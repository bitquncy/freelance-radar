"""Критические сценарии устойчивой и ограниченной рассылки."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import aiosqlite
import pytest
from telegram.error import BadRequest, ChatMigrated, Forbidden, NetworkError, RetryAfter

from db import init_db, queries
from services.broadcast.repository import BroadcastRepository
from services.broadcast.runner import BroadcastRunner
from services.broadcast.sender import BroadcastSender


@dataclass
class BroadcastSetup:
    db_path: str
    repository: BroadcastRepository
    group_id: int

    async def add_chats(self, *chat_ids: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            for chat_id in chat_ids:
                await queries.add_chat_to_group(db, self.group_id, chat_id, chat_id)

    async def create(self) -> int:
        broadcast_id, _ = await self.repository.create_broadcast(
            user_id=1,
            group_id=self.group_id,
            source_chat_id=1,
            source_message_id=100,
            progress_chat_id=1,
            progress_message_id=200,
        )
        return broadcast_id


@pytest.fixture
async def broadcast_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BroadcastSetup:
    db_path = str(tmp_path / "broadcast.db")
    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    await init_db.init_and_migrate()
    async with aiosqlite.connect(db_path) as db:
        group_id = await queries.create_chat_group(db, 1, "Разрешённые чаты")
    return BroadcastSetup(db_path, BroadcastRepository(db_path), group_id)


class ImmediateGate:
    def __init__(self) -> None:
        self.pauses: list[float] = []

    async def wait(self) -> None:
        return None

    async def pause(self, seconds: float) -> None:
        self.pauses.append(seconds)


@pytest.mark.asyncio
async def test_retry_after_pauses_worker_and_retries_same_target(
    broadcast_setup: BroadcastSetup,
) -> None:
    await broadcast_setup.add_chats("-1001")
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = [RetryAfter(0), object()]
    gate = ImmediateGate()
    sender = BroadcastSender(
        bot=bot,
        repository=broadcast_setup.repository,
        max_retries=3,
        pause_gate=gate,  # type: ignore[arg-type]
    )

    result = await sender.send(broadcast, target)  # type: ignore[arg-type]

    assert result == "sent"
    assert bot.copy_message.await_count == 2
    assert gate.pauses == [1.0]
    assert (await broadcast_setup.repository.counts(broadcast_id))["sent"] == 1


@pytest.mark.asyncio
async def test_forbidden_deactivates_chat_without_retry(
    broadcast_setup: BroadcastSetup,
) -> None:
    await broadcast_setup.add_chats("-1002")
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = Forbidden("bot was blocked")
    sender = BroadcastSender(
        bot=bot,
        repository=broadcast_setup.repository,
        max_retries=3,
        pause_gate=ImmediateGate(),  # type: ignore[arg-type]
    )

    result = await sender.send(broadcast, target)  # type: ignore[arg-type]

    assert result == "blocked"
    assert bot.copy_message.await_count == 1
    async with aiosqlite.connect(broadcast_setup.db_path) as db:
        cursor = await db.execute(
            "SELECT is_active, deactivated_reason FROM chat_group_members WHERE chat_id = ?",
            ("-1002",),
        )
        assert await cursor.fetchone() == (0, "forbidden")


@pytest.mark.asyncio
async def test_bad_request_for_missing_chat_deactivates_without_retry(
    broadcast_setup: BroadcastSetup,
) -> None:
    await broadcast_setup.add_chats("-1004")
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = BadRequest("chat not found")
    sender = BroadcastSender(
        bot=bot,
        repository=broadcast_setup.repository,
        max_retries=3,
        pause_gate=ImmediateGate(),  # type: ignore[arg-type]
    )

    assert await sender.send(broadcast, target) == "failed"  # type: ignore[arg-type]
    assert bot.copy_message.await_count == 1
    async with aiosqlite.connect(broadcast_setup.db_path) as db:
        cursor = await db.execute(
            "SELECT is_active FROM chat_group_members WHERE chat_id = ?", ("-1004",)
        )
        assert await cursor.fetchone() == (0,)


@pytest.mark.asyncio
async def test_network_error_retries_with_exponential_backoff(
    broadcast_setup: BroadcastSetup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await broadcast_setup.add_chats("-1005")
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = [NetworkError("temporary"), NetworkError("temporary"), object()]
    sleep_mock = AsyncMock()
    monkeypatch.setattr("services.broadcast.sender.asyncio.sleep", sleep_mock)
    sender = BroadcastSender(
        bot=bot,
        repository=broadcast_setup.repository,
        max_retries=3,
        pause_gate=ImmediateGate(),  # type: ignore[arg-type]
    )

    assert await sender.send(broadcast, target) == "sent"  # type: ignore[arg-type]
    assert [call.args[0] for call in sleep_mock.await_args_list] == [1.0, 4.0]
    assert bot.copy_message.await_count == 3


@pytest.mark.asyncio
async def test_migrated_group_is_updated_and_retried(
    broadcast_setup: BroadcastSetup,
) -> None:
    await broadcast_setup.add_chats("-1006")
    broadcast_id = await broadcast_setup.create()
    broadcast = await broadcast_setup.repository.get_broadcast(broadcast_id)
    target = (await broadcast_setup.repository.claim_targets(broadcast_id, 1))[0]
    bot = AsyncMock()
    bot.copy_message.side_effect = [ChatMigrated(-1006000), object()]
    sender = BroadcastSender(
        bot=bot,
        repository=broadcast_setup.repository,
        max_retries=3,
        pause_gate=ImmediateGate(),  # type: ignore[arg-type]
    )

    assert await sender.send(broadcast, target) == "sent"  # type: ignore[arg-type]
    assert bot.copy_message.await_args_list[1].kwargs["chat_id"] == "-1006000"
    async with aiosqlite.connect(broadcast_setup.db_path) as db:
        cursor = await db.execute(
            "SELECT chat_id FROM chat_group_members WHERE group_id = ?",
            (broadcast_setup.group_id,),
        )
        assert await cursor.fetchone() == ("-1006000",)


@pytest.mark.asyncio
async def test_restart_does_not_repeat_uncertain_send(
    broadcast_setup: BroadcastSetup,
) -> None:
    await broadcast_setup.add_chats("-1003")
    broadcast_id = await broadcast_setup.create()
    await broadcast_setup.repository.claim_targets(broadcast_id, 1)
    bot = AsyncMock()
    runner = BroadcastRunner(
        bot=bot,
        repository=broadcast_setup.repository,
        rate_limit=2,
        batch_size=2,
        max_retries=3,
        progress_interval=5,
        min_chat_interval_sec=3600,
    )

    await runner.run_due()

    bot.copy_message.assert_not_awaited()
    counts = await broadcast_setup.repository.counts(broadcast_id)
    assert counts["skipped"] == 1
    assert await broadcast_setup.repository.status(broadcast_id) == "done"


@pytest.mark.asyncio
async def test_runner_limits_batch_and_waits_for_rate_window(
    broadcast_setup: BroadcastSetup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await broadcast_setup.add_chats(*[f"-20{i}" for i in range(5)])
    broadcast_id = await broadcast_setup.create()
    bot = AsyncMock()
    sleep_mock = AsyncMock()
    monkeypatch.setattr("services.broadcast.runner.asyncio.sleep", sleep_mock)
    runner = BroadcastRunner(
        bot=bot,
        repository=broadcast_setup.repository,
        rate_limit=2,
        batch_size=25,
        max_retries=3,
        progress_interval=5,
        min_chat_interval_sec=3600,
    )

    await runner.run_due()

    assert runner.batch_size == 2
    assert bot.copy_message.await_count == 5
    assert sleep_mock.await_count == 3
    assert all(call.args[0] > 0.45 for call in sleep_mock.await_args_list)
    assert await broadcast_setup.repository.status(broadcast_id) == "done"


@pytest.mark.asyncio
async def test_cancellation_stops_after_current_batch(
    broadcast_setup: BroadcastSetup,
) -> None:
    await broadcast_setup.add_chats(*[f"-30{i}" for i in range(5)])
    broadcast_id = await broadcast_setup.create()
    bot = AsyncMock()
    cancellation_started = False

    async def copy_and_cancel(**_: object) -> object:
        nonlocal cancellation_started
        if not cancellation_started:
            cancellation_started = True
            await broadcast_setup.repository.set_status(broadcast_id, "cancelled")
        return object()

    bot.copy_message.side_effect = copy_and_cancel
    runner = BroadcastRunner(
        bot=bot,
        repository=broadcast_setup.repository,
        rate_limit=2,
        batch_size=2,
        max_retries=3,
        progress_interval=5,
        min_chat_interval_sec=3600,
    )

    await runner.run_due()

    assert bot.copy_message.await_count == 2
    counts = await broadcast_setup.repository.counts(broadcast_id)
    assert counts["sent"] == 2
    assert counts["skipped"] == 3
    assert await broadcast_setup.repository.status(broadcast_id) == "cancelled"


@pytest.mark.asyncio
async def test_migration_creates_durable_queue_schema(
    broadcast_setup: BroadcastSetup,
) -> None:
    async with aiosqlite.connect(broadcast_setup.db_path) as db:
        cursor = await db.execute("PRAGMA table_info(broadcasts)")
        columns = {row[1] for row in await cursor.fetchall()}
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='broadcast_targets'"
        )
        target_table = await cursor.fetchone()

    assert {"source_chat_id", "source_message_id", "scheduled_at", "blocked_count"} <= columns
    assert target_table == ("broadcast_targets",)


@pytest.mark.asyncio
async def test_migration_upgrades_existing_broadcast_table_before_indexing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production may already have the legacy table without scheduled_at."""
    db_path = str(tmp_path / "legacy-broadcast.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                message_text TEXT,
                message_type TEXT NOT NULL DEFAULT 'text',
                file_id TEXT,
                caption TEXT,
                sent_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
            """
        )
        await db.commit()

    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    await init_db.init_and_migrate()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(broadcasts)")
        columns = {row[1] for row in await cursor.fetchall()}
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_broadcasts_status_scheduled'"
        )
        index = await cursor.fetchone()

    assert "scheduled_at" in columns
    assert index == ("idx_broadcasts_status_scheduled",)
