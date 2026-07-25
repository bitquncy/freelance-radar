"""Telegram channels adapter (§3.1).

Wraps the existing channel parser (public web preview by default; the
Telethon session — where configured — follows §8: a dedicated account,
read-only). Channel list comes from users' ``ExchangeConnection.settings``.
"""
from typing import List, Optional, Sequence

from core.models import Platform
from monitoring.adapters.base import RawListing, SourceAdapter
from monitoring.adapters.kwork import vacancy_to_listing
from services.logger_config import get_logger

logger = get_logger(__name__)


class TelegramChannelsAdapter(SourceAdapter):
    """Adapter over the legacy Telegram channel parser."""

    platform = Platform.TG_CHANNEL

    def __init__(
        self,
        channels: Sequence[str],
        parser: Optional[object] = None,
        limit_per_channel: int = 20,
    ) -> None:
        """Create the adapter.

        Args:
            channels: Channel usernames (with or without ``@``).
            parser: Injectable parser exposing
                ``fetch_messages_from_channel(channel, limit)``.
            limit_per_channel: Messages to scan per channel per tick.
        """
        self._channels = [self._normalize(c) for c in channels if c and c.strip()]
        self._parser = parser
        self._limit = limit_per_channel

    @staticmethod
    def _normalize(channel: str) -> str:
        username = channel.strip().split("/")[-1]
        return username if username.startswith("@") else f"@{username}"

    async def fetch(self) -> List[RawListing]:
        """Fetch recent messages from all configured channels."""
        if not self._channels:
            return []
        if self._parser is None:
            from parsers.telegram_source import TelegramSourceParser

            self._parser = TelegramSourceParser()
            await self._parser.connect()
        listings: List[RawListing] = []
        for channel in self._channels:
            try:
                vacancies = await self._parser.fetch_messages_from_channel(  # type: ignore[attr-defined]
                    channel, limit=self._limit
                )
            except (ValueError, TypeError, ConnectionError, OSError) as exc:
                logger.error(
                    "adapter.tg_channel_error", channel=channel, error=str(exc)
                )
                continue
            for vacancy in vacancies:
                listing = vacancy_to_listing(vacancy, self.platform)
                listing.raw_payload["channel"] = channel
                listings.append(listing)
        logger.info("adapter.tg_fetched", count=len(listings))
        return listings

    async def close(self) -> None:
        """Disconnect the underlying parser if it was created."""
        if self._parser is not None and hasattr(self._parser, "disconnect"):
            await self._parser.disconnect()
