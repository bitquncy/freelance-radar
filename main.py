"""Main entry point for FreelanceRadar bot v2."""
import asyncio
import re
import signal
import sys
from pathlib import Path

import telegram.error
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

sys.path.insert(0, str(Path(__file__).parent))

from services.logger_config import configure_logging, get_logger
from services.dependencies import setup_services
from services.event_bus import get_event_bus, Events
from bot.auth import owner_only
from config import BOT_TOKEN, MONITOR_INTERVAL_MINUTES, validate_config
from bot.keyboards import (
    MAIN_MENU_BUTTONS,
    MENU_HELP,
    MENU_JOBS,
    MENU_PROFILE,
    MENU_SETTINGS,
    MENU_SOURCES,
    MENU_STATS,
    settings_keyboard,
)
from bot.commands import (
    start, help_command, check_sources_command,
    blacklist_command, health_command, stats_command, refresh_stats,
    search_command, chart_command,
)
from bot.handlers.sources_handler import (
    sources_menu, list_sources, toggle_source, delete_source, get_sources_handler,
)
from bot.handlers.jobs_handler import jobs_menu, get_jobs_handlers
from bot.handlers.settings_handler import (
    settings_menu, get_settings_handler, filters_menu,
    auto_mode_menu, auto_mode_on, auto_mode_off,
)
from bot.handlers.profile_handler import profile_menu, get_profile_handler
from services.monitor import MonitorService
from services.scheduler import scheduled_check, check_monitor_health, cleanup_blacklist_expired

configure_logging()
logger = get_logger(__name__)

# Initialize DI container and event bus
registry = setup_services()
event_bus = get_event_bus()


async def _metrics_middleware(event):
    """Collect metrics from events."""
    from services.metrics import get_metrics
    metrics = get_metrics()
    if event.name == Events.VACANCIES_FETCHED:
        metrics.counter("vacancies_fetched_total").inc(event.data.get("count", 0))
    elif event.name == Events.VACANCY_ANALYZED:
        metrics.counter("vacancies_analyzed_total").inc()
    elif event.name == Events.VACANCY_NOTIFIED:
        metrics.counter("vacancies_notified_total").inc()
    elif event.name == Events.CHECK_ERROR:
        metrics.counter("check_errors_total").inc()


# Register metrics middleware
event_bus.add_middleware(_metrics_middleware)


@owner_only
async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle main menu button presses."""
    text = update.message.text

    # Сравниваем с теми же константами, из которых собрана клавиатура,
    # иначе смена иконки молча сломала бы реакцию на нажатие.
    if text == MENU_JOBS:
        await jobs_menu(update, context)
    elif text == MENU_SETTINGS:
        await settings_menu(update, context)
    elif text == MENU_SOURCES:
        await sources_menu(update, context)
    elif text == MENU_STATS:
        await stats_command(update, context)
    elif text == MENU_PROFILE:
        await profile_menu(update, context)
    elif text == MENU_HELP:
        await help_command(update, context)


@owner_only
async def handle_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle back to main menu."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "\u0413\u043b\u0430\u0432\u043d\u043e\u0435 \u043c\u0435\u043d\u044e. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0438 \u043d\u0438\u0436\u0435 \u0434\u043b\u044f \u043d\u0430\u0432\u0438\u0433\u0430\u0446\u0438\u0438."
    )


@owner_only
async def handle_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle back to settings menu."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "\u2699\ufe0f \u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u0431\u043e\u0442\u0430", reply_markup=settings_keyboard()
    )


async def _telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log exceptions with safe correlation metadata, never update contents."""
    effective_user = getattr(update, "effective_user", None)
    effective_chat = getattr(update, "effective_chat", None)
    update_id = getattr(update, "update_id", None)
    fields = {
        "error_type": type(context.error).__name__,
        "update_id": update_id,
        "telegram_user_id": getattr(effective_user, "id", None),
        "chat_id": getattr(effective_chat, "id", None),
    }
    if isinstance(context.error, telegram.error.NetworkError):
        logger.warning("telegram.network_error", **fields, exc_info=context.error)
    else:
        logger.error("telegram.error", **fields, exc_info=context.error)


async def _graceful_shutdown(application: Application, scheduler: AsyncIOScheduler) -> None:
    """Perform graceful shutdown of the bot."""
    logger.info("bot.graceful_shutdown_started")

    try:
        scheduler.shutdown(wait=False)
        logger.info("bot.scheduler_stopped")
    except (RuntimeError, ValueError, TypeError) as e:
        logger.error("bot.scheduler_shutdown_error", error=str(e))

    try:
        monitor = MonitorService()
        await monitor.cleanup()
        logger.info("bot.monitor_cleaned")
    except (ValueError, TypeError, ConnectionError, OSError) as e:
        logger.error("bot.monitor_cleanup_error", error=str(e))

    try:
        await application.stop()
        logger.info("bot.application_stopped")
    except (RuntimeError, ValueError, TypeError, telegram.error.NetworkError) as e:
        logger.warning("bot.application_stop_error", error=str(e))

    logger.info("bot.graceful_shutdown_completed")


def main() -> None:
    """Start the bot."""
    try:
        validate_config()
    except ValueError as e:
        logger.error("config.validation_failed", error=str(e))
        sys.exit(1)

    # Initialize database and run migrations before starting the bot
    from db.init_db import init_and_migrate
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_and_migrate())

    from config import get_config
    config = get_config()
    v2_enabled = config.RADAR_V2_ENABLED
    if config.ENVIRONMENT.casefold() == "production":
        if config.DATABASE_URL.startswith("sqlite"):
            raise RuntimeError("Production DATABASE_URL must use PostgreSQL")
        if config.BOT_REPLICAS != 1:
            raise RuntimeError(
                "Local PicklePersistence requires BOT_REPLICAS=1; shared FSM is not configured"
            )
    if v2_enabled:
        # Alembic (not create_all): records alembic_version so future
        # schema migrations apply cleanly on SQLite and PostgreSQL alike.
        from core.db import run_v2_migrations
        run_v2_migrations()
        logger.info("v2.db_migrated")

    builder = Application.builder().token(BOT_TOKEN)
    if v2_enabled:
        # Survive container restarts mid-conversation (onboarding, portfolio
        # add, pending edit/note inputs live in user_data).
        from pathlib import Path as _Path

        import os as _os
        from telegram.ext import PicklePersistence

        state_dir = _Path(_os.environ.get("PTB_STATE_DIR", "data"))
        state_dir.mkdir(parents=True, exist_ok=True)
        builder = builder.persistence(
            PicklePersistence(filepath=str(state_dir / "ptb_state.pickle"))
        )

        async def _v2_post_shutdown(app: Application) -> None:
            """Release V2 resources (PTB restores its own signal handling)."""
            from core.db import dispose_engine
            from core.llm import aclose_shared_llm_client

            await aclose_shared_llm_client()
            await dispose_engine()
            logger.info("v2.resources_released")

        async def _v2_post_init(app: Application) -> None:
            """Publish the ☰ command menu once the bot is initialized."""
            from bot.handlers.v2 import publish_bot_commands

            await publish_bot_commands(app)

        builder = builder.post_init(_v2_post_init)
        builder = builder.post_shutdown(_v2_post_shutdown)
    application = builder.build()

    # Durable Bot API broadcast queue. It is intentionally separate from the
    # read-only Telethon monitoring session required by AGENTS.md §8.
    from services.broadcast import BroadcastRepository, BroadcastRunner

    broadcast_runner = BroadcastRunner(
        bot=application.bot,
        repository=BroadcastRepository(config.DB_PATH),
        rate_limit=config.BROADCAST_RATE_LIMIT,
        batch_size=config.BROADCAST_BATCH_SIZE,
        max_retries=config.BROADCAST_MAX_RETRIES,
        progress_interval=config.BROADCAST_PROGRESS_INTERVAL,
        min_chat_interval_sec=config.BROADCAST_MIN_CHAT_INTERVAL_SEC,
    )
    application.bot_data["broadcast_runner"] = broadcast_runner

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_sources_command))
    application.add_handler(CommandHandler("health", health_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("blacklist", blacklist_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("chart", chart_command))

    # Регулярка собирается из тех же подписей, что и клавиатура (и экранируется),
    # поэтому любая смена иконок остаётся согласованной автоматически.
    menu_pattern = "^(?:{})$".format(
        "|".join(re.escape(label) for label in MAIN_MENU_BUTTONS)
    )
    application.add_handler(MessageHandler(
        filters.Regex(menu_pattern),
        handle_menu_buttons,
    ))

    application.add_handler(get_sources_handler())
    application.add_handler(get_settings_handler())
    application.add_handler(get_profile_handler())

    application.add_handler(CallbackQueryHandler(list_sources, pattern="^list_sources$"))
    application.add_handler(CallbackQueryHandler(toggle_source, pattern="^toggle_source_"))
    application.add_handler(CallbackQueryHandler(delete_source, pattern="^delete_source_"))
    application.add_handler(CallbackQueryHandler(handle_back_to_main, pattern="^back_to_main$"))
    application.add_handler(CallbackQueryHandler(handle_settings_menu, pattern="^settings_menu$"))
    application.add_handler(CallbackQueryHandler(filters_menu, pattern="^settings_filters$"))
    application.add_handler(CallbackQueryHandler(auto_mode_menu, pattern="^settings_auto_mode$"))
    application.add_handler(CallbackQueryHandler(auto_mode_on, pattern="^auto_mode_on$"))
    application.add_handler(CallbackQueryHandler(auto_mode_off, pattern="^auto_mode_off$"))
    application.add_handler(CallbackQueryHandler(refresh_stats, pattern="^refresh_stats$"))

    for handler in get_jobs_handlers():
        application.add_handler(handler)

    from bot.handlers.broadcast_handler import get_broadcast_handlers

    for handler in get_broadcast_handlers():
        application.add_handler(handler)

    if v2_enabled:
        from bot.handlers.v2 import register_v2_handlers
        register_v2_handlers(application)
        logger.info("v2.handlers_registered")

    application.add_error_handler(_telegram_error_handler)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_check,
        "interval",
        minutes=MONITOR_INTERVAL_MINUTES,
        args=[application],
        id="check_sources",
    )
    scheduler.add_job(
        check_monitor_health,
        "interval",
        minutes=30,
        args=[application],
        id="health_check",
    )
    scheduler.add_job(
        cleanup_blacklist_expired,
        "interval",
        hours=1,
        id="cleanup_blacklist",
    )
    scheduler.add_job(
        broadcast_runner.run_due,
        "interval",
        seconds=5,
        id="broadcast_queue",
        max_instances=1,
        coalesce=True,
    )
    if v2_enabled:
        from monitoring.worker import register_v2_jobs
        register_v2_jobs(scheduler, application)
    scheduler.start()

    logger.info("bot.started", interval_minutes=MONITOR_INTERVAL_MINUTES)

    def shutdown_handler(signum, frame):
        logger.info("bot.shutdown_signal_received", signal=signum)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_graceful_shutdown(application, scheduler))
        except (RuntimeError, ValueError, TypeError) as e:
            logger.error("bot.shutdown_error", error=str(e))

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
