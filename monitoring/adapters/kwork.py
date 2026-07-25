"""Kwork adapter — wraps the existing Playwright-based parser (§3.1, §4.2).

The legacy ``KworkParser`` already implements polite request pacing; this
adapter only maps its output to :class:`RawListing`. Scraping frequency is
controlled by the worker and NEVER increased without explicit approval
(AGENTS.md §12.7).
"""
from typing import List, Optional

from db.models import JobVacancy
from core.models import Platform
from monitoring.adapters.base import RawListing, SourceAdapter
from services.logger_config import get_logger

logger = get_logger(__name__)


def vacancy_to_listing(vacancy: JobVacancy, platform: Platform) -> RawListing:
    """Map a legacy ``JobVacancy`` to a V2 ``RawListing``."""
    return RawListing(
        source=platform,
        external_id=str(vacancy.kwork_id),
        title=vacancy.title or "",
        description_raw=vacancy.description or "",
        budget_raw=vacancy.budget,
        budget_min=vacancy.budget_min,
        budget_max=vacancy.budget_max,
        category=vacancy.category,
        proposals_count=vacancy.proposals_count,
        client_rating=vacancy.customer_rating,
        client_orders=vacancy.customer_orders,
        posted_at=vacancy.fetched_at,
        url=vacancy.url,
        raw_payload={"deadline": vacancy.deadline, "skills": vacancy.skills_list},
    )


class KworkAdapter(SourceAdapter):
    """Adapter over the legacy Playwright Kwork parser."""

    platform = Platform.KWORK

    def __init__(self, parser: Optional[object] = None) -> None:
        """Create the adapter.

        Args:
            parser: Injectable parser exposing ``fetch_vacancies()`` (tests
                pass a fake; production lazily builds the real one so that
                importing this module never requires Playwright).
        """
        self._parser = parser

    async def fetch(self) -> List[RawListing]:
        """Fetch current Kwork projects as raw listings."""
        if self._parser is None:
            from parsers.kwork import KworkParser

            self._parser = KworkParser()
        vacancies = await self._parser.fetch_vacancies()  # type: ignore[attr-defined]
        listings = [vacancy_to_listing(v, self.platform) for v in vacancies]
        logger.info("adapter.kwork_fetched", count=len(listings))
        return listings
