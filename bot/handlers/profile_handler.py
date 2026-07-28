"""Freelancer profile handler for managing user profile."""
import aiosqlite
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters
)

from services.logger_config import get_logger
from bot.auth import owner_only
from bot.keyboards import profile_keyboard, cancel_keyboard
from db import queries
from db.models import FreelancerProfile
from config import DB_PATH, OWNER_CHAT_ID

logger = get_logger(__name__)

# Conversation states
(
    ENTERING_SKILLS, ENTERING_EXPERIENCE, ENTERING_CATEGORIES,
    ENTERING_HOURLY_RATE, ENTERING_STRONG_SIDES, ENTERING_BIO,
    ENTERING_PORTFOLIO
) = range(7)


@owner_only
async def profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show freelancer profile menu."""
    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    text = "👤 **Профиль фрилансера**\n\n"
    if profile:
        if profile.skills:
            skills_list = profile.skills_list
            text += f"📝 Навыки: {', '.join(skills_list)}\n"
        if profile.experience_years:
            text += f"📅 Опыт: {profile.experience_years} лет\n"
        if profile.preferred_categories:
            categories_list = profile.preferred_categories_list
            text += f"📂 Категории: {', '.join(categories_list)}\n"
        if profile.hourly_rate:
            text += f"💰 Ставка: {profile.hourly_rate} руб/час\n"
        if profile.strong_sides:
            text += f"🌟 Сильные стороны: {profile.strong_sides}\n"
        if profile.bio:
            text += f"📄 О себе: {profile.bio}\n"
        if profile.portfolio_url:
            text += f"🔗 Портфолио: {profile.portfolio_url}\n"
        text += f"\n🤖 Авто-режим: {'✅ Включен' if profile.auto_mode_enabled else '❌ Выключен'}"
        if profile.auto_mode_enabled:
            text += f" ({profile.auto_mode_delay_minutes} мин)"
    else:
        text += "Профиль не заполнен. Заполните профиль для лучшей персонализации анализа и откликов."

    await update.message.reply_text(text, reply_markup=profile_keyboard(), parse_mode="Markdown")


@owner_only
async def profile_skills_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing skills."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.skills_list if profile and profile.skills else "Не указаны"
    await query.edit_message_text(
        f"📝 Текущие навыки: {current}\n\n"
        "Введите навыки через запятую (например: Python, Django, PostgreSQL):\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_SKILLS


@owner_only
async def save_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save skills."""
    skills = update.message.text.strip()
    await _update_profile_field(update, "skills", skills, "Навыки сохранены")
    return ConversationHandler.END


@owner_only
async def profile_experience_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing experience."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.experience_years if profile and profile.experience_years else "Не указан"
    await query.edit_message_text(
        f"📅 Текущий опыт: {current} лет\n\n"
        "Введите опыт в годах (число):\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_EXPERIENCE


@owner_only
async def save_experience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save experience years."""
    try:
        years = int(update.message.text.strip())
        await _update_profile_field(update, "experience_years", years, f"Опыт сохранён: {years} лет")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Введите число. Например: 3")
        return ENTERING_EXPERIENCE


@owner_only
async def profile_categories_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing preferred categories."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.preferred_categories_list if profile and profile.preferred_categories else "Не указаны"
    await query.edit_message_text(
        f"📂 Текущие категории: {current}\n\n"
        "Введите предпочтительные категории через запятую:\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_CATEGORIES


@owner_only
async def save_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save preferred categories."""
    categories = update.message.text.strip()
    await _update_profile_field(update, "preferred_categories", categories, "Категории сохранены")
    return ConversationHandler.END


@owner_only
async def profile_hourly_rate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing hourly rate."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.hourly_rate if profile and profile.hourly_rate else "Не указана"
    await query.edit_message_text(
        f"💰 Текущая ставка: {current} руб/час\n\n"
        "Введите ставку в рублях за час (число):\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_HOURLY_RATE


@owner_only
async def save_hourly_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save hourly rate."""
    try:
        rate = int(update.message.text.strip())
        await _update_profile_field(update, "hourly_rate", rate, f"Ставка сохранена: {rate} руб/час")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Введите число. Например: 1500")
        return ENTERING_HOURLY_RATE


@owner_only
async def profile_strong_sides_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing strong sides."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.strong_sides if profile and profile.strong_sides else "Не указаны"
    await query.edit_message_text(
        f"🌟 Текущие сильные стороны: {current}\n\n"
        "Введите ваши сильные стороны (кратко, через запятую):\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_STRONG_SIDES


@owner_only
async def save_strong_sides(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save strong sides."""
    sides = update.message.text.strip()
    await _update_profile_field(update, "strong_sides", sides, "Сильные стороны сохранены")
    return ConversationHandler.END


@owner_only
async def profile_bio_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing bio."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.bio if profile and profile.bio else "Не заполнено"
    await query.edit_message_text(
        f"📄 Текущее описание: {current}\n\n"
        "Введите краткое описание о себе (для использования в откликах):\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_BIO


@owner_only
async def save_bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save bio."""
    bio = update.message.text.strip()
    await _update_profile_field(update, "bio", bio, "Описание сохранено")
    return ConversationHandler.END


@owner_only
async def profile_portfolio_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start editing portfolio URL."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

    current = profile.portfolio_url if profile and profile.portfolio_url else "Не указан"
    await query.edit_message_text(
        f"🔗 Текущее портфолио: {current}\n\n"
        "Введите ссылку на портфолио:\n"
        "Или /cancel для отмены.",
        reply_markup=cancel_keyboard()
    )
    return ENTERING_PORTFOLIO


@owner_only
async def save_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save portfolio URL."""
    url = update.message.text.strip()
    await _update_profile_field(update, "portfolio_url", url, "Портфолио сохранено")
    return ConversationHandler.END


async def _update_profile_field(
    update: Update,
    field_name: str,
    value,
    success_message: str
) -> None:
    """Helper to update a single profile field."""
    async with aiosqlite.connect(DB_PATH) as db:
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)

        if not profile:
            profile = FreelancerProfile(
                id=None,
                user_id=OWNER_CHAT_ID,
            )

        setattr(profile, field_name, value)
        await queries.save_freelancer_profile(db, profile)

    await update.message.reply_text(f"✅ {success_message}!")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "❌ Операция отменена.",
            reply_markup=profile_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Операция отменена.",
            reply_markup=profile_keyboard()
        )
    return ConversationHandler.END


def get_profile_handler() -> ConversationHandler:
    """Get the profile conversation handler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(profile_skills_start, pattern="^profile_skills$"),
            CallbackQueryHandler(profile_experience_start, pattern="^profile_experience$"),
            CallbackQueryHandler(profile_categories_start, pattern="^profile_categories$"),
            CallbackQueryHandler(profile_hourly_rate_start, pattern="^profile_hourly_rate$"),
            CallbackQueryHandler(profile_strong_sides_start, pattern="^profile_strong_sides$"),
            CallbackQueryHandler(profile_bio_start, pattern="^profile_bio$"),
            CallbackQueryHandler(profile_portfolio_start, pattern="^profile_portfolio$"),
        ],
        states={
            ENTERING_SKILLS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_skills)
            ],
            ENTERING_EXPERIENCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_experience)
            ],
            ENTERING_CATEGORIES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_categories)
            ],
            ENTERING_HOURLY_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_hourly_rate)
            ],
            ENTERING_STRONG_SIDES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_strong_sides)
            ],
            ENTERING_BIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_bio)
            ],
            ENTERING_PORTFOLIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_portfolio)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
        per_user=True,
        per_chat=True,
        name="profile_conversation",
    )
