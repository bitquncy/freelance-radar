"""Two-level filter system for job vacancies."""
import re
from typing import Optional, List, Tuple

from services.logger_config import get_logger
from db.models import JobVacancy, FreelancerProfile
from services.blacklist import BlacklistService
from constants import (
    FilterReason,
    DEFAULT_MIN_SCORE,
    DEFAULT_MIN_MATCH,
)
from config import DB_PATH

logger = get_logger(__name__)


class VacancyFilter:
    """Two-level filter system for vacancies."""

    def __init__(self, profile: Optional[FreelancerProfile] = None):
        self.profile = profile
        self.blacklist_service = BlacklistService(DB_PATH)

    async def apply_pre_filters(self, vacancy: JobVacancy) -> Tuple[bool, Optional[str]]:
        """
        Level 1: Pre-filters applied BEFORE saving to DB and AI analysis.
        Returns (should_keep, reason_if_filtered).
        """
        # Blacklist check (vacancy + customer)
        customer_id = None
        if vacancy.url:
            # Try to extract customer username from URL or other fields
            # For now, we use customer_orders as a proxy identifier
            customer_id = str(vacancy.customer_orders) if vacancy.customer_orders else None

        is_blocked = await self.blacklist_service.check_vacancy(
            vacancy.kwork_id, customer_id
        )
        if is_blocked:
            return False, FilterReason.BLACKLISTED

        # Budget filter
        if self.profile and self.profile.min_budget is not None:
            if vacancy.budget_max and vacancy.budget_max < self.profile.min_budget:
                return False, f"{FilterReason.BUDGET_TOO_LOW} ({vacancy.budget_max} < {self.profile.min_budget})"

        if self.profile and self.profile.max_budget is not None:
            if vacancy.budget_min and vacancy.budget_min > self.profile.max_budget:
                return False, f"{FilterReason.BUDGET_TOO_HIGH} ({vacancy.budget_min} > {self.profile.max_budget})"

        # Blacklist words
        blacklist = self._get_blacklist()
        if blacklist:
            text = f"{vacancy.title} {vacancy.description}".lower()
            for word in blacklist:
                if word.lower() in text:
                    return False, f"{FilterReason.BLACKLIST_WORD}: {word}"

        # Whitelist words (must have at least one)
        whitelist = self._get_whitelist()
        if whitelist:
            text = f"{vacancy.title} {vacancy.description}".lower()
            has_whitelist = any(word.lower() in text for word in whitelist)
            if not has_whitelist:
                return False, FilterReason.NO_WHITELIST

        # Customer rating filter
        if self.profile and self.profile.min_customer_rating is not None:
            if vacancy.customer_rating and vacancy.customer_rating < self.profile.min_customer_rating:
                return False, f"{FilterReason.RATING_TOO_LOW} ({vacancy.customer_rating})"

        # Max proposals filter
        if self.profile and self.profile.max_proposals_count is not None:
            if vacancy.proposals_count and vacancy.proposals_count > self.profile.max_proposals_count:
                return False, f"{FilterReason.TOO_MANY_PROPOSALS} ({vacancy.proposals_count})"

        return True, None

    def apply_post_filters(self, vacancy: JobVacancy) -> Tuple[bool, Optional[str]]:
        """
        Level 2: Post-filters applied AFTER AI analysis.
        Returns (should_keep, reason_if_filtered).
        """
        # Filter by AI score
        if vacancy.ai_score is not None and vacancy.ai_score < DEFAULT_MIN_SCORE:
            return False, f"{FilterReason.AI_SCORE_TOO_LOW} ({vacancy.ai_score})"

        # Filter by match percentage
        if vacancy.match_percentage is not None and vacancy.match_percentage < DEFAULT_MIN_MATCH:
            return False, f"{FilterReason.MATCH_TOO_LOW} ({vacancy.match_percentage}%)"

        return True, None

    def _get_blacklist(self) -> List[str]:
        """Get blacklist words from profile."""
        if not self.profile or not self.profile.blacklist_words:
            return []
        return self.profile.blacklist_words_list

    def _get_whitelist(self) -> List[str]:
        """Get whitelist words from profile."""
        if not self.profile or not self.profile.whitelist_words:
            return []
        return self.profile.whitelist_words_list


def quick_budget_filter(text: str, min_budget: Optional[int], max_budget: Optional[int]) -> bool:
    """Quick budget extraction and filter for raw text."""
    numbers = re.findall(r"\d[\d\s]*", text.replace(" ", "").replace("\u2009", ""))
    values = []
    for num in numbers:
        try:
            val = int(num)
            if val > 100:  # Likely a price, not a date
                values.append(val)
        except ValueError:
            continue

    if not values:
        return True  # Can't determine budget, let it through

    max_val = max(values)
    min_val = min(values)

    if min_budget is not None and max_val < min_budget:
        return False
    if max_budget is not None and min_val > max_budget:
        return False

    return True
