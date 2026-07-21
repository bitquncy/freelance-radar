"""Persistent rate limiter using SQLite for state persistence."""
import asyncio
from datetime import datetime

import aiosqlite

from services.logger_config import get_logger
from config import DB_PATH

logger = get_logger(__name__)


class PersistentRateLimiter:
    """Rate limiter with SQLite-backed state persistence.

    Survives bot restarts by storing counters in the database.
    """

    def __init__(
        self,
        daily_limit: int = 200,
        delay_min: float = 2.0,
        delay_max: float = 5.0,
        night_delay_multiplier: float = 2.0,
    ):
        self.daily_limit = daily_limit
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.night_delay_multiplier = night_delay_multiplier
        self._last_request_time: float = 0

    async def _get_requests_today(self) -> int:
        """Get request count for today from DB."""
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rate_limiter (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(date)
                )
            """)
            cursor = await db.execute(
                "SELECT requests FROM rate_limiter WHERE date = ?",
                (today,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def _increment_requests(self) -> None:
        """Increment request counter for today."""
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO rate_limiter (date, requests)
                VALUES (?, 1)
                ON CONFLICT(date) DO UPDATE SET requests = requests + 1
            """, (today,))
            await db.commit()

    async def can_make_request(self) -> bool:
        """Check if we can make another request today."""
        requests = await self._get_requests_today()
        return requests < self.daily_limit

    async def record_request(self) -> None:
        """Record that we made a request."""
        await self._increment_requests()

    def get_delay(self) -> float:
        """Get adaptive delay based on time of day."""
        import random

        hour = datetime.now().hour
        base_delay = random.uniform(self.delay_min, self.delay_max)

        if 0 <= hour < 8:
            return base_delay * self.night_delay_multiplier
        if 18 <= hour < 24:
            return base_delay * 1.3

        return base_delay

    async def sleep(self) -> None:
        """Sleep for the calculated delay."""
        delay = self.get_delay()
        requests = await self._get_requests_today()
        logger.debug(
            "rate_limiter.sleep",
            delay_seconds=round(delay, 2),
            requests_today=requests,
            daily_limit=self.daily_limit,
        )
        await asyncio.sleep(delay)

    async def get_status(self) -> dict:
        """Get current rate limiter status."""
        requests = await self._get_requests_today()
        return {
            "requests_today": requests,
            "daily_limit": self.daily_limit,
            "remaining": max(0, self.daily_limit - requests),
            "reset_date": datetime.now().strftime("%Y-%m-%d"),
        }
