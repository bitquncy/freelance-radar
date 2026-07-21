"""Settings handler for managing user preferences and filters."""
from typing import Optional
import aiosqlite
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)

from services.logger_config import get_logger
from bot.auth import owner_only
from bot.keyboards import (
    settings_keyboard, filters_settings_keyboard, auto_mode_keyboard,
    cancel_keyboard
)
from db import queries
from db.models import UserSettings, FreelancerProfile
from config import DB_PATH, OWNER_CHAT_ID, DEFAULT_COOLDOWN_SEC

logger = get_logger(__name__)

# Conversation states
(
    ENTERING_ANALYSIS_PROMPT, ENTERING_RESPONSE_PROMPT, ENTERING_BUDGET,
    ENTERING_COOLDOWN, ENTERING_WHITELIST, ENTERING_BLACKLIST,
    ENTERING_MIN_RATING, ENTERING_MAX_PROPOSALS, ENTERING_AUTO_DELAY
) = range(9)


@owner_only
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show settings menu."""
    await update.message.reply_text(
        "⚙️ Настройки бота",
        reply_markup=settings_keyboard()
    )


# --- Prompts ---

@owner_only
async def settings_analysis_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing analysis prompt."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        settings = await queries.get_user_settings(db, OWNER_CHAT_ID)

    current = settings.analysis_prompt if settings and settings.analysis_prompt else "Не установлен"

    await query.edit_message_text(
        f"📝 Текущий промпт для анализа:\n\n{current}\n\n"
        "Отправьте новый промпт или /cancel для отмены:",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_ANALYSIS_PROMPT


@owner_only
async def save_analysis_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save analysis prompt."""
    prompt = update.message.text.strip()[:2000]  # Max 2000 chars
    await _save_user_setting(update, analysis_prompt=prompt)
    return ConversationHandler.END


@owner_only
async def settings_response_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing response prompt."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        settings = await queries.get_user_settings(db, OWNER_CHAT_ID)

    current = settings.response_prompt if settings and settings.response_prompt else "Не установлен"

    await query.edit_message_text(
        f"💬 Текущий промпт для откликов:\n\n{current}\n\n"
        "Отправьте новый промпт или /cancel для отмены:",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_RESPONSE_PROMPT


@owner_only
async def save_response_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save response prompt."""
    prompt = update.message.text.strip()[:2000]  # Max 2000 chars
    await _save_user_setting(update, response_prompt=prompt)
    return ConversationHandler.END


# --- Budget ---

@owner_only
async def settings_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing budget range."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        settings = await queries.get_user_settings(db, OWNER_CHAT_ID)

    if settings and (settings.min_budget or settings.max_budget):
        current = f"От {settings.min_budget or 'не указано'} до {settings.max_budget or 'не указано'} руб."
    else:
        current = "Не установлен"

    await query.edit_message_text(
        f"💰 Текущий диапазон бюджета:\n\n{current}\n\n"
        "Отправьте диапазон в формате: мин макс\n"
        "Например: 5000 50000\n\n"
        "Или /cancel для отмены:",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_BUDGET


@owner_only
async def save_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save budget range."""
    text = update.message.text.strip()
    parts = text.split()

    if len(parts) != 2:
        await update.message.reply_text(
            "❌ Неверный формат. Используйте: мин макс\nНапример: 5000 50000"
        )
        return ENTERING_BUDGET

    try:
        min_budget = int(parts[0])
        max_budget = int(parts[1])
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Используйте числа.\nНапример: 5000 50000"
        )
        return ENTERING_BUDGET

    if min_budget < 0 or max_budget < 0:
        await update.message.reply_text(
            "❌ Бюджет не может быть отрицательным."
        )
        return ENTERING_BUDGET

    if min_budget > max_budget:
        await update.message.reply_text(
            "❌ Минимальный бюджет не может быть больше максимального."
        )
        return ENTERING_BUDGET

    await _save_user_setting(update, min_budget=min_budget, max_budget=max_budget)
    await update.message.reply_text(
        f"✅ Диапазон бюджета сохранён: {min_budget} - {max_budget} руб.",
        reply_markup=settings_keyboard()
    )
    return ConversationHandler.END


# --- Cooldown ---

@owner_only
async def settings_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing cooldown."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        settings = await queries.get_user_settings(db, OWNER_CHAT_ID)

    current = settings.cooldown_seconds if settings else DEFAULT_COOLDOWN_SEC
    current_minutes = current // 60

    await query.edit_message_text(
        f"⏱ Текущий кулдаун: {current_minutes} минут\n\n"
        "Отправьте новое значение в минутах или /cancel для отмены:",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_COOLDOWN


@owner_only
async def save_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save cooldown."""
    try:
        minutes = int(update.message.text.strip())
        seconds = minutes * 60
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Используйте число (минуты).")
        return ENTERING_COOLDOWN

    if minutes <= 0:
        await update.message.reply_text("❌ Кулдаун должен быть положительным числом.")
        return ENTERING_COOLDOWN

    if minutes > 1440:  # 24 hours
        await update.message.reply_text("❌ Кулдаун не может быть больше 24 часов (1440 минут).")
        return ENTERING_COOLDOWN

    await _save_user_setting(update, cooldown_seconds=seconds)
    await update.message.reply_text(
        f"✅ Кулдаун сохранён: {minutes} минут",
        reply_markup=settings_keyboard()
    )
    return ConversationHandler.END


# --- Filters Menu ---

@owner_only
async def filters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show filter settings menu."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    text = "🔍 **Настройки фильтров**\n\n"
    if profile:
        if profile.whitelist_words:
            whitelist_list = profile.whitelist_words_list
            text += f"📜 Белый список: {', '.join(whitelist_list)}\n"
        if profile.blacklist_words:
            blacklist_list = profile.blacklist_words_list
            text += f"🚫 Чёрный список: {', '.join(blacklist_list)}\n"
        if profile.min_customer_rating:
            text += f"⭐ Мин. рейтинг: {profile.min_customer_rating}\n"
        if profile.max_proposals_count:
            text += f"📊 Макс. предложений: {profile.max_proposals_count}\n"
        text += f"🤖 Авто-режим: {'✅' if profile.auto_mode_enabled else '❌'}"
    else:
        text += "Фильтры не настроены."

    await query.edit_message_text(text, reply_markup=filters_settings_keyboard(), parse_mode="Markdown")


# --- Whitelist ---

@owner_only
async def settings_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing whitelist."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.whitelist_words_list if profile and profile.whitelist_words else "Не установлен"

    await query.edit_message_text(
        f"📜 Текущий белый список:\n\n{current}\n\n"
        "Введите слова через запятую (вакансия должна содержать хотя бы одно):\n"
        "Например: python, django, backend\n\n"
        "Или /cancel для отмены:",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_WHITELIST


@owner_only
async def save_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save whitelist words."""
    words = update.message.text.strip()
    await _save_profile_field(update, "whitelist_words", words)
    return ConversationHandler.END


# --- Blacklist ---

@owner_only
async def settings_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing blacklist."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.blacklist_words_list if profile and profile.blacklist_words else "Не установлен"

    await query.edit_message_text(
        f"🚫 Текущий чёрный список:\n\n{current}\n\n"
        "Введите слова через запятую (вакансия будет отфильтрована, если содержит любое):\n"
        "Например: бесплатно, тестовое, стажировка\n\n"
        "Или /cancel для отмены:",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_BLACKLIST


@owner_only
async def save_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save blacklist words."""
    words = update.message.text.strip()
    await _save_profile_field(update, "blacklist_words", words)
    return ConversationHandler.END


# --- Min Rating ---

@owner_only
async def settings_min_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing min customer rating."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.min_customer_rating if profile and profile.min_customer_rating else "Не установлен"

    await query.edit_message_text(
        f"⭐ Текущий мин. рейтинг заказчика:\n\n{current}\n\n"
        "Введите минимальный рейтинг (число, например 4.5):\n"
        "Или /cancel для отмены:",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_MIN_RATING


@owner_only
async def save_min_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save min customer rating."""
    try:
        rating = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите число. Например: 4.5")
        return ENTERING_MIN_RATING

    if rating < 0 or rating > 5:
        await update.message.reply_text("❌ Рейтинг должен быть от 0 до 5.")
        return ENTERING_MIN_RATING

    await _save_profile_field(update, "min_customer_rating", rating)
    return ConversationHandler.END


# --- Max Proposals ---

@owner_only
async def settings_max_proposals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing max proposals count."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.max_proposals_count if profile and profile.max_proposals_count else "Не установлен"

    await query.edit_message_text(
        f"📊 Текущий макс. предложений:\n\n{current}\n\n"
        "Введите максимальное количество предложений (число):\n"
        "Или /cancel для отмены:",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_MAX_PROPOSALS


@owner_only
async def save_max_proposals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save max proposals count."""
    try:
        count = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите число. Например: 20")
        return ENTERING_MAX_PROPOSALS

    if count <= 0:
        await update.message.reply_text("❌ Количество должно быть положительным числом.")
        return ENTERING_MAX_PROPOSALS

    await _save_profile_field(update, "max_proposals_count", count)
    return ConversationHandler.END


# --- Auto Mode ---

@owner_only
async def auto_mode_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show auto mode settings."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    text = "🤖 **Авто-режим**\n\n"
    if profile:
        status = "✅ Включен" if profile.auto_mode_enabled else "❌ Выключен"
        text += f"Статус: {status}\n"
        text += f"Задержка: {profile.auto_mode_delay_minutes} минут\n\n"
        text += (
            "При включённом авто-режиме бот автоматически предлагает "
            "сгенерировать отклик для high-priority вакансий."
        )
    else:
        text += "Авто-режим не настроен."

    await query.edit_message_text(text, reply_markup=auto_mode_keyboard(), parse_mode="Markdown")


@owner_only
async def auto_mode_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable auto mode."""
    query = update.callback_query
    await query.answer()
    await _save_profile_field(update, "auto_mode_enabled", True, silent=True)
    await query.edit_message_text("✅ Авто-режим включён!", reply_markup=auto_mode_keyboard())


@owner_only
async def auto_mode_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable auto mode."""
    query = update.callback_query
    await query.answer()
    await _save_profile_field(update, "auto_mode_enabled", False, silent=True)
    await query.edit_message_text("❌ Авто-режим выключён.", reply_markup=auto_mode_keyboard())


@owner_only
async def settings_auto_delay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing auto mode delay."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.auto_mode_delay_minutes if profile else 5

    await query.edit_message_text(
        f"⏱ Текущая задержка авто-режима: {current} минут\n\n"
        "Введите задержку в минутах (число):\n"
        "Или /cancel для отмены:",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_AUTO_DELAY


@owner_only
async def save_auto_delay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save auto mode delay."""
    try:
        minutes = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите число. Например: 5")
        return ENTERING_AUTO_DELAY

    if minutes <= 0:
        await update.message.reply_text("❌ Задержка должна быть положительным числом.")
        return ENTERING_AUTO_DELAY

    if minutes > 1440:  # 24 hours
        await update.message.reply_text("❌ Задержка не может быть больше 24 часов (1440 минут).")
        return ENTERING_AUTO_DELAY

    await _save_profile_field(update, "auto_mode_delay_minutes", minutes)
    return ConversationHandler.END


# --- Helpers ---

async def _save_user_setting(
    update: Update,
    analysis_prompt: Optional[str] = None,
    response_prompt: Optional[str] = None,
    min_budget: Optional[int] = None,
    max_budget: Optional[int] = None,
    cooldown_seconds: Optional[int] = None
) -> None:
    """Helper to save user settings."""
    async with aiosqlite.connect(DB_PATH) as db:
        settings = await queries.get_user_settings(db, OWNER_CHAT_ID)

        if not settings:
            settings = UserSettings(
                id=None,
                user_id=OWNER_CHAT_ID,
                analysis_prompt=analysis_prompt,
                response_prompt=response_prompt,
                min_budget=min_budget,
                max_budget=max_budget,
                cooldown_seconds=cooldown_seconds or DEFAULT_COOLDOWN_SEC,
            )
        else:
            if analysis_prompt is not None:
                settings.analysis_prompt = analysis_prompt
            if response_prompt is not None:
                settings.response_prompt = response_prompt
            if min_budget is not None:
                settings.min_budget = min_budget
            if max_budget is not None:
                settings.max_budget = max_budget
            if cooldown_seconds is not None:
                settings.cooldown_seconds = cooldown_seconds

        await queries.save_user_settings(db, settings)

    field_name = "Настройки сохранены"
    await update.message.reply_text(f"✅ {field_name}!")


async def _save_profile_field(
    update: Update,
    field_name: str,
    value,
    silent: bool = False
) -> None:
    """Helper to save a profile field."""
    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

        if not profile:
            profile = FreelancerProfile(id=None, user_id=OWNER_CHAT_ID)

        setattr(profile, field_name, value)
        await queries.save_freelancer_profile(db, profile)

    if not silent:
        await update.message.reply_text(f"✅ {field_name} сохранён!")


@owner_only
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "❌ Операция отменена.",
            reply_markup=settings_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Операция отменена.",
            reply_markup=settings_keyboard()
        )
    return ConversationHandler.END


def get_settings_handler() -> ConversationHandler:
    """Get the settings conversation handler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(settings_analysis_prompt, pattern="^settings_analysis_prompt$"),
            CallbackQueryHandler(settings_response_prompt, pattern="^settings_response_prompt$"),
            CallbackQueryHandler(settings_budget, pattern="^settings_budget$"),
            CallbackQueryHandler(settings_cooldown, pattern="^settings_cooldown$"),
            CallbackQueryHandler(settings_whitelist, pattern="^settings_whitelist$"),
            CallbackQueryHandler(settings_blacklist, pattern="^settings_blacklist$"),
            CallbackQueryHandler(settings_min_rating, pattern="^settings_min_rating$"),
            CallbackQueryHandler(settings_max_proposals, pattern="^settings_max_proposals$"),
            CallbackQueryHandler(settings_auto_delay, pattern="^auto_mode_delay$"),
        ],
        states={
            ENTERING_ANALYSIS_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_analysis_prompt)
            ],
            ENTERING_RESPONSE_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_response_prompt)
            ],
            ENTERING_BUDGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_budget)
            ],
            ENTERING_COOLDOWN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_cooldown)
            ],
            ENTERING_WHITELIST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_whitelist)
            ],
            ENTERING_BLACKLIST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_blacklist)
            ],
            ENTERING_MIN_RATING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_min_rating)
            ],
            ENTERING_MAX_PROPOSALS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_max_proposals)
            ],
            ENTERING_AUTO_DELAY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_auto_delay)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern="^cancel$"),
            CommandHandler("cancel", cancel),
        ],
        per_user=True,
        per_chat=True,
        name="settings_conversation",
    )
