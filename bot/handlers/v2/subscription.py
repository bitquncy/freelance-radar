"""Subscription info + manual tier granting (MVP monetization, §7, §14).

Payments per roadmap MVP: "оплата вручную/по инвойсу для первых пользователей
до интеграции платежей" — Telegram Payments/ЮKassa integration is Phase 2.
"""
from datetime import timedelta
from typing import List

from sqlalchemy import func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    BaseHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from bot.auth import owner_only
from bot.handlers.v2.common import TIER_TITLES, get_or_create_user, tier_label
from core import crm, tariffs
from core.db import get_session_factory
from core.models import (
    PaymentStatus,
    ProjectAnalysis,
    Subscription,
    SubscriptionTier,
    User,
    utcnow,
)

TARIFF_TABLE = (
    "<b>Тарифы</b>\n"
    "• Basic — 299 ₽/мес: 1 биржа + до 5 TG-каналов, 50 анализов/мес, "
    "отклик по шаблону, CRM до 15 клиентов\n"
    "• Pro — 599 ₽/мес: до 3 бирж + безлимит каналов, безлимит анализов, "
    "AI-отклики + адаптация портфолио, напоминания, недельный отчёт\n"
    "• Business — 999 ₽/мес: безлимит источников, варианты тона, команда до 3 мест, "
    "экспорт, приоритетное сканирование\n\n"
    "Оплата картой — кнопками ниже (Telegram Payments, не покидая мессенджер)."
)


def _tariff_keyboard() -> InlineKeyboardMarkup:
    """Buy buttons for the §7 tiers."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"💳 {TIER_TITLES[tier]} · {tariffs.PRICES_RUB[tier]} ₽/мес",
                    callback_data=f"v2sub:buy:{tier.value}",
                )
            ]
            for tier in (
                SubscriptionTier.BASIC,
                SubscriptionTier.PRO,
                SubscriptionTier.BUSINESS,
            )
        ]
    )


async def subscription_info(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/subscription — current tier, usage and the tariff table."""
    if update.effective_user is None:
        return
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        tier = tariffs.effective_tier(user)
        limits = tariffs.get_limits(tier)
        month_start = utcnow().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        used = (
            await session.execute(
                select(func.count(ProjectAnalysis.id)).where(
                    ProjectAnalysis.user_id == user.id,
                    ProjectAnalysis.computed_at >= month_start,
                )
            )
        ).scalar_one()
        active_clients = await crm.count_active_clients(session, user.id)
        await session.commit()

    quota = "—"
    clients_line = "—"
    if limits is not None:
        quota = (
            f"{used}/{limits.analyses_per_month}"
            if limits.analyses_per_month is not None
            else f"{used}/безлимит"
        )
        clients_line = (
            f"{active_clients}/{limits.max_active_clients}"
            if limits.max_active_clients is not None
            else f"{active_clients}/безлимит"
        )
    text = (
        f"⭐ <b>Подписка:</b> {tier_label(user)}\n"
        f"Анализов в этом месяце: {quota}\n"
        f"Активных клиентов CRM: {clients_line}\n\n"
        f"{TARIFF_TABLE}"
    )
    if update.message is not None:
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=_tariff_keyboard()
        )
    elif update.callback_query is not None:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML", reply_markup=_tariff_keyboard()
        )


@owner_only
async def grant_subscription(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/grant <telegram_id> <basic|pro|business> [days] — manual invoice flow."""
    if update.message is None:
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Формат: /grant <telegram_id> <basic|pro|business> [дней=30]"
        )
        return
    try:
        telegram_id = int(args[0])
        tier = SubscriptionTier(args[1].lower())
        days = int(args[2]) if len(args) > 2 else 30
        if tier is SubscriptionTier.TRIAL:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Формат: /grant <telegram_id> <basic|pro|business> [дней=30]"
        )
        return
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            await update.message.reply_text(
                "Пользователь не найден — он должен сначала запустить /radar."
            )
            return
        now = utcnow()
        user.subscription_tier = tier
        user.subscription_expires_at = now + timedelta(days=days)
        session.add(
            Subscription(
                user_id=user.id,
                tier=tier,
                amount=tariffs.PRICES_RUB[tier],
                provider="manual_invoice",
                status=PaymentStatus.PAID,
                period_start=now,
                period_end=now + timedelta(days=days),
            )
        )
        await session.commit()
    await update.message.reply_text(
        f"Выдано: {TIER_TITLES[tier]} на {days} дней для {telegram_id}."
    )


def get_subscription_handlers() -> List[BaseHandler]:
    """Build subscription handlers."""
    return [
        CommandHandler("subscription", subscription_info),
        CallbackQueryHandler(subscription_info, pattern=r"^v2sub:info$"),
        CommandHandler("grant", grant_subscription),
    ]
