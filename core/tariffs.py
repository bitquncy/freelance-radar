"""Tariff plans, limits and feature gating — AGENTS.md §7.

Spec-conflict resolution (documented per §12.6): §2.4 says auto-send is
Business-only, while §3.5 and §6.4 both say Pro/Business. The two explicit
product sections win: auto-send is available on Pro and Business, always
opt-in and threshold-gated (§6.4).

The 7-day trial (§7) grants Pro-level limits (documented assumption).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

from core.models import SubscriptionTier, User, utcnow

TRIAL_DAYS = 7
ANNUAL_DISCOUNT = 0.20

PRICES_RUB: Dict[SubscriptionTier, int] = {
    SubscriptionTier.BASIC: 299,
    SubscriptionTier.PRO: 599,
    SubscriptionTier.BUSINESS: 999,
}


@dataclass(frozen=True)
class TariffLimits:
    """Feature limits for a tier. ``None`` means unlimited."""

    max_exchanges: Optional[int]
    max_tg_channels: Optional[int]
    analyses_per_month: Optional[int]
    max_active_clients: Optional[int]
    ai_generation: bool
    portfolio_adaptation: bool
    tone_variants: int
    reminders: bool
    auto_send: bool
    weekly_report: bool
    team_seats: int
    export_integrations: bool
    priority_scan: bool
    personal_scoring: bool


_BASIC = TariffLimits(
    max_exchanges=1,
    max_tg_channels=5,
    analyses_per_month=50,
    max_active_clients=15,
    ai_generation=False,
    portfolio_adaptation=False,
    tone_variants=1,
    reminders=False,
    auto_send=False,
    weekly_report=False,
    team_seats=1,
    export_integrations=False,
    priority_scan=False,
    personal_scoring=False,
)

_PRO = TariffLimits(
    max_exchanges=3,
    max_tg_channels=None,
    analyses_per_month=None,
    max_active_clients=None,
    ai_generation=True,
    portfolio_adaptation=True,
    tone_variants=1,
    reminders=True,
    auto_send=True,
    weekly_report=True,
    team_seats=1,
    export_integrations=False,
    priority_scan=False,
    personal_scoring=False,
)

_BUSINESS = TariffLimits(
    max_exchanges=None,
    max_tg_channels=None,
    analyses_per_month=None,
    max_active_clients=None,
    ai_generation=True,
    portfolio_adaptation=True,
    tone_variants=3,
    reminders=True,
    auto_send=True,
    weekly_report=True,
    team_seats=3,
    export_integrations=True,
    priority_scan=True,
    personal_scoring=True,
)

LIMITS: Dict[SubscriptionTier, TariffLimits] = {
    SubscriptionTier.BASIC: _BASIC,
    SubscriptionTier.PRO: _PRO,
    SubscriptionTier.BUSINESS: _BUSINESS,
    SubscriptionTier.TRIAL: _PRO,  # trial == Pro-level access for 7 days
}


def trial_expiry(now: Optional[datetime] = None) -> datetime:
    """Compute trial expiry timestamp from ``now``."""
    return (now or utcnow()) + timedelta(days=TRIAL_DAYS)


def effective_tier(
    user: User, now: Optional[datetime] = None
) -> Optional[SubscriptionTier]:
    """Return the user's active tier, or ``None`` if the subscription expired.

    Args:
        user: The user whose subscription to check.
        now: Injectable clock for tests.

    Returns:
        Active tier or ``None`` (expired / no subscription).
    """
    moment = now or utcnow()
    if user.subscription_expires_at is None:
        return user.subscription_tier
    if user.subscription_expires_at <= moment:
        return None
    return user.subscription_tier


def get_limits(tier: Optional[SubscriptionTier]) -> Optional[TariffLimits]:
    """Return limits for a tier (``None`` tier → no access)."""
    if tier is None:
        return None
    return LIMITS[tier]


def can_connect_exchange(tier: Optional[SubscriptionTier], current: int) -> bool:
    """Check whether one more non-Telegram exchange can be connected."""
    limits = get_limits(tier)
    if limits is None:
        return False
    return limits.max_exchanges is None or current < limits.max_exchanges


def can_connect_tg_channel(tier: Optional[SubscriptionTier], current: int) -> bool:
    """Check whether one more Telegram channel can be connected."""
    limits = get_limits(tier)
    if limits is None:
        return False
    return limits.max_tg_channels is None or current < limits.max_tg_channels


def can_analyze(tier: Optional[SubscriptionTier], used_this_month: int) -> bool:
    """Check the per-month project analysis quota (§7: Basic — 50/мес)."""
    limits = get_limits(tier)
    if limits is None:
        return False
    if limits.analyses_per_month is None:
        return True
    return used_this_month < limits.analyses_per_month


def can_use_ai_generation(tier: Optional[SubscriptionTier]) -> bool:
    """AI proposal generation is a Pro/Business feature (§7)."""
    limits = get_limits(tier)
    return limits is not None and limits.ai_generation


def can_add_active_client(tier: Optional[SubscriptionTier], current: int) -> bool:
    """Check the active-clients CRM limit (§7: Basic — 15)."""
    limits = get_limits(tier)
    if limits is None:
        return False
    return limits.max_active_clients is None or current < limits.max_active_clients


def can_use_reminders(tier: Optional[SubscriptionTier]) -> bool:
    """Reminders are available from Pro (§7)."""
    limits = get_limits(tier)
    return limits is not None and limits.reminders


def can_auto_send(user: User, tier: Optional[SubscriptionTier]) -> bool:
    """Auto-send: Pro/Business AND explicitly enabled by the user (§6.4)."""
    limits = get_limits(tier)
    return bool(limits is not None and limits.auto_send and user.auto_send_enabled)
