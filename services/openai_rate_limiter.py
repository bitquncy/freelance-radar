"""Rate limiter for OpenAI API to prevent 429 errors and manage costs."""
import asyncio
import time
from typing import Optional, List, Dict

from services.logger_config import get_logger

logger = get_logger(__name__)


class OpenAIRateLimiter:
    """Rate limiter for OpenAI API requests.

    Implements token bucket algorithm with:
    - Requests per minute limit (RPM)
    - Requests per day limit (RPD)
    - Minimum delay between requests
    """

    def __init__(
        self,
        max_rpm: int = 20,  # OpenAI default for gpt-4o-mini
        min_delay: float = 3.0,
        daily_limit: Optional[int] = None,
    ):
        self.max_rpm = max_rpm
        self.min_delay = min_delay
        self.daily_limit = daily_limit

        self._last_request_time: float = 0
        self._requests_in_minute: List[float] = []
        self._requests_today: int = 0
        self._day_start: float = time.time()

    async def acquire(self) -> None:
        """Wait until request can be made according to rate limits."""
        now = time.time()

        # Reset daily counter
        if now - self._day_start >= 86400:
            self._requests_today = 0
            self._day_start = now
            logger.info("openai_rate_limiter.daily_reset")

        # Check daily limit
        if self.daily_limit and self._requests_today >= self.daily_limit:
            raise Exception(f"OpenAI daily limit reached: {self.daily_limit}")

        # Clean old requests from minute window
        self._requests_in_minute = [
            t for t in self._requests_in_minute if now - t < 60
        ]

        # Wait if RPM exceeded
        if len(self._requests_in_minute) >= self.max_rpm:
            oldest = self._requests_in_minute[0]
            wait = 60 - (now - oldest) + 0.1
            logger.warning(
                "openai_rate_limiter.rpm_wait",
                wait_seconds=wait,
                current_rpm=len(self._requests_in_minute),
            )
            await asyncio.sleep(wait)
            now = time.time()
            self._requests_in_minute = [
                t for t in self._requests_in_minute if now - t < 60
            ]

        # Enforce minimum delay between requests
        elapsed = now - self._last_request_time
        if elapsed < self.min_delay:
            wait = self.min_delay - elapsed
            await asyncio.sleep(wait)

        self._last_request_time = time.time()
        self._requests_in_minute.append(self._last_request_time)
        self._requests_today += 1

        logger.debug(
            "openai_rate_limiter.request_allowed",
            rpm=len(self._requests_in_minute),
            today=self._requests_today,
        )

    def get_status(self) -> Dict:
        """Get current rate limiter status."""
        now = time.time()
        self._requests_in_minute = [
            t for t in self._requests_in_minute if now - t < 60
        ]
        return {
            "rpm_current": len(self._requests_in_minute),
            "rpm_limit": self.max_rpm,
            "today": self._requests_today,
            "daily_limit": self.daily_limit,
            "min_delay": self.min_delay,
        }
