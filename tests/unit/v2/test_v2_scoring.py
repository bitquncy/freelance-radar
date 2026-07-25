"""Scoring engine tests — §3.3 formula, §3.4 profitability, §6.4 manual review."""
from datetime import timedelta

import pytest

from core.models import User, SubscriptionTier, utcnow
from core.scoring import (
    DEFAULT_WEIGHTS,
    ScoringFeatures,
    TrafficLight,
    budget_estimate_for,
    compute_profitability,
    estimate_hours,
    normalize_budget_fit,
    normalize_client_score,
    normalize_competition_index,
    normalize_freshness,
    normalize_skill_match,
    score_project,
    traffic_light,
    win_probability,
)
from tests.unit.v2.conftest import make_project


class TestNormalization:
    def test_client_score_components(self) -> None:
        """Rating, orders and verification each add signal."""
        assert normalize_client_score(None, None, None) is None
        assert normalize_client_score(5.0, 20, True) == pytest.approx(1.0)
        assert normalize_client_score(0.0, 0, False) == pytest.approx(0.0)
        mid = normalize_client_score(2.5, 10, None)
        assert mid == pytest.approx(0.45)

    def test_skill_match_overlap(self) -> None:
        """Match share of required skills covered by user skills/tags."""
        assert normalize_skill_match([], ["python"], []) is None
        assert normalize_skill_match(["python"], [], []) == 0.0
        full = normalize_skill_match(
            ["python", "парсинг"], ["Python"], ["Парсинг"]
        )
        assert full == pytest.approx(1.0)
        half = normalize_skill_match(["python", "go"], ["python"], [])
        assert half == pytest.approx(0.5)

    def test_skill_match_substring_tolerance(self) -> None:
        """«telegram-боты» in profile covers required «боты»."""
        value = normalize_skill_match(["боты"], ["telegram-боты"], [])
        assert value == pytest.approx(1.0)

    def test_budget_fit(self) -> None:
        """Budget vs target income, capped at 1.5×."""
        assert normalize_budget_fit(None, 1500, 10) is None
        assert normalize_budget_fit(15000, None, 10) is None
        exact = normalize_budget_fit(15000, 1500.0, 10.0)
        assert exact == pytest.approx(1 / 1.5)
        rich = normalize_budget_fit(150000, 1500.0, 10.0)
        assert rich == pytest.approx(1.0)

    def test_competition_index(self) -> None:
        """0 proposals → 0; grows toward 1 with competition."""
        assert normalize_competition_index(None) is None
        assert normalize_competition_index(0) == pytest.approx(0.0)
        assert normalize_competition_index(10) == pytest.approx(0.5)
        crowded = normalize_competition_index(90)
        assert crowded == pytest.approx(0.9)

    def test_freshness_decay(self) -> None:
        """Fresh listing ≈ 1, stale listing → 0 (§2.4: speed matters)."""
        now = utcnow()
        fresh = normalize_freshness(now, now=now)
        assert fresh == pytest.approx(1.0)
        old = normalize_freshness(now - timedelta(hours=24), now=now)
        assert old is not None and old < 0.01
        assert normalize_freshness(None) is None


class TestWinProbability:
    def test_bounds_and_neutral(self) -> None:
        """Result is a 0–100 percentage; unknowns are neutral."""
        p_neutral = win_probability(ScoringFeatures())
        assert 0 <= p_neutral <= 100

        p_best = win_probability(
            ScoringFeatures(
                client_score=1.0,
                skill_match=1.0,
                budget_fit=1.0,
                competition_index=0.0,
                freshness=1.0,
            )
        )
        p_worst = win_probability(
            ScoringFeatures(
                client_score=0.0,
                skill_match=0.0,
                budget_fit=0.0,
                competition_index=1.0,
                freshness=0.0,
            )
        )
        assert p_worst < p_neutral < p_best
        assert p_best > 85
        assert p_worst < 10

    def test_monotonic_in_skill_match(self) -> None:
        """Better skill match never lowers the probability."""
        base = ScoringFeatures(skill_match=0.2)
        better = ScoringFeatures(skill_match=0.9)
        assert win_probability(better) > win_probability(base)

    def test_competition_lowers_probability(self) -> None:
        """More competition → lower probability (negative weight, §3.3)."""
        calm = ScoringFeatures(competition_index=0.1)
        crowded = ScoringFeatures(competition_index=0.9)
        assert win_probability(crowded) < win_probability(calm)

    def test_weights_are_cold_start_defaults(self) -> None:
        """Cold-start weights exist for all five features + bias (§3.3)."""
        assert DEFAULT_WEIGHTS.client > 0
        assert DEFAULT_WEIGHTS.skill > 0
        assert DEFAULT_WEIGHTS.budget > 0
        assert DEFAULT_WEIGHTS.competition > 0
        assert DEFAULT_WEIGHTS.freshness > 0


class TestProfitability:
    def test_formula_exact(self) -> None:
        """§3.4: net = budget×(1−commission)−tax; EHR = net/hours."""
        result = compute_profitability(
            budget_estimate=30000,
            platform="kwork",  # 20% commission
            tax_rate=0.06,
            estimated_hours_value=10,
            target_hourly_rate=1500,
        )
        # 30000 * 0.8 = 24000; tax 6% → 22560; /10h → 2256 ₽/ч; index 1.504
        assert result.net_payout == pytest.approx(22560.0)
        assert result.effective_hourly_rate == pytest.approx(2256.0)
        assert result.profitability_index == pytest.approx(1.504)
        assert result.traffic_light is TrafficLight.GREEN

    def test_traffic_light_thresholds(self) -> None:
        """§3.4: 🟢 >1.2 · 🟡 0.8–1.2 · 🔴 <0.8."""
        assert traffic_light(1.21) is TrafficLight.GREEN
        assert traffic_light(1.2) is TrafficLight.YELLOW
        assert traffic_light(0.8) is TrafficLight.YELLOW
        assert traffic_light(0.79) is TrafficLight.RED
        assert TrafficLight.GREEN.emoji == "\U0001f7e2"

    def test_tg_channel_has_no_commission(self) -> None:
        """Direct deals from channels keep the full budget."""
        result = compute_profitability(
            budget_estimate=10000,
            platform="tg_channel",
            tax_rate=0.0,
            estimated_hours_value=10,
            target_hourly_rate=1000,
        )
        assert result.net_payout == pytest.approx(10000.0)

    def test_estimate_hours_from_reference(self) -> None:
        """Category reference table with fallbacks (§3.4)."""
        assert estimate_hours("Telegram-бот") == 25.0
        assert estimate_hours("Лендинг под ключ") == 20.0
        assert estimate_hours(None, extracted_deadline_days=5) == 20.0
        assert estimate_hours(None) == 10.0


class TestScoreProject:
    def _user(self) -> User:
        return User(
            telegram_id=9,
            target_hourly_rate=1500,
            tax_rate=0.06,
            skills=["python", "telegram-боты"],
            subscription_tier=SubscriptionTier.PRO,
        )

    def test_full_scoring(self) -> None:
        """A complete project yields probability + profitability."""
        project = make_project()
        result = score_project(project, self._user(), [])
        assert result.needs_manual_review is False
        assert result.win_probability is not None
        assert 0 <= result.win_probability <= 100
        assert result.profitability is not None
        assert result.profitability.traffic_light in TrafficLight

    def test_no_budget_flags_manual_review(self) -> None:
        """§6.4: no budget → flagged, excluded from auto-scoring."""
        project = make_project(budget_min=None, budget_max=None)
        project.budget_raw = None
        result = score_project(project, self._user(), [])
        assert result.needs_manual_review is True
        assert result.win_probability is None
        assert result.profitability is None

    def test_budget_estimate_prefers_analysis(self) -> None:
        """Extracted budget wins over parser min/max midpoint."""
        project = make_project(budget_min=10000, budget_max=20000)
        assert budget_estimate_for(project) == pytest.approx(15000.0)

    def test_user_without_rate_gets_no_profitability(self) -> None:
        """No target rate → probability only (onboarding not finished)."""
        user = self._user()
        user.target_hourly_rate = None
        result = score_project(make_project(), user, [])
        assert result.win_probability is not None
        assert result.profitability is None
