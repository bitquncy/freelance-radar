"""Redis rate-limit and FSM persistence contract tests without a real server."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.broadcast.rate_limiter import RedisSlidingWindowLimiter
from services.redis_persistence import RedisPersistence


@pytest.mark.asyncio
async def test_redis_limiter_uses_atomic_sliding_window_script() -> None:
    limiter = RedisSlidingWindowLimiter("redis://localhost:6379/15", rate=25)
    limiter.redis = AsyncMock()
    limiter.redis.eval.return_value = 0

    await limiter.acquire()

    args = limiter.redis.eval.await_args.args
    assert "ZREMRANGEBYSCORE" in args[0]
    assert args[1:] == (
        2,
        "broadcast:rate:global",
        "broadcast:rate:global:sequence",
        25,
        1000,
    )


@pytest.mark.asyncio
async def test_redis_persistence_round_trips_user_and_conversation_state() -> None:
    persistence = RedisPersistence("redis://localhost:6379/15")
    persistence.redis = AsyncMock()
    persistence.redis.hgetall.side_effect = [
        {"42": '{"broadcast_group_id":7}'},
        {"[42,42]": "8"},
    ]

    users = await persistence.get_user_data()
    conversations = await persistence.get_conversations("broadcast_conversation")
    await persistence.update_user_data(42, {"broadcast_group_id": 7})
    await persistence.update_conversation("broadcast_conversation", (42, 42), 8)

    assert users == {42: {"broadcast_group_id": 7}}
    assert conversations == {(42, 42): 8}
    assert persistence.redis.hset.await_count == 2
