"""Проверки глобального персистентного лимита запросов Kwork."""

from __future__ import annotations

import asyncio

from services import persistent_rate_limiter as limiter_module
from services.persistent_rate_limiter import PersistentRateLimiter


async def test_limit_is_atomic_and_shared_between_instances(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "rate-limit.db"
    monkeypatch.setattr(limiter_module, "DB_PATH", str(db_path))

    first = PersistentRateLimiter(daily_limit=3)
    results = await asyncio.gather(*(first.acquire_request() for _ in range(8)))
    assert sum(results) == 3

    second = PersistentRateLimiter(daily_limit=3)
    assert await second.can_make_request() is False
    status = await second.get_status()
    assert status["requests_today"] == 3
    assert status["remaining"] == 0
