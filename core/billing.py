"""Subscription billing: Telegram Payments activation — AGENTS.md §7, §14 Фаза 2.

The invoice payload format is ``v2sub:<tier>:<days>`` and the paid amount is
always re-validated against the §7 price table server-side — the client
(Telegram) is never trusted for pricing. Activation is idempotent on the
Telegram ``payment_charge_id`` (unique column + savepoint recovery), so a
re-delivered ``successful_payment`` update can never double-extend.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core import tariffs
from core.models import (
    PaymentStatus,
    Subscription,
    SubscriptionTier,
    User,
    utcnow,
)
from services.logger_config import get_logger

logger = get_logger(__name__)

PAYLOAD_PREFIX = "v2sub"
SUBSCRIPTION_DAYS = 30

#: The single plan sold in the bot («Радар PRO», 300 ₽/мес).
PRIMARY_TIER = tariffs.PRIMARY_TIER

#: Tiers purchasable via Telegram Payments (§7). TRIAL is never sold.
PURCHASABLE_TIERS = (
    SubscriptionTier.BASIC,
    SubscriptionTier.PRO,
    SubscriptionTier.BUSINESS,
)


class PaymentError(Exception):
    """Raised when a payment payload/amount fails validation."""


@dataclass(frozen=True)
class PaymentIntent:
    """A validated purchase intent parsed from the invoice payload."""

    tier: SubscriptionTier
    days: int
    amount_rub: int

    @property
    def amount_kopecks(self) -> int:
        """Telegram invoices use the currency's minor units."""
        return self.amount_rub * 100


def build_payload(
    tier: SubscriptionTier = PRIMARY_TIER, days: int = SUBSCRIPTION_DAYS
) -> str:
    """Serialize a purchase intent into the invoice payload."""
    return f"{PAYLOAD_PREFIX}:{tier.value}:{days}"


def parse_payload(payload: str) -> PaymentIntent:
    """Parse and validate an invoice payload (server-side price lookup).

    Raises:
        PaymentError: On unknown format, non-purchasable tier or bad days.
    """
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != PAYLOAD_PREFIX:
        raise PaymentError(f"unknown payload format: {payload!r}")
    try:
        tier = SubscriptionTier(parts[1])
        days = int(parts[2])
    except ValueError as exc:
        raise PaymentError(f"bad payload values: {payload!r}") from exc
    if tier not in PURCHASABLE_TIERS:
        raise PaymentError(f"tier is not purchasable: {tier.value}")
    if days != SUBSCRIPTION_DAYS:
        raise PaymentError(f"unsupported period: {days} days")
    return PaymentIntent(
        tier=tier, days=days, amount_rub=tariffs.PRICES_RUB[tier]
    )


def validate_paid_amount(intent: PaymentIntent, total_amount: int) -> None:
    """Ensure the user paid exactly the §7 price (in kopecks).

    Raises:
        PaymentError: On any mismatch — activation must not proceed.
    """
    if total_amount != intent.amount_kopecks:
        raise PaymentError(
            f"amount mismatch: paid {total_amount}, "
            f"expected {intent.amount_kopecks}"
        )


async def apply_paid_subscription(
    session: AsyncSession,
    user: User,
    intent: PaymentIntent,
    charge_id: str,
    provider: str = "telegram_payments",
) -> Tuple[Optional[Subscription], bool]:
    """Activate a paid subscription idempotently.

    Same-tier purchases EXTEND from the current expiry (never losing paid
    time); a different tier switches immediately for the full period.

    Returns:
        ``(subscription, applied)`` — ``applied=False`` means this charge id
        was already processed (duplicate update) and nothing changed.
    """
    now = utcnow()
    # Serialize entitlement mutation. The subscription insert and this locked
    # user-row update remain in the caller's single transaction.
    locked_user = (
        await session.execute(
            select(User).where(User.id == user.id).with_for_update()
        )
    ).scalar_one()
    base = now
    if (
        locked_user.subscription_tier is intent.tier
        and locked_user.subscription_expires_at is not None
        and locked_user.subscription_expires_at > now
    ):
        base = locked_user.subscription_expires_at
    period_end = base + timedelta(days=intent.days)

    subscription = Subscription(
        user_id=user.id,
        tier=intent.tier,
        amount=intent.amount_rub,
        provider=provider,
        status=PaymentStatus.PAID,
        payment_charge_id=charge_id,
        period_start=now,
        period_end=period_end,
    )
    try:
        async with session.begin_nested():
            session.add(subscription)
            await session.flush()
    except IntegrityError:
        # Idempotency: this exact Telegram charge was already applied.
        existing = (
            await session.execute(
                select(Subscription).where(
                    Subscription.payment_charge_id == charge_id
                )
            )
        ).scalar_one_or_none()
        logger.info(
            "billing.duplicate_charge_ignored",
            charge_id=charge_id,
            user_id=user.id,
        )
        return existing, False

    locked_user.subscription_tier = intent.tier
    locked_user.subscription_expires_at = period_end
    # Keep a separately supplied instance coherent for callers/tests.
    user.subscription_tier = intent.tier
    user.subscription_expires_at = period_end
    # New paid period → the expiry nudge is eligible again (one per period).
    locked_user.expiry_notified_at = None
    user.expiry_notified_at = None
    await session.flush()
    logger.info(
        "billing.subscription_activated",
        user_id=user.id,
        tier=intent.tier.value,
        period_end=period_end.isoformat(),
        amount_rub=intent.amount_rub,
    )
    return subscription, True
