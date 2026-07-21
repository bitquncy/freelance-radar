"""Rate limiting and adaptive delays for external services."""
import asyncio
import random
from datetime import datetime

from services.logger_config import get_logger

logger = get_logger(__name__)


class KworkRateLimiter:
    """Rate limiter for Kwork with daily limits and adaptive delays."""

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
        self._requests_today = 0
        self._last_reset = datetime.now().date()

    def _reset_if_new_day(self) -> None:
        """Reset counter if it's a new day."""
        today = datetime.now().date()
        if today != self._last_reset:
            self._requests_today = 0
            self._last_reset = today
            logger.info("rate_limiter.daily_reset", requests_reset=True)

    def can_make_request(self) -> bool:
        """Check if we can make another request today."""
        self._reset_if_new_day()
        return self._requests_today < self.daily_limit

    def record_request(self) -> None:
        """Record that we made a request."""
        self._reset_if_new_day()
        self._requests_today += 1

    def get_delay(self) -> float:
        """Get adaptive delay based on time of day."""
        hour = datetime.now().hour
        base_delay = random.uniform(self.delay_min, self.delay_max)

        # Night time (00:00 - 08:00): longer delays to be less suspicious
        if 0 <= hour < 8:
            return base_delay * self.night_delay_multiplier

        # Peak hours (18:00 - 23:00): slightly longer delays
        if 18 <= hour < 24:
            return base_delay * 1.3

        return base_delay

    async def sleep(self) -> None:
        """Sleep for the calculated delay."""
        delay = self.get_delay()
        logger.debug(
            "rate_limiter.sleep",
            delay_seconds=round(delay, 2),
            requests_today=self._requests_today,
            daily_limit=self.daily_limit,
        )
        await asyncio.sleep(delay)

    def get_status(self) -> dict:
        """Get current rate limiter status."""
        self._reset_if_new_day()
        return {
            "requests_today": self._requests_today,
            "daily_limit": self.daily_limit,
            "remaining": max(0, self.daily_limit - self._requests_today),
            "reset_date": self._last_reset.isoformat(),
        }
