"""Bot commands for FreelanceRadar."""
import io
import aiosqlite
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from services.logger_config import get_logger
from bot.auth import check_owner, deny_access, owner_only
from bot.keyboards import main_menu_keyboard, stats_keyboard
from services.rate_limiter import KworkRateLimiter
from services.blacklist import BlacklistService
from services.charts import (
    generate_vacancy_stats_chart,
    generate_source_distribution_chart,
    generate_priority_distribution_chart,
    generate_daily_activity_chart,
)
from telegram import InputFile
from db import queries
from config import DB_PATH

logger = get_logger(__name__)


def _md_escape(value: object) -> str:
    """Escape MarkdownV1 special chars in untrusted text before interpolation.

    Telegram MarkdownV1 treats ``_``, ``*``, ``[`` and backtick as markup, so a
    user-typed search query or a scraped title containing them breaks parsing
    (silent message loss) — E-3. HTML-like chars are irrelevant for MarkdownV1.
    """
    return (
        str(value if value is not None else "")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — the very first screen every user sees.

    Open to everyone when the multi-tenant V2 is enabled: a paying customer
    must never be greeted with "у вас нет доступа". Owner-only admin
    commands stay decorated individually. Legacy single-owner installs
    (V2 off) keep the old restricted behaviour.
    """
    from config import get_config

    if not get_config().RADAR_V2_ENABLED:
        if not check_owner(update):
            await deny_access(update)
            return
        await update.message.reply_text(
            "\U0001f44b Добро пожаловать в FreelanceRadar!\n\n"
            "Я помогу мониторить фриланс-биржи и находить подходящие заказы.\n\n"
            "Используйте меню ниже для управления:",
            reply_markup=main_menu_keyboard(),
        )
        return

    from bot.handlers.v2.onboarding import radar_entry

    await radar_entry(update, context)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — user-facing help (V2) or the legacy owner cheatsheet."""
    from config import get_config

    if get_config().RADAR_V2_ENABLED:
        from bot.handlers.v2.menu import show_help

        await show_help(update, context)
        return
    if not check_owner(update):
        await deny_access(update)
        return
    help_text = """
\U0001f4d6 **\u0421\u043f\u0440\u0430\u0432\u043a\u0430 \u043f\u043e FreelanceRadar**

**\u041e\u0441\u043d\u043e\u0432\u043d\u044b\u0435 \u043a\u043e\u043c\u0430\u043d\u0434\u044b:**
/start \u2014 \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u0431\u043e\u0442\u0430
/help \u2014 \u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u044d\u0442\u0443 \u0441\u043f\u0440\u0430\u0432\u043a\u0443
/check \u2014 \u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438 \u0432\u0440\u0443\u0447\u043d\u0443\u044e
/health \u2014 \u0421\u0442\u0430\u0442\u0443\u0441 \u0441\u0438\u0441\u0442\u0435\u043c\u044b
/stats \u2014 \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439
/blacklist \u2014 \u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0447\u0451\u0440\u043d\u044b\u043c \u0441\u043f\u0438\u0441\u043a\u043e\u043c

**\u0420\u0430\u0437\u0434\u0435\u043b\u044b:**
\U0001f4cb \u0412\u0430\u043a\u0430\u043d\u0441\u0438\u0438 \u2014 \u041f\u0440\u043e\u0441\u043c\u043e\u0442\u0440 \u043d\u043e\u0432\u044b\u0445 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439
\u2699\ufe0f \u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u2014 \u041f\u0440\u043e\u043c\u043f\u0442\u044b, \u0431\u044e\u0434\u0436\u0435\u0442, \u043a\u0443\u043b\u0434\u0430\u0443\u043d, \u0444\u0438\u043b\u044c\u0442\u0440\u044b
\U0001f4e1 \u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438 \u2014 \u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0430\u043c\u0438
\U0001f464 \u041f\u0440\u043e\u0444\u0438\u043b\u044c \u2014 \u041f\u0440\u043e\u0444\u0438\u043b\u044c \u0444\u0440\u0438\u043b\u0430\u043d\u0441\u0435\u0440\u0430
\U0001f4ca \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u2014 \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u043f\u043e \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u044f\u043c
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


@owner_only
async def check_sources_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually trigger source check with streaming progress."""
    from services.scheduler import check_and_notify_streaming

    logger.info("bot.manual_check_triggered", user_id=update.effective_user.id)

    progress_msg = await update.message.reply_text(
        "\U0001f504 \u041f\u043e\u043b\u0443\u0447\u0430\u044e \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0438..."
    )

    await check_and_notify_streaming(
        context.application,
        is_scheduled=False,
        progress_message=progress_msg,
    )


@owner_only
async def blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /blacklist command."""
    bs = BlacklistService(DB_PATH)
    entries = await bs.get_blacklist()

    if not entries:
        await update.message.reply_text(
            "\U0001f4cb \u0427\u0451\u0440\u043d\u044b\u0439 \u0441\u043f\u0438\u0441\u043e\u043a \u043f\u0443\u0441\u0442.", reply_markup=main_menu_keyboard()
        )
        return

    text = "\U0001f6ab **\u0427\u0451\u0440\u043d\u044b\u0439 \u0441\u043f\u0438\u0441\u043e\u043a:**\n\n"
    for i, entry in enumerate(entries, 1):
        text += f"{i}. {entry.entity_type}: {entry.entity_id}"
        if entry.reason:
            text += f" (\u043f\u0440\u0438\u0447\u0438\u043d\u0430: {entry.reason})"
        if entry.expires_at:
            text += f" [\u0434\u043e {entry.expires_at.strftime('%d.%m.%Y')}]"
        text += "\n"

    text += "\n\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0438 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439 \u0434\u043b\u044f \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0438\u044f/\u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f."

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())


@owner_only
async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show comprehensive system health status."""
    from services.scheduler import get_state

    state = get_state()

    kwork_limiter = KworkRateLimiter()
    kwork_status = kwork_limiter.get_status()

    minutes_since_check = (datetime.now() - state.last_check_time).total_seconds() / 60
    check_status = "\u2705" if minutes_since_check < 40 else "\u26a0\ufe0f"

    db_ok = False
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("SELECT 1")
            db_ok = True
    except (aiosqlite.Error, OSError):
        pass

    text = "\U0001f3e5 **\u0421\u0442\u0430\u0442\u0443\u0441 \u0441\u0438\u0441\u0442\u0435\u043c\u044b**\n\n"
    text += f"{check_status} \u041c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433: \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u044f\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 {int(minutes_since_check)} \u043c\u0438\u043d \u043d\u0430\u0437\u0430\u0434\n"
    text += "\u2705 \u0411\u043e\u0442: \u043e\u043d\u043b\u0430\u0439\u043d\n"
    db_status = "\u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0430" if db_ok else "\u043e\u0448\u0438\u0431\u043a\u0430"
    db_icon = "\u2705" if db_ok else "\u274c"
    text += f"{db_icon} \u0411\u0430\u0437\u0430 \u0434\u0430\u043d\u043d\u044b\u0445: {db_status}\n"
    text += "\u2705 OpenAI API: \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\n"
    text += "\u2705 Telegram API: \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\n\n"

    text += "**Kwork \u043f\u0430\u0440\u0441\u0435\u0440:**\n"
    text += f"  \u0417\u0430\u043f\u0440\u043e\u0441\u043e\u0432 \u0441\u0435\u0433\u043e\u0434\u043d\u044f: {kwork_status['requests_today']}/{kwork_status['daily_limit']}\n"
    text += f"  \u041e\u0441\u0442\u0430\u043b\u043e\u0441\u044c: {kwork_status['remaining']}\n\n"

    text += "**\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u044f\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430:**\n"
    text += f"  \u041d\u0430\u0439\u0434\u0435\u043d\u043e \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439: {state.last_check_count}\n"
    if state.last_check_errors:
        text += f"  \u041e\u0448\u0438\u0431\u043a\u0438: {len(state.last_check_errors)}\n"

    text += "\n\u0412\u0441\u0451 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442 \u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e \U0001f680" if minutes_since_check < 40 and db_ok else "\n\u26a0\ufe0f \u041e\u0431\u0440\u0430\u0442\u0438\u0442\u0435 \u0432\u043d\u0438\u043c\u0430\u043d\u0438\u0435 \u043d\u0430 \u043f\u0440\u0435\u0434\u0443\u043f\u0440\u0435\u0436\u0434\u0435\u043d\u0438\u044f"

    await update.message.reply_text(text, parse_mode="Markdown")


@owner_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed vacancy statistics."""
    async with aiosqlite.connect(DB_PATH) as db:
        stats = await queries.get_vacancy_stats(db)
        total = stats.get("total", 0)
        unseen = stats.get("unseen", 0)
        responded = stats.get("responded", 0)
        filtered = stats.get("filtered_out", 0)
        high = stats.get("high_priority", 0)

        seen = total - unseen
        response_rate = (responded / seen * 100) if seen > 0 else 0
        filter_rate = (filtered / total * 100) if total > 0 else 0
        high_rate = (high / total * 100) if total > 0 else 0

    text = "\U0001f4ca **\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439**\n\n"
    text += f"\U0001f4e6 \u0412\u0441\u0435\u0433\u043e: {total}\n"
    text += f"\U0001f440 \u041d\u043e\u0432\u044b\u0445: {unseen}\n"
    text += f"\u2705 \u041f\u0440\u043e\u0441\u043c\u043e\u0442\u0440\u0435\u043d\u043e: {seen}\n"
    text += f"\U0001f4ac \u041e\u0442\u043a\u043b\u0438\u043a\u043d\u0443\u0442\u043e: {responded} ({response_rate:.1f}%)\n"
    text += f"\U0001f6ab \u041e\u0442\u0444\u0438\u043b\u044c\u0442\u0440\u043e\u0432\u0430\u043d\u043e: {filtered} ({filter_rate:.1f}%)\n"
    text += f"\U0001f534 High priority: {high} ({high_rate:.1f}%)\n\n"

    if stats.get("by_source"):
        text += "**\u041f\u043e \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0430\u043c:**\n"
        for source, count in stats["by_source"].items():
            pct = (count / total * 100) if total > 0 else 0
            text += f"  \u2022 {source}: {count} ({pct:.1f}%)\n"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=stats_keyboard())


@owner_only
async def refresh_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh stats display."""
    query = update.callback_query
    await query.answer("\u041e\u0431\u043d\u043e\u0432\u043b\u044f\u044e...")
    await stats_command(update, context)


@owner_only
async def chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send vacancy statistics charts."""
    from telegram.error import TelegramError

    await update.message.reply_text("\U0001f4c8 Генерирую графики...")

    async with aiosqlite.connect(DB_PATH) as db:
        stats = await queries.get_vacancy_stats(db)
        daily = await queries.get_daily_vacancy_counts(db, days=14)

    total = stats.get("total", 0)
    if total == 0:
        await update.message.reply_text("\U0001f4c9 Нет данных для построения графиков.")
        return

    sent = 0

    # Chart 1: Status distribution
    img = generate_vacancy_stats_chart(stats)
    if img:
        try:
            await update.message.reply_photo(
                photo=InputFile(io.BytesIO(img), filename="stats.png"),
                caption="\U0001f4ca Распределение статусов вакансий",
            )
            sent += 1
        except (TelegramError, ValueError, TypeError) as e:
            logger.warning("chart.send_failed", chart="stats", error=str(e))

    # Chart 2: Source distribution
    if stats.get("by_source"):
        img = generate_source_distribution_chart(stats["by_source"])
        if img:
            try:
                await update.message.reply_photo(
                    photo=InputFile(io.BytesIO(img), filename="sources.png"),
                    caption="\U0001f4e1 Распределение по источникам",
                )
                sent += 1
            except (TelegramError, ValueError, TypeError) as e:
                logger.warning("chart.send_failed", chart="sources", error=str(e))

    # Chart 3: Priority distribution
    high = stats.get("high_priority", 0)
    img = generate_priority_distribution_chart(
        high,
        total - high - stats.get("filtered_out", 0) - stats.get("unseen", 0),
        stats.get("unseen", 0),
    )
    if img:
        try:
            await update.message.reply_photo(
                photo=InputFile(io.BytesIO(img), filename="priority.png"),
                caption="\U0001f525 Распределение по приоритету",
            )
            sent += 1
        except (TelegramError, ValueError, TypeError) as e:
            logger.warning("chart.send_failed", chart="priority", error=str(e))

    # Chart 4: Daily activity
    if daily:
        img = generate_daily_activity_chart(daily)
        if img:
            try:
                await update.message.reply_photo(
                    photo=InputFile(io.BytesIO(img), filename="activity.png"),
                    caption="\U0001f4c5 Активность по дням (14 дней)",
                )
                sent += 1
            except (TelegramError, ValueError, TypeError) as e:
                logger.warning("chart.send_failed", chart="activity", error=str(e))

    if sent == 0:
        await update.message.reply_text("\u274c Не удалось сгенерировать графики.")


@owner_only
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command with FTS."""
    query = " ".join(context.args) if context.args else ""

    # Input validation
    query = query.strip()[:200]  # Max 200 chars
    if not query:
        await update.message.reply_text(
            "\U0001f50d **\u041f\u043e\u0438\u0441\u043a**\n\n"
            "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: `/search <\u0437\u0430\u043f\u0440\u043e\u0441>`\n\n"
            "\u041f\u0440\u0438\u043c\u0435\u0440\u044b:\n"
            "\u2022 `/search python`\n"
            "\u2022 `/search \"machine learning\"`\n"
            "\u2022 `/search python AND django`\n"
            "\u2022 `/search backend NOT java`",
            parse_mode="Markdown",
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            results = await queries.search_vacancies(db, query, limit=20)
        except (aiosqlite.Error, ValueError, TypeError):
            # Fallback to LIKE search if FTS fails
            results = await queries.search_vacancies_by_title(db, query, limit=20)

    if not results:
        await update.message.reply_text(
            f"\U0001f50d \u041f\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u0443 `{_md_escape(query)}` \u043d\u0438\u0447\u0435\u0433\u043e \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e.",
            parse_mode="Markdown",
        )
        return

    text = f"\U0001f50d **\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b \u043f\u043e\u0438\u0441\u043a\u0430:** `{_md_escape(query)}`\n\n"
    for i, vacancy in enumerate(results, 1):
        priority_emoji = "\U0001f525" if vacancy.ai_priority == "high" else "\u2b50" if vacancy.ai_priority == "medium" else "\U0001f4cc"
        budget = vacancy.budget or f"{vacancy.budget_min or 0}-{vacancy.budget_max or 0} \u20bd"
        title_escaped = _md_escape(vacancy.title[:50])
        text += (
            f"{i}. {priority_emoji} [{title_escaped}]({vacancy.url})\n"
            f"   \U0001f4b0 {budget} | \U0001f4c5 {vacancy.deadline or 'N/A'} | \u2b50 {vacancy.ai_score or 'N/A'}\n\n"
        )

    text += f"\u041d\u0430\u0439\u0434\u0435\u043d\u043e: {len(results)}"
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
