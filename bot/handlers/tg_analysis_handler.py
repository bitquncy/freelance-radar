"""Telegram channel/chat analysis handler."""
import aiosqlite
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters

from services.logger_config import get_logger
from bot.auth import owner_only
from bot.keyboards import tg_analysis_keyboard, cancel_keyboard
from db import queries
from config import DB_PATH, OWNER_CHAT_ID

logger = get_logger(__name__)

# Conversation states
ENTERING_CHANNEL_URL, ENTERING_ANALYSIS_TYPE = range(2)


@owner_only
async def tg_analysis_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Telegram analysis menu."""
    await update.message.reply_text(
        "🔍 **Анализ Telegram-каналов/чатов**\n\n"
        "Выберите действие:\n"
        "• 📊 Анализ контента канала\n"
        "• 🎯 Поиск заказов в канале\n"
        "• 📈 Тренды и активность\n"
        "• 🤖 AI-анализ вакансий",
        reply_markup=tg_analysis_keyboard(),
        parse_mode=None
    )


@owner_only
async def analyze_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start channel analysis."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🔍 **Анализ Telegram-канала**\n\n"
        "Введите URL канала (например: @channel_name или https://t.me/channel_name):\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard(),
        parse_mode=None
    )
    return ENTERING_CHANNEL_URL


@owner_only
async def search_jobs_in_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for jobs in a Telegram channel."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🎯 **Поиск заказов в Telegram-канале**\n\n"
        "Введите URL канала (например: @channel_name или https://t.me/channel_name):\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard(),
        parse_mode=None
    )
    return ENTERING_CHANNEL_URL


@owner_only
async def analyze_trends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Analyze trends and activity in a Telegram channel."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📈 **Анализ трендов и активности**\n\n"
        "Введите URL канала (например: @channel_name или https://t.me/channel_name):\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard(),
        parse_mode=None
    )
    return ENTERING_CHANNEL_URL


@owner_only
async def ai_analyze_vacancies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """AI analyze vacancies from a Telegram channel."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        vacancies = await queries.get_vacancies_by_source(db, "telegram", limit=10)

    if not vacancies:
        await query.edit_message_text(
            "🤖 **AI-анализ вакансий**\n\n"
            "Нет вакансий из Telegram для анализа.\n"
            "Сначала добавьте Telegram-канал в источники.",
            reply_markup=tg_analysis_keyboard(),
            parse_mode=None
        )
        return

    text = "🤖 **AI-анализ вакансий из Telegram**\n\n"
    for i, vacancy in enumerate(vacancies, 1):
        text += f"{i}. {vacancy.title[:50]}...\n"
        text += f"   📝 {vacancy.source}\n"
        text += f"   💰 {vacancy.budget or 'N/A'}\n"
        text += f"   ⭐ Score: {vacancy.ai_score or 'N/A'}\n\n"

    await query.edit_message_text(text, reply_markup=tg_analysis_keyboard(), parse_mode=None)


async def process_channel_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process channel URL and perform analysis."""
    url = update.message.text.strip()

    # Parse channel username
    channel = url.replace("https://t.me/", "").replace("t.me/", "").lstrip("@")

    await update.message.reply_text(f"🔍 Анализирую канал @{channel}...")

    # Import the Telegram source parser
    from parsers.telegram_source import TelegramSourceParser
    parser = TelegramSourceParser()
    await parser.connect()

    try:
        vacancies = await parser.fetch_messages_from_channel(f"@{channel}", limit=50)

        if not vacancies:
            await update.message.reply_text(
                f"📊 Канал @{channel} не содержит сообщений с заказами.",
                reply_markup=tg_analysis_keyboard()
            )
            return ConversationHandler.END

        # Analyze the vacancies
        text = f"📊 **Анализ канала @{channel}**\n\n"
        text += f"Найдено сообщений: {len(vacancies)}\n\n"

        # Group by category
        categories = {}
        for v in vacancies:
            cat = v.category or "Без категории"
            if cat not in categories:
                categories[cat] = 0
            categories[cat] += 1

        text += "**Категории:**\n"
        for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
            text += f"• {cat}: {count}\n"

        # Budget analysis
        budgets = []
        for v in vacancies:
            if v.budget_min:
                budgets.append(v.budget_min)
            if v.budget_max:
                budgets.append(v.budget_max)

        if budgets:
            text += f"\n**Бюджет:**\n"
            text += f"• Мин: {min(budgets)} ₽\n"
            text += f"• Макс: {max(budgets)} ₽\n"
            text += f"• Средний: {sum(budgets) // len(budgets)} ₽\n"

        # Skills analysis
        all_skills = []
        for v in vacancies:
            if v.skills:
                all_skills.extend(v.skills_list)

        if all_skills:
            from collections import Counter
            skill_counts = Counter(all_skills)
            text += f"\n**Топ навыков:**\n"
            for skill, count in skill_counts.most_common(10):
                text += f"• {skill}: {count}\n"

        await update.message.reply_text(text, reply_markup=tg_analysis_keyboard(), parse_mode=None)

    finally:
        await parser.disconnect()

    return ConversationHandler.END


def get_tg_analysis_handler() -> ConversationHandler:
    """Get the TG analysis conversation handler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(analyze_channel, pattern="^tg_analyze_channel$"),
            CallbackQueryHandler(search_jobs_in_channel, pattern="^tg_search_jobs$"),
            CallbackQueryHandler(analyze_trends, pattern="^tg_analyze_trends$"),
        ],
        states={
            ENTERING_CHANNEL_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_channel_url)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern="^cancel$"),
            MessageHandler(filters.COMMAND, cancel),
        ],
        per_user=True,
        per_chat=True,
        name="tg_analysis_conversation",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "❌ Операция отменена.",
            reply_markup=tg_analysis_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Операция отменена.",
            reply_markup=tg_analysis_keyboard()
        )
    return ConversationHandler.END
