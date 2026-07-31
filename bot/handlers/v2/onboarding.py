"""/radar onboarding: target rate, tax reserve, skills (§3.4 target_hourly_rate)."""
from typing import List

from telegram import Update
from telegram.ext import (
    BaseHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.handlers.v2.common import get_or_create_user, pending
from bot.handlers.v2.menu import main_menu_keyboard, show_menu
from core import tariffs
from core.db import get_session_factory
from emoji_config import E, P
from services.logger_config import get_logger

logger = get_logger(__name__)

RATE, TAX, SKILLS = range(3)


STEP_RATE = "Шаг 1 из 3"
STEP_TAX = "Шаг 2 из 3"
STEP_SKILLS = "Шаг 3 из 3"

RATE_PROMPT = (
    f"{E.SETTINGS} <b>{STEP_RATE} · Ставка</b>\n\n"
    "Какая у вас целевая ставка в час, в рублях?\n"
    "Например: <code>1500</code>\n\n"
    "<i>Нужна, чтобы считать выгодность заказа и отсекать дешёвые. "
    "Отменить — /cancel</i>"
)


async def radar_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: show the dashboard, or start onboarding for new users."""
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    factory = get_session_factory()
    async with factory() as session:
        user, created = await get_or_create_user(session, update.effective_user)
        await session.commit()
        onboarded = user.target_hourly_rate is not None
    if onboarded:
        await show_menu(update, context)
        return ConversationHandler.END
    greeting = (
        "\U0001f44b <b>Добро пожаловать в FreelanceRadar!</b>\n"
        f"{E.GIFT} Первые {tariffs.TRIAL_DAYS} дней — бесплатно и без карты, "
        f"дальше {tariffs.PRIMARY_PRICE_RUB} \u20bd/мес.\n"
        "Настройка займёт минуту — 3 вопроса.\n\n"
        if created
        else ""
    )
    await update.message.reply_text(
        f"{greeting}{RATE_PROMPT}", parse_mode="HTML"
    )
    return RATE


async def onboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """«🚀 Настроить профиль» from the dashboard starts the same flow."""
    query = update.callback_query
    if query is None or update.effective_chat is None:
        return ConversationHandler.END
    await query.answer()
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=RATE_PROMPT, parse_mode="HTML"
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
        # Без parse_mode — только plain-иконки (:class:`P`).
        await update.message.reply_text(
            f"{P.EXCLAMATION} Нужно целое число от 50 до 1 000 000 — например 1500.\n"
            "Попробуйте ещё раз или отмените: /cancel"
        )
        return RATE
    pending(context)["v2_onb_rate"] = rate
    await update.message.reply_text(
        f"{E.CHECK} Ставка: {rate} \u20bd/ч\n\n"
        f"<b>{STEP_TAX} · Налоги</b>\n\n"
        "Какой процент откладываете на налоги?\n"
        "Например: <code>6</code> (НПД) · не откладываете — отправьте <code>0</code>\n\n"
        "<i>Учтём в расчёте чистого дохода по заказу.</i>",
        parse_mode="HTML",
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
        await update.message.reply_text(
            f"{P.EXCLAMATION} Нужно число от 0 до 50 — например 6. Отменить — /cancel"
        )
        return TAX
    pending(context)["v2_onb_tax"] = percent / 100.0
    await update.message.reply_text(
        f"{E.CHECK} Налоги: {percent:g}%\n\n"
        f"<b>{STEP_SKILLS} · Навыки</b>\n\n"
        "Перечислите ключевые навыки через запятую:\n"
        "<code>python, telegram-боты, парсинг</code>\n\n"
        "<i>По ним радар отбирает заказы и считает совпадение.</i>",
        parse_mode="HTML",
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
    if not skills:
        await update.message.reply_text(
            f"{P.EXCLAMATION} Нужен хотя бы один навык — например: python, парсинг"
        )
        return SKILLS
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        user.target_hourly_rate = int(pending(context).pop("v2_onb_rate", 0)) or None
        user.tax_rate = float(pending(context).pop("v2_onb_tax", 0.06))
        user.skills = skills
        await session.commit()
    logger.info("v2.onboarding_done", telegram_id=update.effective_user.id)
    await update.message.reply_text(
        f"{E.PARTY} <b>Профиль готов!</b>\n\n"
        "Осталось два шага:\n"
        f"{E.RADAR} <b>Источники</b> — откуда брать заказы\n"
        f"{E.BRIEFCASE} <b>Портфолио</b> — факты для AI-откликов\n\n"
        "После этого радар начнёт присылать заказы со скорингом автоматически.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def onboarding_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel onboarding."""
    if update.message is not None:
        await update.message.reply_text(
            "Ок, отменил. Продолжить настройку можно когда угодно: /radar"
        )
    return ConversationHandler.END


def get_onboarding_handlers(persistent: bool = False) -> List[BaseHandler]:
    """Build onboarding handlers.

    Args:
        persistent: Persist conversation state across restarts (requires an
            application-level persistence backend).
    """
    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("radar", radar_entry),
            CallbackQueryHandler(onboard_button, pattern=r"^v2:onboard$"),
        ],
        states={
            RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_rate)],
            TAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_tax)],
            SKILLS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_skills)
            ],
        },
        fallbacks=[CommandHandler("cancel", onboarding_cancel)],
        name="v2_onboarding",
        persistent=persistent,
    )
    return [conversation]
