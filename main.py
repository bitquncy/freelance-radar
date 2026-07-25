"""Main entry point for FreelanceRadar bot v2."""
import asyncio
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

    if text == "\U0001f4cb \u0412\u0430\u043a\u0430\u043d\u0441\u0438\u0438":
        await jobs_menu(update, context)
    elif text == "\u2699\ufe0f \u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438":
        await settings_menu(update, context)
    elif text == "\U0001f4e1 \u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438":
        await sources_menu(update, context)
    elif text == "\U0001f4ca \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430":
        await stats_command(update, context)
    elif text == "\U0001f464 \u041f\u0440\u043e\u0444\u0438\u043b\u044c":
        await profile_menu(update, context)
    elif text == "\u2753 \u041f\u043e\u043c\u043e\u0449\u044c":
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
    """Handle telegram errors. Suppress network errors during shutdown."""
    if isinstance(context.error, telegram.error.NetworkError):
        logger.warning("telegram.network_error", error=str(context.error))
    else:
        logger.error("telegram.error", error=str(context.error))


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
    v2_enabled = get_config().RADAR_V2_ENABLED
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

        builder = builder.post_shutdown(_v2_post_shutdown)
    application = builder.build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_sources_command))
    application.add_handler(CommandHandler("health", health_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("blacklist", blacklist_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("chart", chart_command))

    application.add_handler(MessageHandler(
        filters.Regex("^(\\U0001f4cb \u0412\u0430\u043a\u0430\u043d\u0441\u0438\u0438|\\u2699\\ufe0f \u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438|\\U0001f4e1 \u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438|\\U0001f4ca \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430|\\U0001f464 \u041f\u0440\u043e\u0444\u0438\u043b\u044c|\\u2753 \u041f\u043e\u043c\u043e\u0449\u044c)$"),
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
