"""Shared helpers for V2 handlers."""
import html
from typing import Any, MutableMapping, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import User as TelegramUser
from telegram.ext import ContextTypes

from core import tariffs
from core.models import SubscriptionTier, User
from emoji_config import E, P, btn_neutral, btn_primary

TIER_TITLES = {
    SubscriptionTier.TRIAL: "Пробный период",
    SubscriptionTier.BASIC: "Радар PRO",
    SubscriptionTier.PRO: "Радар PRO",
    SubscriptionTier.BUSINESS: "Радар PRO",
}

#: Shown in callback alerts (Telegram caps these at ~200 chars).
#: Plain Unicode only — ``show_alert`` не парсит HTML, тег <tg-emoji>
#: протёк бы пользователю как сырой текст.
NO_ACCESS_TEXT = (
    f"{P.LOCK} Доступ приостановлен. Подключите Радар PRO за "
    f"{tariffs.PRIMARY_PRICE_RUB} ₽/мес — команда /subscription. Данные и CRM сохранены."
)


def paywall_text() -> str:
    """Full paywall message for chat replies (HTML — premium-эмодзи ок)."""
    return (
        f"{E.LOCK} <b>Доступ приостановлен</b>\n\n"
        "Сканирование бирж, анализ заказов и AI-отклики выключены, но "
        "портфолио, CRM и история откликов целы.\n\n"
        f"Вернуть всё — {tariffs.PRIMARY_PRICE_RUB} ₽/мес, отмена в любой момент."
    )


def paywall_keyboard() -> InlineKeyboardMarkup:
    """Single-action paywall keyboard: pay now, or read what's included."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    btn_primary(
                        f"Подключить за {tariffs.PRIMARY_PRICE_RUB} ₽/мес", P.CARD
                    ),
                    callback_data=f"v2sub:buy:{tariffs.PRIMARY_TIER.value}",
                )
            ],
            [
                InlineKeyboardButton(
                    btn_neutral("Что входит", P.INFO), callback_data="v2sub:info"
                )
            ],
        ]
    )


async def deny_no_access(update: object) -> None:
    """Answer a blocked interaction with the paywall (callback or message).

    Callback alerts are short by protocol, so the alert carries the short
    text and the chat gets the full card with a pay button.
    """
    query = getattr(update, "callback_query", None)
    message = getattr(update, "message", None)
    if query is not None:
        await query.answer(NO_ACCESS_TEXT, show_alert=True)
        chat = getattr(query, "message", None)
        if chat is not None:
            await chat.reply_text(
                paywall_text(), parse_mode="HTML", reply_markup=paywall_keyboard()
            )
        return
    if message is not None:
        await message.reply_text(
            paywall_text(), parse_mode="HTML", reply_markup=paywall_keyboard()
        )


def esc(value: object) -> str:
    """HTML-escape a value for Telegram HTML parse mode."""
    return html.escape(str(value if value is not None else ""))


def pending(context: ContextTypes.DEFAULT_TYPE) -> MutableMapping[str, Any]:
    """Per-user state dict (PTB provides it for user-originated updates)."""
    data = context.user_data
    if data is None:  # pragma: no cover - never happens for our update types
        raise RuntimeError("user_data is unavailable for this update")
    return data


async def _select_user(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Load a user row by Telegram id (separated for race-recovery tests)."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_user(
    session: AsyncSession, tg_user: TelegramUser
) -> Tuple[User, bool]:
    """Fetch the V2 user row for a Telegram user, creating it on first touch.

    New users get the 7-day trial (§7: "пробный период 7 дней без карты").
    Concurrency-safe: two simultaneous first-touch updates (e.g. /radar and a
    button tap) race on the unique ``telegram_id`` — the loser recovers by
    re-selecting the winner's row instead of crashing the handler.

    Returns:
        ``(user, created)`` tuple.
    """
    user = await _select_user(session, tg_user.id)
    if user is not None:
        return user, False
    try:
        async with session.begin_nested():
            user = User(
                telegram_id=tg_user.id,
                username=tg_user.username,
                subscription_tier=SubscriptionTier.TRIAL,
                subscription_expires_at=tariffs.trial_expiry(),
            )
            session.add(user)
            await session.flush()
    except IntegrityError:
        existing = await _select_user(session, tg_user.id)
        if existing is None:  # pragma: no cover - constraint guarantees it
            raise
        return existing, False
    return user, True


def tier_label(user: User) -> str:
    """Human-readable tier label with expiry."""
    tier: Optional[SubscriptionTier] = tariffs.effective_tier(user)
    if tier is None:
        return "нет активной подписки"
    label = TIER_TITLES[tier]
    if user.subscription_expires_at is not None:
        label += f" (до {user.subscription_expires_at:%d.%m.%Y})"
    return label
