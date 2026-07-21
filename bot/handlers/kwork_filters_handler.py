"""Kwork-specific filters handler for AI-friendly orders."""
import aiosqlite
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters

from services.logger_config import get_logger
from bot.auth import owner_only
from bot.keyboards import kwork_filters_keyboard, ai_friendly_filter_keyboard, cancel_keyboard
from db import queries
from db.models import FreelancerProfile
from config import DB_PATH, OWNER_CHAT_ID

logger = get_logger(__name__)

# Conversation states
ENTERING_AI_FILTER_SETTINGS, ENTERING_BUDGET_FILTER, ENTERING_DEADLINE_FILTER, ENTERING_SKILLS_FILTER = range(4)


@owner_only
async def kwork_filters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Kwork-specific filters menu."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🔍 **Фильтры для Kwork**\n\n"
        "Выберите фильтр для настройки:\n\n"
        "🤖 AI-дружественные заказы — заказы, которые можно выполнить с помощью ИИ\n"
        "💼 Простые задачи — заказы с минимальными требованиями\n"
        "📊 Фильтр по бюджету — настройка диапазона бюджета\n"
        "⏱ Фильтр по срокам — настройка сроков выполнения\n"
        "🏷 Фильтр по навыкам — фильтрация по необходимым навыкам",
        reply_markup=kwork_filters_keyboard(),
        parse_mode=None
    )


@owner_only
async def ai_friendly_filter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show AI-friendly filter settings."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    text = "🤖 **AI-дружественные заказы**\n\n"
    text += "Эти фильтры помогут найти заказы, которые можно выполнить с помощью ИИ:\n\n"
    text += "• 🎯 **ИИ-генерация** — тексты, статьи, контент\n"
    text += "• 🎯 **Вайб-кодинг** — генерация кода, отладка\n"
    text += "• 🎯 **Авто-тестирование** — написание тестов\n"
    text += "• 🎯 **Дизайн** — генерация изображений, макетов\n"
    text += "• 🎯 **Анализ данных** — парсинг, обработка\n\n"

    if profile and hasattr(profile, 'ai_friendly_enabled'):
        text += f"Текущий статус: {'✅ Включен' if profile.ai_friendly_enabled else '❌ Выключен'}\n"

    await query.edit_message_text(text, reply_markup=ai_friendly_filter_keyboard(), parse_mode=None)


@owner_only
async def enable_ai_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable AI-friendly filter."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)
        if profile:
            profile.ai_friendly_enabled = True
            await queries.save_freelancer_profile(db, profile)

    await query.edit_message_text(
        "✅ AI-фильтр включён!\n\n"
        "Теперь бот будет искать заказы, которые можно выполнить с помощью ИИ.",
        reply_markup=ai_friendly_filter_keyboard()
    )


@owner_only
async def disable_ai_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable AI-friendly filter."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)
        if profile:
            profile.ai_friendly_enabled = False
            await queries.save_freelancer_profile(db, profile)

    await query.edit_message_text(
        "❌ AI-фильтр выключен.",
        reply_markup=ai_friendly_filter_keyboard()
    )


@owner_only
async def set_ai_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set AI task type filter."""
    query = update.callback_query
    await query.answer()

    task_type = query.data.replace("ai_task_type_", "")

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)
        if profile:
            profile.ai_task_type = task_type
            await queries.save_freelancer_profile(db, profile)

    task_names = {
        "generate": "ИИ-генерация",
        "vibe": "Вайб-кодинг",
        "test": "Авто-тестирование"
    }
    task_name = task_names.get(task_type, task_type)

    await query.edit_message_text(
        f"✅ Тип задачи установлен: {task_name}\n\n"
        "Теперь бот будет искать заказы этого типа.",
        reply_markup=ai_friendly_filter_keyboard()
    )


@owner_only
async def simple_tasks_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show simple tasks filter settings."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💼 **Простые задачи**\n\n"
        "Эти фильтры помогут найти заказы с минимальными требованиями:\n\n"
        "• 📝 Написание текстов\n"
        "• 🔍 Парсинг данных\n"
        "• 📊 Обработка данных\n"
        "• 🎨 Простой дизайн\n"
        "• 📱 Простая вёрстка\n\n"
        "Настройте фильтры для поиска простых задач.",
        reply_markup=kwork_filters_keyboard(),
        parse_mode=None
    )


@owner_only
async def budget_filter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start budget filter configuration."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📊 **Фильтр по бюджету**\n\n"
        "Введите диапазон бюджета в формате: мин макс\n"
        "Например: 5000 50000\n\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard(),
        parse_mode=None
    )
    return ENTERING_BUDGET_FILTER


@owner_only
async def save_budget_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save budget filter settings."""
    text = update.message.text.strip()
    parts = text.split()

    if len(parts) != 2:
        await update.message.reply_text(
            "❌ Неверный формат. Используйте: мин макс\nНапример: 5000 50000"
        )
        return ENTERING_BUDGET_FILTER

    try:
        min_budget = int(parts[0])
        max_budget = int(parts[1])
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Используйте числа.\nНапример: 5000 50000"
        )
        return ENTERING_BUDGET_FILTER

    if min_budget < 0 or max_budget < 0:
        await update.message.reply_text(
            "❌ Бюджет не может быть отрицательным."
        )
        return ENTERING_BUDGET_FILTER

    if min_budget > max_budget:
        await update.message.reply_text(
            "❌ Минимальный бюджет не может быть больше максимального."
        )
        return ENTERING_BUDGET_FILTER

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)
        if profile:
            profile.min_budget = min_budget
            profile.max_budget = max_budget
            await queries.save_freelancer_profile(db, profile)

    await update.message.reply_text(
        f"✅ Диапазон бюджета сохранён: {min_budget} - {max_budget} руб.",
        reply_markup=kwork_filters_keyboard()
    )
    return ConversationHandler.END


@owner_only
async def deadline_filter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start deadline filter configuration."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "⏱ **Фильтр по срокам**\n\n"
        "Введите максимальный срок выполнения в днях:\n"
        "Например: 14\n\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard(),
        parse_mode=None
    )
    return ENTERING_DEADLINE_FILTER


@owner_only
async def save_deadline_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save deadline filter settings."""
    try:
        days = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Используйте число (дни).")
        return ENTERING_DEADLINE_FILTER

    if days <= 0:
        await update.message.reply_text("❌ Срок должен быть положительным числом.")
        return ENTERING_DEADLINE_FILTER

    if days > 365:
        await update.message.reply_text("❌ Срок не может быть больше 365 дней.")
        return ENTERING_DEADLINE_FILTER

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)
        if profile:
            profile.max_deadline_days = days
            await queries.save_freelancer_profile(db, profile)

    await update.message.reply_text(
        f"✅ Максимальный срок сохранён: {days} дней",
        reply_markup=kwork_filters_keyboard()
    )
    return ConversationHandler.END


@owner_only
async def skills_filter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start skills filter configuration."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🏷 **Фильтр по навыкам**\n\n"
        "Введите навыки через запятую (навыки, которые должны быть в заказе):\n"
        "Например: Python, Django, React\n\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard(),
        parse_mode=None
    )
    return ENTERING_SKILLS_FILTER


@owner_only
async def save_skills_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save skills filter settings."""
    skills = update.message.text.strip()
    await _save_profile_field(update, "required_skills", skills)
    return ConversationHandler.END


async def _save_profile_field(update: Update, field_name: str, value) -> None:
    """Helper to save a profile field."""
    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)
        if not profile:
            profile = FreelancerProfile(id=None, user_id=OWNER_CHAT_ID)
        setattr(profile, field_name, value)
        await queries.save_freelancer_profile(db, profile)

    await update.message.reply_text(f"✅ {field_name} сохранён!")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "❌ Операция отменена.",
            reply_markup=kwork_filters_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Операция отменена.",
            reply_markup=kwork_filters_keyboard()
        )
    return ConversationHandler.END


def get_kwork_filters_handler() -> ConversationHandler:
    """Get the Kwork filters conversation handler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(budget_filter_menu, pattern="^kwork_filter_budget$"),
            CallbackQueryHandler(deadline_filter_menu, pattern="^kwork_filter_deadline$"),
            CallbackQueryHandler(skills_filter_menu, pattern="^kwork_filter_skills$"),
        ],
        states={
            ENTERING_BUDGET_FILTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_budget_filter)
            ],
            ENTERING_DEADLINE_FILTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_deadline_filter)
            ],
            ENTERING_SKILLS_FILTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_skills_filter)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern="^cancel$"),
            MessageHandler(filters.COMMAND, cancel),
        ],
        per_user=True,
        per_chat=True,
        name="kwork_filters_conversation",
    )
