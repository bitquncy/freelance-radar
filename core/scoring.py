"""Scoring engine: win probability + profitability — AGENTS.md §3.3–§3.4.

No LLM is involved in computing numbers (§6.1): the formula combines
normalized features through a logistic function. Weights are heuristic for
the cold start (§3.3); per-user retraining is Phase 3.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Sequence

from core.models import PortfolioItem, Project, ProjectAnalysis, User, utcnow

# --- Reference data (справочники, пополняются вручную на старте — §3.4) ---

PLATFORM_COMMISSION: Dict[str, float] = {
    "kwork": 0.20,
    "fl_ru": 0.10,
    "weblancer": 0.10,
    "tg_channel": 0.0,  # direct deals, no platform fee
    "upwork": 0.10,
}
DEFAULT_COMMISSION = 0.15

ESTIMATED_HOURS_BY_CATEGORY: Dict[str, float] = {
    "лендинг": 20.0,
    "сайт": 40.0,
    "бот": 25.0,
    "telegram-бот": 25.0,
    "парсер": 15.0,
    "скрипт": 8.0,
    "дизайн": 20.0,
    "логотип": 8.0,
    "верстка": 16.0,
    "интеграция": 20.0,
    "автоматизация": 20.0,
}
DEFAULT_ESTIMATED_HOURS = 10.0

DEFAULT_MEDIAN_PROPOSALS = 10.0
FRESHNESS_HALF_LIFE_MINUTES = 240.0
NEUTRAL_FEATURE = 0.5


class TrafficLight(str, Enum):
    """Profitability traffic light (§3.4)."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"

    @property
    def emoji(self) -> str:
        """Emoji used in bot cards."""
        return {"green": "\U0001f7e2", "yellow": "\U0001f7e1", "red": "\U0001f534"}[
            self.value
        ]


@dataclass(frozen=True)
class ScoringWeights:
    """Heuristic cold-start weights for the §3.3 formula."""

    client: float = 1.2
    skill: float = 1.6
    budget: float = 1.1
    competition: float = 0.9
    freshness: float = 1.0
    bias: float = -2.4


DEFAULT_WEIGHTS = ScoringWeights()


@dataclass(frozen=True)
class ScoringFeatures:
    """Normalized features in [0, 1]; ``None`` = unknown (neutral 0.5)."""

    client_score: Optional[float] = None
    skill_match: Optional[float] = None
    budget_fit: Optional[float] = None
    competition_index: Optional[float] = None
    freshness: Optional[float] = None


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def normalize_client_score(
    rating: Optional[float],
    orders_count: Optional[int],
    payment_verified: Optional[bool] = None,
) -> Optional[float]:
    """Normalize client quality signals to [0, 1] (§3.3 client_score).

    Args:
        rating: Client rating 0..5.
        orders_count: Number of completed orders.
        payment_verified: Whether payment method is verified.

    Returns:
        Normalized score or ``None`` when no signal is available.
    """
    if rating is None and orders_count is None and payment_verified is None:
        return None
    score = 0.0
    if rating is not None:
        score += _clamp(rating / 5.0) * 0.6
    if orders_count is not None:
        score += _clamp(orders_count / 20.0) * 0.3
    if payment_verified:
        score += 0.1
    return _clamp(score)


def _norm_tokens(values: Sequence[str]) -> set:
    return {v.strip().casefold() for v in values if v and v.strip()}


def normalize_skill_match(
    required_skills: Sequence[str],
    user_skills: Sequence[str],
    portfolio_tags: Sequence[str],
) -> Optional[float]:
    """Share of required skills covered by the user's skills/portfolio tags.

    MVP heuristic (roadmap §14: "эвристический скоринг без ML"); the
    embedding-based version is Phase 3.
    """
    required = _norm_tokens(required_skills)
    if not required:
        return None
    known = _norm_tokens(user_skills) | _norm_tokens(portfolio_tags)
    if not known:
        return 0.0
    matched = {r for r in required if r in known or any(r in k or k in r for k in known)}
    return _clamp(len(matched) / len(required))


def normalize_budget_fit(
    budget_estimate: Optional[float],
    target_hourly_rate: Optional[float],
    estimated_hours: Optional[float],
) -> Optional[float]:
    """Declared budget vs the user's expected income for the job (§3.3)."""
    if not budget_estimate or not target_hourly_rate or not estimated_hours:
        return None
    expected = target_hourly_rate * estimated_hours
    if expected <= 0:
        return None
    ratio = budget_estimate / expected
    return _clamp(ratio / 1.5)


def normalize_competition_index(
    proposals_count: Optional[int],
    category_median: Optional[float] = None,
) -> Optional[float]:
    """Competition pressure in [0, 1]: 0 = no competition (§3.3)."""
    if proposals_count is None:
        return None
    median = category_median if category_median and category_median > 0 else (
        DEFAULT_MEDIAN_PROPOSALS
    )
    return _clamp(proposals_count / (proposals_count + median))


def normalize_freshness(
    posted_at: Optional[datetime], now: Optional[datetime] = None
) -> Optional[float]:
    """Exponential decay of listing age (§2.4: скорость решает)."""
    if posted_at is None:
        return None
    moment = now or utcnow()
    age_minutes = max(0.0, (moment - posted_at).total_seconds() / 60.0)
    return math.exp(-age_minutes / FRESHNESS_HALF_LIFE_MINUTES)


def win_probability(
    features: ScoringFeatures, weights: ScoringWeights = DEFAULT_WEIGHTS
) -> float:
    """Compute win probability 0–100 via the §3.3 logistic formula.

    Unknown features contribute a neutral 0.5.
    """

    def f(value: Optional[float]) -> float:
        return NEUTRAL_FEATURE if value is None else _clamp(value)

    s = (
        weights.bias
        + weights.client * f(features.client_score)
        + weights.skill * f(features.skill_match)
        + weights.budget * f(features.budget_fit)
        - weights.competition * f(features.competition_index)
        + weights.freshness * f(features.freshness)
    )
    return round(100.0 / (1.0 + math.exp(-s)), 1)


@dataclass(frozen=True)
class ProfitabilityResult:
    """Profitability figures per §3.4."""

    net_payout: float
    effective_hourly_rate: float
    profitability_index: float
    estimated_hours: float
    traffic_light: TrafficLight


def traffic_light(profitability_index: float) -> TrafficLight:
    """Map profitability index to the §3.4 traffic light."""
    if profitability_index > 1.2:
        return TrafficLight.GREEN
    if profitability_index >= 0.8:
        return TrafficLight.YELLOW
    return TrafficLight.RED


def estimate_hours(
    category: Optional[str],
    extracted_deadline_days: Optional[int] = None,
) -> float:
    """Estimate labor hours from the category reference table (§3.4)."""
    if category:
        key = category.strip().casefold()
        for name, hours in ESTIMATED_HOURS_BY_CATEGORY.items():
            if name in key or key in name:
                return hours
    if extracted_deadline_days is not None and extracted_deadline_days > 0:
        # Rough heuristic: half a workday per deadline day, bounded.
        return _clamp(extracted_deadline_days * 4.0, 2.0, 80.0)
    return DEFAULT_ESTIMATED_HOURS


def compute_profitability(
    budget_estimate: float,
    platform: str,
    tax_rate: float,
    estimated_hours_value: float,
    target_hourly_rate: float,
) -> ProfitabilityResult:
    """Compute net payout, effective hourly rate and index (§3.4 formulas)."""
    commission = PLATFORM_COMMISSION.get(platform, DEFAULT_COMMISSION)
    gross = budget_estimate * (1.0 - commission)
    tax_reserve = gross * max(0.0, tax_rate)
    net_payout = gross - tax_reserve
    hours = max(0.25, estimated_hours_value)
    effective_hourly_rate = net_payout / hours
    index = (
        effective_hourly_rate / target_hourly_rate if target_hourly_rate > 0 else 0.0
    )
    return ProfitabilityResult(
        net_payout=round(net_payout, 2),
        effective_hourly_rate=round(effective_hourly_rate, 2),
        profitability_index=round(index, 3),
        estimated_hours=hours,
        traffic_light=traffic_light(index),
    )


@dataclass
class ScoreResult:
    """Combined scoring outcome for a (project, user) pair."""

    win_probability: Optional[float] = None
    profitability: Optional[ProfitabilityResult] = None
    needs_manual_review: bool = False
    features: ScoringFeatures = field(default_factory=ScoringFeatures)


def budget_estimate_for(
    project: Project, analysis: Optional[ProjectAnalysis] = None
) -> Optional[float]:
    """Pick the best available budget estimate for a project."""
    if analysis is not None and analysis.extracted_budget:
        return float(analysis.extracted_budget)
    lo, hi = project.budget_min, project.budget_max
    if lo and hi:
        return (lo + hi) / 2.0
    if hi:
        return float(hi)
    if lo:
        return float(lo)
    return None


def score_project(
    project: Project,
    user: User,
    portfolio_items: Sequence[PortfolioItem],
    analysis: Optional[ProjectAnalysis] = None,
    category_median_proposals: Optional[float] = None,
    now: Optional[datetime] = None,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> ScoreResult:
    """Score a project for a user (§3.3 + §3.4).

    Per §6.4, when no budget can be established the project is flagged
    ``needs_manual_review`` and excluded from auto-scoring.
    """
    budget = budget_estimate_for(project, analysis)
    if budget is None:
        return ScoreResult(needs_manual_review=True)

    required = list(analysis.extracted_skills) if analysis is not None else []
    tags: List[str] = []
    for item in portfolio_items:
        tags.extend(item.tags or [])
    hours = (
        analysis.estimated_hours
        if analysis is not None and analysis.estimated_hours
        else estimate_hours(
            project.category,
            analysis.extracted_deadline_days if analysis is not None else None,
        )
    )
    features = ScoringFeatures(
        client_score=normalize_client_score(
            project.client_rating, project.client_orders
        ),
        skill_match=normalize_skill_match(required, user.skills or [], tags),
        budget_fit=normalize_budget_fit(budget, user.target_hourly_rate, hours),
        competition_index=normalize_competition_index(
            project.proposals_count, category_median_proposals
        ),
        freshness=normalize_freshness(project.posted_at, now=now),
    )
    probability = win_probability(features, weights)
    profitability = (
        compute_profitability(
            budget_estimate=budget,
            platform=project.source.value,
            tax_rate=user.tax_rate,
            estimated_hours_value=hours,
            target_hourly_rate=float(user.target_hourly_rate or 0),
        )
        if user.target_hourly_rate
        else None
    )
    return ScoreResult(
        win_probability=probability,
        profitability=profitability,
        features=features,
    )
