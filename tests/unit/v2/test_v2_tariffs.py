"""Tariff limits and gating tests — §7 table, trial, expiry."""
from datetime import timedelta

from core import tariffs
from core.models import SubscriptionTier, User, utcnow


def _user(tier: SubscriptionTier, expires_in_days: int = 10) -> User:
    return User(
        telegram_id=1,
        subscription_tier=tier,
        subscription_expires_at=utcnow() + timedelta(days=expires_in_days),
    )


def test_basic_limits_match_spec_table() -> None:
    """§7: Basic — 1 биржа, 5 каналов, 50 анализов, CRM 15, без AI/напоминаний."""
    limits = tariffs.get_limits(SubscriptionTier.BASIC)
    assert limits is not None
    assert limits.max_exchanges == 1
    assert limits.max_tg_channels == 5
    assert limits.analyses_per_month == 50
    assert limits.max_active_clients == 15
    assert limits.ai_generation is False
    assert limits.reminders is False
    assert limits.auto_send is False


def test_pro_limits_match_spec_table() -> None:
    """§7: Pro — до 3 бирж, безлимит каналов/анализов/CRM, AI, напоминания."""
    limits = tariffs.get_limits(SubscriptionTier.PRO)
    assert limits is not None
    assert limits.max_exchanges == 3
    assert limits.max_tg_channels is None
    assert limits.analyses_per_month is None
    assert limits.max_active_clients is None
    assert limits.ai_generation is True
    assert limits.reminders is True
    assert limits.weekly_report is True


def test_business_limits_match_spec_table() -> None:
    """§7: Business — безлимит, тона, команда 3, экспорт, приоритет."""
    limits = tariffs.get_limits(SubscriptionTier.BUSINESS)
    assert limits is not None
    assert limits.max_exchanges is None
    assert limits.tone_variants == 3
    assert limits.team_seats == 3
    assert limits.export_integrations is True
    assert limits.priority_scan is True
    assert limits.personal_scoring is True


def test_prices_match_spec() -> None:
    """§7: 299 / 599 / 999 ₽, годовая −20%, триал 7 дней."""
    assert tariffs.PRICES_RUB[SubscriptionTier.BASIC] == 299
    assert tariffs.PRICES_RUB[SubscriptionTier.PRO] == 599
    assert tariffs.PRICES_RUB[SubscriptionTier.BUSINESS] == 999
    assert tariffs.ANNUAL_DISCOUNT == 0.20
    assert tariffs.TRIAL_DAYS == 7


def test_trial_gets_pro_level_access() -> None:
    """Trial == Pro limits (documented assumption)."""
    assert tariffs.get_limits(SubscriptionTier.TRIAL) == tariffs.get_limits(
        SubscriptionTier.PRO
    )


def test_effective_tier_active_and_expired() -> None:
    """Expired subscription → no tier → no access."""
    active = _user(SubscriptionTier.PRO, expires_in_days=5)
    assert tariffs.effective_tier(active) is SubscriptionTier.PRO

    expired = _user(SubscriptionTier.PRO, expires_in_days=-1)
    assert tariffs.effective_tier(expired) is None
    assert tariffs.get_limits(None) is None
    assert tariffs.can_analyze(None, 0) is False
    assert tariffs.can_connect_exchange(None, 0) is False


def test_effective_tier_without_expiry_is_active() -> None:
    """No expiry set → tier counts as active (e.g. manually granted)."""
    user = User(telegram_id=2, subscription_tier=SubscriptionTier.BASIC)
    assert tariffs.effective_tier(user) is SubscriptionTier.BASIC


def test_analysis_quota_gate() -> None:
    """Basic: 50/month hard cap; Pro: unlimited."""
    assert tariffs.can_analyze(SubscriptionTier.BASIC, 49) is True
    assert tariffs.can_analyze(SubscriptionTier.BASIC, 50) is False
    assert tariffs.can_analyze(SubscriptionTier.PRO, 10_000) is True


def test_connection_gates() -> None:
    """Exchange and channel limits per tier."""
    assert tariffs.can_connect_exchange(SubscriptionTier.BASIC, 0) is True
    assert tariffs.can_connect_exchange(SubscriptionTier.BASIC, 1) is False
    assert tariffs.can_connect_exchange(SubscriptionTier.PRO, 2) is True
    assert tariffs.can_connect_exchange(SubscriptionTier.PRO, 3) is False
    assert tariffs.can_connect_tg_channel(SubscriptionTier.BASIC, 4) is True
    assert tariffs.can_connect_tg_channel(SubscriptionTier.BASIC, 5) is False
    assert tariffs.can_connect_tg_channel(SubscriptionTier.PRO, 500) is True


def test_crm_client_gate() -> None:
    """Basic: 15 active clients cap."""
    assert tariffs.can_add_active_client(SubscriptionTier.BASIC, 14) is True
    assert tariffs.can_add_active_client(SubscriptionTier.BASIC, 15) is False
    assert tariffs.can_add_active_client(SubscriptionTier.BUSINESS, 10_000) is True


def test_auto_send_requires_tier_and_opt_in() -> None:
    """§6.4: auto-send is Pro/Business AND explicit opt-in, never default."""
    pro_user = _user(SubscriptionTier.PRO)
    assert tariffs.can_auto_send(pro_user, SubscriptionTier.PRO) is False  # not opted
    pro_user.auto_send_enabled = True
    assert tariffs.can_auto_send(pro_user, SubscriptionTier.PRO) is True

    basic_user = _user(SubscriptionTier.BASIC)
    basic_user.auto_send_enabled = True
    assert tariffs.can_auto_send(basic_user, SubscriptionTier.BASIC) is False
