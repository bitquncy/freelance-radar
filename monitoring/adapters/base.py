"""Adapter contract — AGENTS.md §3.1.

Every source is a separate adapter with the single interface
``fetch() -> list[RawListing]`` so adding a source never touches the core
(collector, scoring, generation).
"""
import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.models import Platform


@dataclass
class RawListing:
    """A raw listing normalized just enough to enter the collector."""

    source: Platform
    external_id: str
    title: str
    description_raw: str = ""
    budget_raw: Optional[str] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    currency: str = "RUB"
    category: Optional[str] = None
    proposals_count: Optional[int] = None
    client_rating: Optional[float] = None
    client_orders: Optional[int] = None
    posted_at: Optional[datetime] = None
    url: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class SourceAdapter(abc.ABC):
    """Base class for all V2 source adapters."""

    platform: Platform

    @abc.abstractmethod
    async def fetch(self) -> List[RawListing]:
        """Fetch fresh listings from the source.

        Returns:
            Raw listings (possibly overlapping with already-seen ones — the
            collector is responsible for deduplication, §3.1).
        """

    async def close(self) -> None:
        """Release adapter resources (optional override)."""
        return None
