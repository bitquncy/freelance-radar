"""Распределённый лимит Telegram Bot API для рассылок."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from services.logger_config import get_logger

logger = get_logger(__name__)


class BroadcastRateLimiter(Protocol):
    """Минимальный контракт лимитера."""

    async def acquire(self) -> None:
        """Дождаться разрешения на один API-вызов."""

    async def close(self) -> None:
        """Освободить ресурсы."""


class LocalSlidingWindowLimiter:
    """Локальный fallback для тестов и разработки без Redis."""

    def __init__(self, rate: int, period: float = 1.0) -> None:
        self.rate = max(1, rate)
        self.period = period
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._events and self._events[0] <= now - self.period:
                    self._events.popleft()
                if len(self._events) < self.rate:
                    self._events.append(now)
                    return
                delay = self.period - (now - self._events[0])
            await asyncio.sleep(max(0.001, delay))

    async def close(self) -> None:
        return None


class RedisSlidingWindowLimiter:
    """Redis sliding-window limiter, общий для всех процессов."""

    _SCRIPT = """
local redis_time = redis.call('TIME')
local now = redis_time[1] * 1000 + math.floor(redis_time[2] / 1000)
local period = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - period)
local current = redis.call('ZCARD', KEYS[1])
if current < tonumber(ARGV[1]) then
    local sequence = redis.call('INCR', KEYS[2])
    redis.call('ZADD', KEYS[1], now, tostring(now) .. '-' .. tostring(sequence))
    redis.call('PEXPIRE', KEYS[1], period + 100)
    redis.call('PEXPIRE', KEYS[2], period + 100)
    return 0
end
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
return math.max(period - (now - tonumber(oldest[2])), 1)
"""

    def __init__(
        self, redis_url: str, rate: int, key: str = "broadcast:rate:global"
    ) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=False)
        self.rate = max(1, rate)
        self.key = key

    async def acquire(self) -> None:
        while True:
            delay_ms = int(
                await self.redis.eval(
                    self._SCRIPT,
                    2,
                    self.key,
                    f"{self.key}:sequence",
                    self.rate,
                    1000,
                )
            )
            if delay_ms <= 0:
                return
            await asyncio.sleep(delay_ms / 1000)

    async def close(self) -> None:
        await self.redis.aclose()


class ResilientRedisLimiter:
    """Fall back locally if Redis is temporarily unavailable."""

    def __init__(self, redis_url: str, rate: int) -> None:
        self.primary = RedisSlidingWindowLimiter(redis_url, rate)
        self.fallback = LocalSlidingWindowLimiter(rate)
        self._degraded = False

    async def acquire(self) -> None:
        if self._degraded:
            await self.fallback.acquire()
            return
        try:
            await self.primary.acquire()
        except (RedisError, OSError, TimeoutError) as exc:
            self._degraded = True
            logger.error("broadcast.redis_rate_limiter_unavailable", error=str(exc))
            await self.fallback.acquire()

    async def close(self) -> None:
        try:
            await self.primary.close()
        except (RedisError, OSError, TimeoutError):
            pass


def build_broadcast_limiter(redis_url: str | None, rate: int) -> BroadcastRateLimiter:
    """Создать Redis-лимитер или безопасный локальный fallback."""
    if redis_url:
        return ResilientRedisLimiter(redis_url, rate)
    return LocalSlidingWindowLimiter(rate)
