"""Telegram Payments flow (ЮKassa provider) — AGENTS.md §7, §14 Фаза 2.

«Оплата не покидая Telegram — ниже трение подписки» (§4.2). Flow:
buy button → ``send_invoice`` → ``PreCheckoutQuery`` (validated) →
``successful_payment`` → idempotent activation via :mod:`core.billing`.

Without ``PAYMENT_PROVIDER_TOKEN`` the buttons stay visible but answer with
a friendly "скоро" alert and the manual /grant flow remains the only path —
so the feature ships dark until the owner connects ЮKassa in BotFather.
"""

from typing import List

from telegram import LabeledPrice, Update
from telegram.ext import (
    BaseHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from bot.handlers.v2.common import TIER_TITLES, get_or_create_user
from core import billing
from core.db import get_session_factory
from emoji_config import E, P
from core.models import SubscriptionTier
from services.logger_config import get_logger

logger = get_logger(__name__)

#: Single-plan description shown inside the Telegram invoice.
PLAN_DESCRIPTION = (
    "Все биржи и Telegram-каналы, безлимит анализов, AI-отклики с адаптацией "
    "под портфолио, CRM с напоминаниями, недельный отчёт. Доступ на 30 дней, "
    "без автосписаний."
)

TIER_DESCRIPTIONS = {
    tier: PLAN_DESCRIPTION
    for tier in (
        SubscriptionTier.BASIC,
        SubscriptionTier.PRO,
        SubscriptionTier.BUSINESS,
    )
}


def _provider_token() -> str:
    from config import get_config

    return get_config().PAYMENT_PROVIDER_TOKEN


async def buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle «💳 Оплатить <tier>» — send a Telegram invoice."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    token = _provider_token()
    if not token:
        await query.answer(
            f"{P.CLOCK} Оплата картой ещё подключается. Напишите владельцу бота — "
            "доступ выдадут вручную в тот же день.",
            show_alert=True,
        )
        return
    try:
        tier = SubscriptionTier(query.data.split(":")[2])
        intent = billing.parse_payload(billing.build_payload(tier))
    except (ValueError, billing.PaymentError):
        await query.answer(f"{P.CROSS} Неизвестный тариф.", show_alert=True)
        return
    await query.answer()
    from config import get_config

    await context.bot.send_invoice(
        chat_id=update.effective_user.id,
        title=f"FreelanceRadar {TIER_TITLES[tier]} — {intent.days} дней",
        description=TIER_DESCRIPTIONS[tier],
        payload=billing.build_payload(tier),
        provider_token=token,
        currency=get_config().PAYMENT_CURRENCY,
        prices=[
            LabeledPrice(
                label=f"{TIER_TITLES[tier]} · {intent.days} дней",
                amount=intent.amount_kopecks,
            )
        ],
    )
    logger.info(
        "billing.invoice_sent",
        telegram_id=update.effective_user.id,
        tier=tier.value,
    )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer Telegram's final pre-charge confirmation (§ payments contract).

    Telegram gives 10 seconds to confirm; we re-validate the payload and the
    amount against the §7 price table before approving the charge.
    """
    pcq = update.pre_checkout_query
    if pcq is None:
        return
    try:
        from config import get_config

        intent = billing.parse_payload(pcq.invoice_payload)
        billing.validate_paid_amount(intent, pcq.total_amount)
        billing.validate_paid_currency(pcq.currency, get_config().PAYMENT_CURRENCY)
    except billing.PaymentError as exc:
        logger.warning("billing.precheckout_rejected", error=str(exc))
        await pcq.answer(
            ok=False,
            error_message=(
                f"{P.WARNING} Не удалось проверить заказ — попробуйте открыть оплату заново."
            ),
        )
        return
    await pcq.answer(ok=True)


async def on_successful_payment(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Activate the subscription after Telegram confirms the charge."""
    message = update.message
    if (
        message is None
        or message.successful_payment is None
        or update.effective_user is None
    ):
        return
    payment = message.successful_payment
    try:
        from config import get_config

        intent = billing.parse_payload(payment.invoice_payload)
        billing.validate_paid_amount(intent, payment.total_amount)
        billing.validate_paid_currency(payment.currency, get_config().PAYMENT_CURRENCY)
    except billing.PaymentError as exc:
        # Money was charged but the payload is foreign/borked — never
        # activate silently; log loudly for manual reconciliation.
        logger.error(
            "billing.successful_payment_invalid",
            error=str(exc),
            charge_id=payment.telegram_payment_charge_id,
            telegram_id=update.effective_user.id,
        )
        await message.reply_text(
            f"{P.WARNING} Платёж получен, но заказ не распознан — напишите владельцу, "
            "подписку активируют вручную."
        )
        return

    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        subscription, applied = await billing.apply_paid_subscription(
            session,
            user,
            intent,
            charge_id=payment.telegram_payment_charge_id,
        )
        await session.commit()
        expires = user.subscription_expires_at

    if not applied:
        await message.reply_text(
            f"{P.INFO} Этот платёж уже был учтён — доступ активен, повторно не списали."
        )
        return
    await message.reply_text(
        f"{E.CHECK} <b>Оплата прошла</b>\n\n"
        f"{TIER_TITLES[intent.tier]} активен"
        + (f" до <b>{expires:%d.%m.%Y}</b>" if expires else "")
        + ".\nРадар снова сканирует заказы — вернуться в меню: /menu",
        parse_mode="HTML",
    )


def get_payment_handlers() -> List[BaseHandler]:
    """Build payment handlers."""
    return [
        CallbackQueryHandler(
            buy_subscription, pattern=r"^v2sub:buy:(basic|pro|business)$"
        ),
        PreCheckoutQueryHandler(precheckout),
        MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment),
    ]
