"""Критические сценарии PostgreSQL-compatible рассылки."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from telegram.error import BadRequest, ChatMigrated, Forbidden, NetworkError, RetryAfter

from bot.handlers.broadcast_handler import _parse_buttons
from core.models import Base, BroadcastRecipient
from services.broadcast.rate_limiter import LocalSlidingWindowLimiter
from services.broadcast.repository import BroadcastRepository
from services.broadcast.runner import BroadcastRunner
from services.broadcast.sender import BroadcastSender


class ImmediateGate:
    def __init__(self) -> None:
        self.pauses: list[float] = []

    async def wait(self) -> None:
        return None

    async def pause(self, seconds: float) -> None:
        self.pauses.append(seconds)


class ImmediateLimiter:
    def __init__(self) -> None:
        self.acquisitions = 0

    async def acquire(self) -> None:
        self.acquisitions += 1

    async def close(self) -> None:
        return None


@dataclass
class BroadcastSetup:
    engine: AsyncEngine
    repository: BroadcastRepository
    group_id: int

    async def add_chats(
        self,
        *chat_ids: int,
        chat_type: str = "supergroup",
        language_code: str | None = "ru",
    ) -> None:
        for chat_id in chat_ids:
            assert await self.repository.add_recipient(
                group_id=self.group_id,
                owner_telegram_id=1,
                chat_id=chat_id,
                chat_type=chat_type,
                title=str(chat_id),
                username=None,
                language_code=language_code,
            )

    async def create(
        self,
        *,
        source_message_ids: list[int] | None = None,
        reply_markup: list[list[dict[str, str]]] | None = None,
        filters: dict | None = None,
    ) -> int:
        broadcast_id, _ = await self.repository.create_broadcast(
            owner_telegram_id=1,
            group_id=self.group_id,
            source_chat_id=1,
            source_message_ids=source_message_ids or [100],
            content_type=(
                "media_group"
                if source_message_ids and len(source_message_ids) > 1
                else "copy"
            ),
            reply_markup=reply_markup,
            filters=filters or {"chat_types": [], "languages": []},
            progress_chat_id=1,
            progress_message_id=200,
        )
        return broadcast_id


@pytest.fixture
async def broadcast_setup(tmp_path) -> BroadcastSetup:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'broadcast.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = BroadcastRepository(factory)
    group_id = await repository.create_group(1, "Разрешённые чаты")
    yield BroadcastSetup(engine, repository, group_id)
    await engine.dispose()


def _sender(setup: BroadcastSetup, bot: AsyncMock, gate=None, limiter=None):
    return BroadcastSender(
        bot=bot,
        repository=setup.repository,
        max_retries=3,
        pause_gate=gate or ImmediateGate(),
        rate_limiter=limiter or ImmediateLimiter(),
    )


def _runner(setup: BroadcastSetup, bot: AsyncMock, *, rate: int = 2) -> BroadcastRunner:
    return BroadcastRunner(
        bot=bot,
        repository=setup.repository,
        rate_limit=rate,
        batch_size=25,
        max_retries=3,
        progress_interval=5,
        min_chat_interval_sec=3600,
        rate_limiter=ImmediateLimiter(),
    )


@pytest.mark.asyncio
async def test_retry_after_pauses_worker_and_retries_same_target(
    broadcast_setup,
) -> None:
    await broadcast_setup.add_chats(-1001)
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = [RetryAfter(0), object()]
    gate = ImmediateGate()

    result = await _sender(broadcast_setup, bot, gate=gate).send(broadcast, target)

    assert result == "sent"
    assert bot.copy_message.await_count == 2
    assert gate.pauses == [1.0]
    assert (await broadcast_setup.repository.counts(broadcast_id))["sent"] == 1


@pytest.mark.asyncio
async def test_forbidden_deactivates_chat_without_retry(broadcast_setup) -> None:
    await broadcast_setup.add_chats(-1002)
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = Forbidden("bot was blocked")

    assert await _sender(broadcast_setup, bot).send(broadcast, target) == "blocked"
    assert bot.copy_message.await_count == 1
    recipients = await broadcast_setup.repository.list_recipients(
        broadcast_setup.group_id
    )
    assert recipients == []


@pytest.mark.asyncio
async def test_bad_request_for_missing_chat_deactivates_without_retry(
    broadcast_setup,
) -> None:
    await broadcast_setup.add_chats(-1004)
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = BadRequest("chat not found")

    assert await _sender(broadcast_setup, bot).send(broadcast, target) == "failed"
    assert (
        await broadcast_setup.repository.list_recipients(broadcast_setup.group_id) == []
    )


@pytest.mark.asyncio
async def test_network_error_retries_with_exponential_backoff(
    broadcast_setup, monkeypatch
) -> None:
    await broadcast_setup.add_chats(-1005)
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = [
        NetworkError("temporary"),
        NetworkError("temporary"),
        object(),
    ]
    sleep_mock = AsyncMock()
    monkeypatch.setattr("services.broadcast.sender.asyncio.sleep", sleep_mock)

    assert await _sender(broadcast_setup, bot).send(broadcast, target) == "sent"
    assert [call.args[0] for call in sleep_mock.await_args_list] == [1.0, 4.0]


@pytest.mark.asyncio
async def test_migrated_group_is_updated_and_retried(broadcast_setup) -> None:
    await broadcast_setup.add_chats(-1006)
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = [ChatMigrated(-1006000), object()]

    assert await _sender(broadcast_setup, bot).send(broadcast, target) == "sent"
    assert bot.copy_message.await_args_list[1].kwargs["chat_id"] == -1006000


@pytest.mark.asyncio
async def test_media_group_and_url_buttons_are_delivered(broadcast_setup) -> None:
    await broadcast_setup.add_chats(-1010)
    markup = [[{"text": "Открыть", "url": "https://example.com"}]]
    broadcast_id = await broadcast_setup.create(
        source_message_ids=[10, 11, 12], reply_markup=markup
    )
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    limiter = ImmediateLimiter()

    assert (
        await _sender(broadcast_setup, bot, limiter=limiter).send(broadcast, target)
        == "sent"
    )
    bot.copy_messages.assert_awaited_once()
    assert bot.copy_messages.await_args.kwargs["message_ids"] == (10, 11, 12)
    bot.send_message.assert_awaited_once()
    assert limiter.acquisitions == 2


@pytest.mark.asyncio
async def test_filter_snapshot_uses_type_language_and_active_state(
    broadcast_setup,
) -> None:
    await broadcast_setup.add_chats(-1, chat_type="channel", language_code="ru")
    await broadcast_setup.add_chats(-2, chat_type="channel", language_code="en")
    await broadcast_setup.add_chats(-3, chat_type="supergroup", language_code="ru")

    broadcast_id = await broadcast_setup.create(
        filters={"chat_types": ["channel"], "languages": ["ru"]}
    )

    counts = await broadcast_setup.repository.counts(broadcast_id)
    assert counts["total"] == 1


@pytest.mark.asyncio
async def test_restart_does_not_repeat_uncertain_send(broadcast_setup) -> None:
    await broadcast_setup.add_chats(-1003)
    broadcast_id = await broadcast_setup.create()
    await broadcast_setup.repository.claim_targets(broadcast_id, 1)
    bot = AsyncMock()

    await _runner(broadcast_setup, bot).run_due()

    bot.copy_message.assert_not_awaited()
    counts = await broadcast_setup.repository.counts(broadcast_id)
    assert counts["skipped"] == 1
    assert await broadcast_setup.repository.status(broadcast_id) == "done"


@pytest.mark.asyncio
async def test_runner_limits_batch_and_waits_for_rate_window(
    broadcast_setup, monkeypatch
) -> None:
    await broadcast_setup.add_chats(*[-200 - value for value in range(5)])
    broadcast_id = await broadcast_setup.create()
    bot = AsyncMock()
    sleep_mock = AsyncMock()
    monkeypatch.setattr("services.broadcast.runner.asyncio.sleep", sleep_mock)
    runner = _runner(broadcast_setup, bot, rate=2)

    await runner.run_due()

    assert runner.batch_size == 2
    assert bot.copy_message.await_count == 5
    assert sleep_mock.await_count == 3
    assert await broadcast_setup.repository.status(broadcast_id) == "done"


@pytest.mark.asyncio
async def test_one_target_task_failure_does_not_stop_batch(broadcast_setup) -> None:
    await broadcast_setup.add_chats(-301, -302)
    broadcast_id = await broadcast_setup.create()
    bot = AsyncMock()
    runner = _runner(broadcast_setup, bot)

    async def isolated_send(broadcast, target):
        if target.chat_id == -301:
            raise RuntimeError("isolated")
        await broadcast_setup.repository.target_succeeded(target)
        return "sent"

    runner.sender.send = isolated_send
    await runner.run_due()

    counts = await broadcast_setup.repository.counts(broadcast_id)
    assert counts["failed"] == 1
    assert counts["sent"] == 1
    assert await broadcast_setup.repository.status(broadcast_id) == "done"


@pytest.mark.asyncio
async def test_cancellation_stops_after_current_batch(broadcast_setup) -> None:
    await broadcast_setup.add_chats(*[-300 - value for value in range(5)])
    broadcast_id = await broadcast_setup.create()
    bot = AsyncMock()
    cancellation_started = False

    async def copy_and_cancel(**_) -> object:
        nonlocal cancellation_started
        if not cancellation_started:
            cancellation_started = True
            await broadcast_setup.repository.set_status(broadcast_id, "cancelled")
        return object()

    bot.copy_message.side_effect = copy_and_cancel
    runner = _runner(broadcast_setup, bot)
    await runner.run_due()

    assert bot.copy_message.await_count == 2
    counts = await broadcast_setup.repository.counts(broadcast_id)
    assert counts["sent"] == 2
    assert counts["skipped"] == 3


@pytest.mark.asyncio
async def test_local_rate_limiter_never_exceeds_three_calls_per_second() -> None:
    limiter = LocalSlidingWindowLimiter(3)
    started = time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(4)))
    assert time.monotonic() - started >= 0.9


@pytest.mark.asyncio
async def test_ten_thousand_recipient_snapshot(broadcast_setup) -> None:
    factory = broadcast_setup.repository.session_factory
    async with factory() as session:
        session.add_all(
            BroadcastRecipient(
                group_id=broadcast_setup.group_id,
                chat_id=-1_000_000 - value,
                chat_type="channel",
                title=None,
                username=None,
                language_code="ru",
                is_active=True,
            )
            for value in range(10_000)
        )
        await session.commit()

    broadcast_id = await broadcast_setup.create()
    assert (await broadcast_setup.repository.counts(broadcast_id))["total"] == 10_000


def test_url_button_validation() -> None:
    assert _parse_buttons("Сайт | https://example.com") == [
        [{"text": "Сайт", "url": "https://example.com"}]
    ]
    with pytest.raises(ValueError):
        _parse_buttons("Опасно | javascript:alert(1)")


def test_models_contain_postgresql_broadcast_queue() -> None:
    assert {
        "broadcast_groups",
        "broadcast_recipients",
        "broadcast_campaigns",
        "broadcast_targets_v2",
    } <= set(Base.metadata.tables)
