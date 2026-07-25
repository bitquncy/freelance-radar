"""Shared helpers for V2 handlers."""
import html
from typing import Any, MutableMapping, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import User as TelegramUser
from telegram.ext import ContextTypes

from core import tariffs
from core.models import SubscriptionTier, User

TIER_TITLES = {
    SubscriptionTier.TRIAL: "Пробный период",
    SubscriptionTier.BASIC: "Basic",
    SubscriptionTier.PRO: "Pro",
    SubscriptionTier.BUSINESS: "Business",
}

NO_ACCESS_TEXT = (
    "Подписка не активна. Откройте /subscription, чтобы продлить доступ."
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


async def get_or_create_user(
    session: AsyncSession, tg_user: TelegramUser
) -> Tuple[User, bool]:
    """Fetch the V2 user row for a Telegram user, creating it on first touch.

    New users get the 7-day trial (§7: "пробный период 7 дней без карты").

    Returns:
        ``(user, created)`` tuple.
    """
    result = await session.execute(
        select(User).where(User.telegram_id == tg_user.id)
    )
    user = result.scalar_one_or_none()
    if user is not None:
        return user, False
    user = User(
        telegram_id=tg_user.id,
        username=tg_user.username,
        subscription_tier=SubscriptionTier.TRIAL,
        subscription_expires_at=tariffs.trial_expiry(),
    )
    session.add(user)
    await session.flush()
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
