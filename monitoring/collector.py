"""Collector: deduplication + normalization + DB write — AGENTS.md §3.1, §4.1.

Deduplication is two-layered:
    1. Exact: unique ``(source, external_id)``.
    2. Fuzzy: normalized-title similarity + budget proximity, to catch the
       same order reposted across several channels (§3.1).
"""
import re
from dataclasses import dataclass, field
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Iterable, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Project, utcnow
from monitoring.adapters.base import RawListing
from services.logger_config import get_logger

logger = get_logger(__name__)

FUZZY_TITLE_THRESHOLD = 0.90
FUZZY_BUDGET_TOLERANCE = 0.10
FUZZY_WINDOW_DAYS = 3

_WS_RE = re.compile(r"\s+")
_NOISE_RE = re.compile(r"[^\w\sа-яё]", re.IGNORECASE)


def normalize_title(title: str) -> str:
    """Normalize a title for fuzzy comparison (§3.1)."""
    cleaned = _NOISE_RE.sub(" ", (title or "").casefold())
    return _WS_RE.sub(" ", cleaned).strip()


def titles_similar(a: str, b: str, threshold: float = FUZZY_TITLE_THRESHOLD) -> bool:
    """Compare two normalized titles with difflib ratio."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def budgets_close(
    a: Optional[int], b: Optional[int], tolerance: float = FUZZY_BUDGET_TOLERANCE
) -> bool:
    """Budgets match when both missing or within relative tolerance."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    top = max(abs(a), abs(b))
    if top == 0:
        return True
    return abs(a - b) / top <= tolerance


def is_fuzzy_duplicate(listing: RawListing, existing: Project) -> bool:
    """Fuzzy-duplicate check: same title (≈) and close budget (§3.1)."""
    return titles_similar(listing.title, existing.title) and budgets_close(
        listing.budget_min or listing.budget_max,
        existing.budget_min or existing.budget_max,
    )


@dataclass
class CollectResult:
    """Statistics + inserted projects for one collect pass."""

    new_projects: List[Project] = field(default_factory=list)
    duplicates_exact: int = 0
    duplicates_fuzzy: int = 0
    errors: int = 0


class Collector:
    """Deduplicates raw listings and persists new projects."""

    def __init__(self, fuzzy_window_days: int = FUZZY_WINDOW_DAYS) -> None:
        """Create a collector.

        Args:
            fuzzy_window_days: How far back to look for fuzzy repost matches.
        """
        self._fuzzy_window = timedelta(days=fuzzy_window_days)

    async def _load_recent(self, session: AsyncSession) -> List[Project]:
        cutoff = utcnow() - self._fuzzy_window
        result = await session.execute(
            select(Project).where(Project.created_at >= cutoff)
        )
        return list(result.scalars().all())

    async def _exists_exact(
        self, session: AsyncSession, listing: RawListing
    ) -> bool:
        result = await session.execute(
            select(Project.id).where(
                Project.source == listing.source,
                Project.external_id == listing.external_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def collect(
        self, session: AsyncSession, listings: Iterable[RawListing]
    ) -> CollectResult:
        """Deduplicate and persist listings; returns inserted projects.

        Args:
            session: Open async session (caller controls the transaction).
            listings: Raw listings from adapters.
        """
        result = CollectResult()
        recent = await self._load_recent(session)
        seen_this_run: Set[Tuple[str, str]] = set()

        for listing in listings:
            key = (listing.source.value, listing.external_id)
            if key in seen_this_run:
                result.duplicates_exact += 1
                continue
            seen_this_run.add(key)

            if await self._exists_exact(session, listing):
                result.duplicates_exact += 1
                continue

            if any(is_fuzzy_duplicate(listing, project) for project in recent):
                result.duplicates_fuzzy += 1
                logger.info(
                    "collector.fuzzy_duplicate",
                    source=listing.source.value,
                    external_id=listing.external_id,
                    title=listing.title[:50],
                )
                continue

            project = Project(
                source=listing.source,
                external_id=listing.external_id,
                title=listing.title,
                description_raw=listing.description_raw,
                budget_raw=listing.budget_raw,
                budget_min=listing.budget_min,
                budget_max=listing.budget_max,
                currency=listing.currency,
                category=listing.category,
                proposals_count=listing.proposals_count,
                client_rating=listing.client_rating,
                client_orders=listing.client_orders,
                posted_at=listing.posted_at,
                url=listing.url,
                raw_payload=listing.raw_payload,
            )
            # Savepoint per insert: a concurrent tick (multi-worker deploy)
            # inserting the same (source, external_id) must not kill the
            # whole batch — the loser is just a duplicate (§3.1).
            try:
                async with session.begin_nested():
                    session.add(project)
                    await session.flush()
            except IntegrityError:
                result.duplicates_exact += 1
                logger.info(
                    "collector.concurrent_duplicate",
                    source=listing.source.value,
                    external_id=listing.external_id,
                )
                continue
            recent.append(project)
            result.new_projects.append(project)

        logger.info(
            "collector.collected",
            new=len(result.new_projects),
            dup_exact=result.duplicates_exact,
            dup_fuzzy=result.duplicates_fuzzy,
        )
        return result
