"""/radar onboarding: target rate, tax reserve, skills (§3.4 target_hourly_rate)."""
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    BaseHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.handlers.v2.common import get_or_create_user, pending, tier_label
from core.db import get_session_factory
from services.logger_config import get_logger

logger = get_logger(__name__)

RATE, TAX, SKILLS = range(3)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """The V2 dashboard menu."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("\U0001f4e1 Источники", callback_data="v2s:menu"),
                InlineKeyboardButton("\U0001f4bc Портфолио", callback_data="v2pf:menu"),
            ],
            [
                InlineKeyboardButton("\U0001f465 Клиенты", callback_data="v2c:list"),
                InlineKeyboardButton("⭐ Подписка", callback_data="v2sub:info"),
            ],
        ]
    )


async def radar_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: show the menu, or start onboarding for new users."""
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    factory = get_session_factory()
    async with factory() as session:
        user, created = await get_or_create_user(session, update.effective_user)
        await session.commit()
        onboarded = user.target_hourly_rate is not None
        label = tier_label(user)
    if onboarded:
        await update.message.reply_text(
            f"\U0001f4e1 <b>FreelanceRadar</b>\nТариф: {label}",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END
    greeting = (
        "\U0001f44b Добро пожаловать в FreelanceRadar! Включён пробный период на 7 дней.\n\n"
        if created
        else ""
    )
    await update.message.reply_text(
        f"{greeting}Какая у вас целевая ставка в час, в рублях? "
        "Например: 1500. От неё считается выгодность заказов."
    )
    return RATE


async def onboarding_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store target hourly rate."""
    if update.message is None or update.message.text is None:
        return RATE
    try:
        rate = int(update.message.text.strip().replace(" ", ""))
        if not 50 <= rate <= 1_000_000:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Нужно целое число в рублях, например 1500. Попробуйте ещё раз."
        )
        return RATE
    pending(context)["v2_onb_rate"] = rate
    await update.message.reply_text(
        "Какой процент откладываете на налоги? Например: 6 (НПД). "
        "Если не откладываете — отправьте 0."
    )
    return TAX


async def onboarding_tax(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store tax reserve rate."""
    if update.message is None or update.message.text is None:
        return TAX
    try:
        percent = float(update.message.text.strip().replace(",", ".").rstrip("%"))
        if not 0 <= percent <= 50:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Число от 0 до 50, например 6.")
        return TAX
    pending(context)["v2_onb_tax"] = percent / 100.0
    await update.message.reply_text(
        "Перечислите ваши ключевые навыки через запятую "
        "(например: python, telegram-боты, парсинг)."
    )
    return SKILLS


async def onboarding_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store skills and finish onboarding."""
    if update.message is None or update.message.text is None:
        return SKILLS
    if update.effective_user is None:
        return ConversationHandler.END
    skills: List[str] = [
        s.strip() for s in update.message.text.split(",") if s.strip()
    ][:30]
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        user.target_hourly_rate = int(pending(context).pop("v2_onb_rate", 0)) or None
        user.tax_rate = float(pending(context).pop("v2_onb_tax", 0.06))
        user.skills = skills
        await session.commit()
    logger.info("v2.onboarding_done", telegram_id=update.effective_user.id)
    await update.message.reply_text(
        "Готово! Теперь подключите источники — и радар начнёт присылать "
        "подходящие заказы со скорингом.",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def onboarding_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel onboarding."""
    if update.message is not None:
        await update.message.reply_text("Настройку можно продолжить позже: /radar")
    return ConversationHandler.END


def get_onboarding_handlers() -> List[BaseHandler]:
    """Build onboarding handlers."""
    conversation = ConversationHandler(
        entry_points=[CommandHandler("radar", radar_entry)],
        states={
            RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_rate)],
            TAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_tax)],
            SKILLS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_skills)
            ],
        },
        fallbacks=[CommandHandler("cancel", onboarding_cancel)],
        name="v2_onboarding",
    )
    return [conversation]
