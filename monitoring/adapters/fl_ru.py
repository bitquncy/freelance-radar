"""FL.ru adapter (Phase 2 source, §3.1 / §14) — HTTP + BeautifulSoup.

Polite scraping per §8: request pacing at human-refresh frequency, the
project's own User-Agent (no masquerading as third-party services), and the
adapter can be disabled instantly by pausing the connection.

The HTML structure of FL.ru changes periodically; parsing is defensive and
returns an empty list rather than raising, so one broken source never stalls
the whole tick (§3.1: adding/removing a source must not touch the core).
"""
import asyncio
import random
import re
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from core.models import Platform
from monitoring.adapters.base import RawListing, SourceAdapter
from services.logger_config import get_logger

logger = get_logger(__name__)

FL_RU_PROJECTS_URL = "https://www.fl.ru/projects/"
_BUDGET_RE = re.compile(r"(\d[\d\s]*)\s*(?:руб|₽)", re.IGNORECASE)
_PROJECT_ID_RE = re.compile(r"/projects/(\d+)")


def parse_budget(text: str) -> Optional[int]:
    """Extract a ruble budget number from free text."""
    match = _BUDGET_RE.search(text or "")
    if not match:
        return None
    digits = match.group(1).replace(" ", "").replace("\xa0", "")
    try:
        return int(digits)
    except ValueError:
        return None


def parse_projects_html(html: str) -> List[RawListing]:
    """Parse the FL.ru projects page into raw listings (defensive)."""
    listings: List[RawListing] = []
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href*='/projects/']"):
        href = link.get("href") or ""
        id_match = _PROJECT_ID_RE.search(str(href))
        title = link.get_text(strip=True)
        if not id_match or not title or len(title) < 8:
            continue
        external_id = id_match.group(1)
        if any(item.external_id == external_id for item in listings):
            continue
        container = link.find_parent(["div", "article", "li"])
        context_text = container.get_text(" ", strip=True) if container else title
        listings.append(
            RawListing(
                source=Platform.FL_RU,
                external_id=external_id,
                title=title[:300],
                description_raw=context_text[:2000],
                budget_raw=None,
                budget_min=parse_budget(context_text),
                url=f"https://www.fl.ru/projects/{external_id}/",
                raw_payload={},
            )
        )
    return listings


class FLRuAdapter(SourceAdapter):
    """Adapter for FL.ru public project listings."""

    platform = Platform.FL_RU

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        url: str = FL_RU_PROJECTS_URL,
        delay_range: tuple = (2.0, 5.0),
    ) -> None:
        """Create the adapter.

        Args:
            client: Injectable HTTP client (tests pass a mock transport).
            url: Projects listing URL.
            delay_range: Polite pre-request delay bounds, seconds (§8).
        """
        self._client = client
        self._url = url
        self._delay_range = delay_range

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            from config import get_config

            self._client = httpx.AsyncClient(
                headers={"User-Agent": get_config().USER_AGENT},
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    async def fetch(self) -> List[RawListing]:
        """Fetch the first page of fresh FL.ru projects."""
        client = await self._get_client()
        await asyncio.sleep(random.uniform(*self._delay_range))
        try:
            response = await client.get(self._url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("adapter.fl_ru_error", error=str(exc))
            return []
        listings = parse_projects_html(response.text)
        logger.info("adapter.fl_ru_fetched", count=len(listings))
        return listings

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
