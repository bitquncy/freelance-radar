"""Regression tests for the production-readiness audit fixes.

Each test pins a specific audit finding: N× extraction cost, double-tap
races, transaction/idempotency behavior, resource lifecycle, notification
accounting, tariff-limit bypass, healthcheck and enum-format bugs.
"""
import os
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import bot.handlers.v2.common as common_module
import monitoring.worker as worker_module
from bot.handlers.v2.crm_handlers import client_note_start
from bot.handlers.v2.proposals import proposal_edit_start, proposal_send
from bot.handlers.v2.sources import add_channel_from_text
from constants import FilterReason
from core.models import (
    Client,
    ExchangeConnection,
    Platform,
    ProjectAnalysis,
    Proposal,
    ProposalStatus,
    Reminder,
    ReminderStatus,
    SubscriptionTier,
    User,
    utcnow,
)
from monitoring.adapters.base import RawListing, SourceAdapter
from monitoring.collector import Collector
from monitoring.worker import run_radar_tick, run_reminders_tick
from services.blacklist import BlacklistService
from tests.unit.v2.conftest import FakeLLM, make_context, make_update, make_project

REPO_ROOT = Path(__file__).resolve().parents[3]

EXTRACTION_JSON = (
    '{"budget_min": 20000, "budget_max": 30000, "currency": "RUB",'
    ' "deadline_days": 14, "required_skills": ["python"],'
    ' "client_red_flags": [], "summary": "Бот записи"}'
)


class FakeAdapter(SourceAdapter):
    platform = Platform.KWORK

    def __init__(self, listings: List[RawListing]) -> None:
        self._listings = listings
        self.closed = False

    async def fetch(self) -> List[RawListing]:
        return self._listings

    async def close(self) -> None:
        self.closed = True


class NotifyRecorder:
    def __init__(self, fail: bool = False) -> None:
        self.sent: List[dict] = []
        self.fail = fail

    async def __call__(
        self, application: object, chat_id: int, text: str, markup: object = None
    ) -> bool:
        self.sent.append({"chat_id": chat_id, "text": text})
        return not self.fail


def _listing(external_id: str = "a-1") -> RawListing:
    return RawListing(
        source=Platform.KWORK,
        external_id=external_id,
        title="Нужен Telegram-бот для записи клиентов",
        description_raw="Запись, оплата, напоминания",
        budget_min=20000,
        budget_max=30000,
        client_rating=4.8,
        client_orders=10,
        proposals_count=3,
        posted_at=utcnow(),
    )


class TestExtractionOncePerListing:
    async def test_one_project_two_users_one_llm_call(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """AUDIT C-1 (§3.2): extraction runs once per LISTING, not per user."""
        second = User(
            telegram_id=555002,
            target_hourly_rate=1200,
            skills=["python"],
            subscription_tier=SubscriptionTier.TRIAL,
            subscription_expires_at=utcnow() + timedelta(days=7),
        )
        session.add(second)
        await session.flush()
        session.add(ExchangeConnection(user_id=user.id, platform=Platform.KWORK))
        session.add(ExchangeConnection(user_id=second.id, platform=Platform.KWORK))
        await session.commit()

        llm = FakeLLM([EXTRACTION_JSON])  # exactly ONE scripted response
        notify = NotifyRecorder()
        stats = await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[FakeAdapter([_listing()])],
            llm=llm,
            notify=notify,
            extraction_model="cheap",
            auto_llm=False,
        )
        assert stats.analyses == 2
        assert stats.notifications == 2
        assert len(llm.calls) == 1  # would raise inside FakeLLM on a 2nd call
        async with session_factory() as check:
            analyses = (
                (await check.execute(select(ProjectAnalysis))).scalars().all()
            )
        assert len(analyses) == 2
        assert {a.extracted_budget for a in analyses} == {30000}


class TestNotifyAccounting:
    async def test_failed_delivery_not_counted_but_persisted(
        self, session_factory, user, kwork_connection
    ) -> None:
        """AUDIT H-9: failed sends are counted as failures, data survives."""
        notify = NotifyRecorder(fail=True)
        stats = await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[FakeAdapter([_listing("n-1")])],
            llm=None,
            notify=notify,
            extraction_model="cheap",
            auto_llm=False,
        )
        assert stats.analyses == 1
        assert stats.notifications == 0
        assert stats.notify_failures == 1
        async with session_factory() as check:
            assert (
                len((await check.execute(select(ProjectAnalysis))).scalars().all())
                == 1
            )


class TestAdapterLifecycle:
    async def test_owned_adapters_closed_after_tick(
        self, session_factory, user, kwork_connection, monkeypatch
    ) -> None:
        """AUDIT H-2: worker-built adapters are closed even on success."""
        spy = FakeAdapter([_listing("c-1")])
        monkeypatch.setattr(worker_module, "build_adapters", lambda _: [spy])
        await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=None,  # worker owns and must close them
            llm=None,
            notify=NotifyRecorder(),
            extraction_model="cheap",
            auto_llm=False,
        )
        assert spy.closed is True

    async def test_injected_adapters_stay_open(
        self, session_factory, user, kwork_connection
    ) -> None:
        """Caller-owned adapters are the caller's responsibility."""
        spy = FakeAdapter([_listing("c-2")])
        await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[spy],
            llm=None,
            notify=NotifyRecorder(),
            extraction_model="cheap",
            auto_llm=False,
        )
        assert spy.closed is False


class TestCollectorConcurrencySafety:
    async def test_integrity_error_is_contained(
        self, session_factory, session: AsyncSession, monkeypatch
    ) -> None:
        """AUDIT C-3: a concurrent duplicate never kills the batch."""
        collector = Collector()
        await collector.collect(session, [_listing("dup-x")])
        await session.commit()

        # Simulate the check-then-insert race: exists-check misses the row.
        async def _always_false(self: Collector, s: AsyncSession, listing) -> bool:
            return False

        monkeypatch.setattr(Collector, "_exists_exact", _always_false)
        # Same (source, external_id) but text/budget differ enough to slip
        # past fuzzy dedup — only the DB constraint can catch it.
        racy_duplicate = RawListing(
            source=Platform.KWORK,
            external_id="dup-x",
            title="Совершенно другая задача: настроить рекламу",
            budget_min=90000,
        )
        fresh = RawListing(
            source=Platform.FL_RU,
            external_id="ok-1",
            title="Совсем другой заказ на дизайн логотипа",
            budget_min=7000,
        )
        result = await collector.collect(session, [racy_duplicate, fresh])
        await session.commit()
        assert result.duplicates_exact == 1  # loser handled via savepoint
        assert [p.external_id for p in result.new_projects] == ["ok-1"]

    async def test_analysis_unique_constraint(
        self, session_factory, session: AsyncSession, user, project
    ) -> None:
        """AUDIT C-3: DB forbids duplicate (project_id, user_id) analyses."""
        session.add(ProjectAnalysis(project_id=project.id, user_id=user.id))
        await session.commit()
        session.add(ProjectAnalysis(project_id=project.id, user_id=user.id))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async def test_exchange_partial_unique(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """AUDIT M-2: one Kwork per user; multiple TG channels allowed."""
        user_id = user.id  # rollback below expires ORM objects
        session.add(ExchangeConnection(user_id=user_id, platform=Platform.KWORK))
        await session.commit()
        session.add(ExchangeConnection(user_id=user_id, platform=Platform.KWORK))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        session.add(
            ExchangeConnection(
                user_id=user_id,
                platform=Platform.TG_CHANNEL,
                settings={"channel": "@a"},
            )
        )
        session.add(
            ExchangeConnection(
                user_id=user_id,
                platform=Platform.TG_CHANNEL,
                settings={"channel": "@b"},
            )
        )
        await session.commit()  # no conflict for channels


class TestUserCreationRace:
    async def test_loser_recovers_existing_row(
        self, session: AsyncSession, monkeypatch
    ) -> None:
        """AUDIT C-3: concurrent first touch converges on one user row."""
        from types import SimpleNamespace

        tg_user = SimpleNamespace(id=424243, username="racer")
        # The winner's row already exists...
        session.add(User(telegram_id=424243, username="racer"))
        await session.commit()

        # ...but the loser's SELECT ran before the winner committed.
        real_select = common_module._select_user
        calls = {"n": 0}

        async def racy_select(s: AsyncSession, telegram_id: int) -> Optional[User]:
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # race window: row not visible yet
            return await real_select(s, telegram_id)

        monkeypatch.setattr(common_module, "_select_user", racy_select)
        user, created = await common_module.get_or_create_user(session, tg_user)
        assert created is False
        assert user.telegram_id == 424243
        rows = (await session.execute(select(User))).scalars().all()
        assert len(rows) == 1


class TestDoubleTapSend:
    async def test_second_tap_from_draft_is_noop(
        self, session_factory, session: AsyncSession, user, portfolio, project
    ) -> None:
        """AUDIT C-4: double-tap «Отправлено» from DRAFT → one client, one reminder."""
        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="т"
        )
        session.add(proposal)
        await session.commit()

        first = make_update(callback_data=f"v2p:send:{proposal.id}")
        await proposal_send(first, make_context())
        second = make_update(callback_data=f"v2p:send:{proposal.id}")
        await proposal_send(second, make_context())

        assert "Уже" in second.callback_query.answer.await_args.args[0]
        async with session_factory() as check:
            clients = (await check.execute(select(Client))).scalars().all()
            reminders = (await check.execute(select(Reminder))).scalars().all()
            sent = await check.get(Proposal, proposal.id)
        assert len(clients) == 1
        assert len(reminders) == 1
        assert sent is not None and sent.status is ProposalStatus.SENT


class TestRemindersAtMostOnce:
    async def test_failed_delivery_never_repeats(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """AUDIT C-5 (§3.8): status commits BEFORE send — no re-ping ever."""
        from core import crm

        client = Client(user_id=user.id, name="К")
        session.add(client)
        await session.flush()
        reminder = await crm.schedule_reminder(
            session, client, due_at=utcnow() - timedelta(minutes=1), message="ping"
        )
        await session.commit()

        failing = NotifyRecorder(fail=True)
        delivered = await run_reminders_tick(
            None, session_factory=session_factory, notify=failing
        )
        assert delivered == 0
        assert len(failing.sent) == 1  # one attempt happened
        async with session_factory() as check:
            row = await check.get(Reminder, reminder.id)
        assert row is not None and row.status is ReminderStatus.NOTIFIED

        # Next tick: nothing to deliver, user is not pinged again.
        again = NotifyRecorder()
        assert (
            await run_reminders_tick(
                None, session_factory=session_factory, notify=again
            )
            == 0
        )
        assert again.sent == []


class TestChannelLimitEnforcedAtSave:
    async def test_delayed_text_cannot_bypass_limit(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """AUDIT M-2: the tariff limit is re-checked at save time."""
        user.subscription_tier = SubscriptionTier.BASIC
        for i in range(5):
            session.add(
                ExchangeConnection(
                    user_id=user.id,
                    platform=Platform.TG_CHANNEL,
                    settings={"channel": f"@ch{i}"},
                )
            )
        await session.commit()
        update = make_update(text="@sixth_channel")
        await add_channel_from_text(update, make_context(), "@sixth_channel")
        reply = update.message.reply_text.await_args.args[0]
        assert "Лимит" in reply
        async with session_factory() as check:
            rows = (
                (await check.execute(select(ExchangeConnection))).scalars().all()
            )
        assert len(rows) == 5

    async def test_duplicate_channel_rejected(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """AUDIT M-2: the same channel cannot be connected twice."""
        session.add(
            ExchangeConnection(
                user_id=user.id,
                platform=Platform.TG_CHANNEL,
                settings={"channel": "@orders"},
            )
        )
        await session.commit()
        update = make_update(text="t.me/orders")
        await add_channel_from_text(update, make_context(), "t.me/orders")
        assert "уже подключён" in update.message.reply_text.await_args.args[0]
        async with session_factory() as check:
            rows = (
                (await check.execute(select(ExchangeConnection))).scalars().all()
            )
        assert len(rows) == 1


class TestOwnershipAtFlowStart:
    async def test_edit_start_rejects_foreign_proposal(
        self, session_factory, session: AsyncSession, user, project
    ) -> None:
        """AUDIT M-7: forged callback ids are rejected at flow start."""
        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="т"
        )
        session.add(proposal)
        await session.commit()
        intruder = make_update(
            telegram_id=999123, callback_data=f"v2p:edit:{proposal.id}"
        )
        context = make_context()
        await proposal_edit_start(intruder, context)
        assert intruder.callback_query.answer.await_args.kwargs.get("show_alert")
        assert "v2_edit_proposal" not in context.user_data

    async def test_note_start_rejects_foreign_client(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """AUDIT M-7: same for CRM notes."""
        client = Client(user_id=user.id, name="К")
        session.add(client)
        await session.commit()
        intruder = make_update(
            telegram_id=999124, callback_data=f"v2c:note:{client.id}"
        )
        context = make_context()
        await client_note_start(intruder, context)
        assert intruder.callback_query.answer.await_args.kwargs.get("show_alert")
        assert "v2_note_client" not in context.user_data


class TestLegacyBugFixes:
    def test_filter_reason_str_is_value(self) -> None:
        """AUDIT H-4: str(str-Enum) must be the value on Python 3.11."""
        assert str(FilterReason.BUDGET_TOO_LOW) == "budget_too_low"
        assert f"{FilterReason.BUDGET_TOO_HIGH} (x)" == "budget_too_high (x)"

    async def test_blacklist_survives_uninitialized_db(self, tmp_path: Path) -> None:
        """AUDIT H-5: missing table degrades to 'not blacklisted', no crash."""
        empty_db = tmp_path / "empty.db"
        sqlite3.connect(empty_db).close()
        service = BlacklistService(str(empty_db))
        assert await service.is_blacklisted("vacancy", "x") is False


class TestHealthcheckScript:
    def _run(self, db_path: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "healthcheck.py")],
            env={**os.environ, "DB_PATH": db_path},
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=30,
        )

    def test_healthy_db_exits_zero(self, tmp_path: Path) -> None:
        """AUDIT H-1: the check must actually pass on a healthy database."""
        db = tmp_path / "ok.db"
        sqlite3.connect(db).close()
        result = self._run(str(db))
        assert result.returncode == 0, result.stdout + result.stderr

    def test_unreachable_db_exits_nonzero(self, tmp_path: Path) -> None:
        """...and fail cleanly (no traceback exit) when the DB is unreachable."""
        result = self._run(str(tmp_path / "no_such_dir" / "x.db"))
        assert result.returncode == 1, result.stdout + result.stderr


class TestCardsUrlScheme:
    def test_non_http_url_not_rendered(self, user) -> None:
        """AUDIT M-3: exotic schemes must not break Telegram delivery."""
        from bot.handlers.v2.cards import project_card

        bad = make_project(external_id="u-1")
        bad.url = "javascript:alert(1)"
        assert "<a href" not in project_card(bad, None)

        good = make_project(external_id="u-2")
        assert "<a href" in project_card(good, None)


class TestSchedulerResilience:
    def test_jobs_tolerate_lateness(self) -> None:
        """AUDIT M-4: late ticks run (grace) instead of silently dropping."""
        from monitoring.worker import JOB_MISFIRE_GRACE_SECONDS, register_v2_jobs

        class FakeScheduler:
            def __init__(self) -> None:
                self.jobs: List[dict] = []

            def add_job(self, *args: object, **kwargs: object) -> None:
                self.jobs.append(kwargs)

        scheduler = FakeScheduler()
        register_v2_jobs(scheduler, application=None)  # type: ignore[arg-type]
        for job in scheduler.jobs:
            assert job["misfire_grace_time"] == JOB_MISFIRE_GRACE_SECONDS
            assert job["coalesce"] is True
            assert job["max_instances"] == 1


class TestStartupSequence:
    def test_migrations_preserve_event_loop(self, tmp_path, monkeypatch) -> None:
        """REVIEW #1: alembic's asyncio.run must not kill the caller's loop.

        Reproduces the production startup sequence: create loop →
        run_v2_migrations() → APScheduler start on the current loop. Before
        the fix this crashed with "There is no current event loop".
        """
        import asyncio

        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from config import get_config
        from core.db import run_v2_migrations

        monkeypatch.setattr(
            get_config(),
            "DATABASE_URL",
            f"sqlite+aiosqlite:///{tmp_path}/startup.db",
        )
        monkeypatch.delenv("DATABASE_URL", raising=False)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            run_v2_migrations()
            # The caller's loop must still be the current one...
            assert asyncio.get_event_loop() is loop
            # ...and the scheduler must be able to bind to it (main.py:254).
            scheduler = AsyncIOScheduler()
            scheduler.start(paused=True)
            scheduler.shutdown(wait=False)
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def test_migrated_db_has_full_schema(self, tmp_path, monkeypatch) -> None:
        """The startup migration path produces the complete V2 schema."""
        from config import get_config
        from core.db import run_v2_migrations

        db_path = tmp_path / "schema.db"
        monkeypatch.setattr(
            get_config(), "DATABASE_URL", f"sqlite+aiosqlite:///{db_path}"
        )
        monkeypatch.delenv("DATABASE_URL", raising=False)
        run_v2_migrations()
        conn = sqlite3.connect(db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        assert "alembic_version" in tables  # future upgrades apply cleanly
        assert {"users", "projects", "project_analyses", "clients"} <= tables


class TestAtomicClaimMechanism:
    async def test_second_claim_matches_zero_rows(
        self, session_factory, session: AsyncSession, user, project
    ) -> None:
        """REVIEW #4: pin the DB-level claim, not just the handler guard.

        Two racing sessions both attempt DRAFT→SENT; the UPDATE ... WHERE
        status != 'sent' must award exactly one winner (rowcount 1 then 0).
        """
        from sqlalchemy import update as sa_update

        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="т"
        )
        session.add(proposal)
        await session.commit()
        proposal_id = proposal.id

        def _claim():
            return (
                sa_update(Proposal)
                .where(
                    Proposal.id == proposal_id,
                    Proposal.status != ProposalStatus.SENT,
                )
                .values(status=ProposalStatus.SENT, sent_at=utcnow())
                .execution_options(synchronize_session=False)
            )

        async with session_factory() as first:
            winner = await first.execute(_claim())
            await first.commit()
        async with session_factory() as second:
            loser = await second.execute(_claim())
            await second.commit()
        assert winner.rowcount == 1
        assert loser.rowcount == 0


class TestSourceAddRace:
    async def test_integrity_error_answered_not_raised(
        self, session_factory, session, user, monkeypatch
    ) -> None:
        """REVIEW #3: the double-tap loser gets an alert, not a traceback.

        Simulates the true race window: the handler's duplicate check runs
        BEFORE the winner's commit becomes visible, so the loser reaches the
        INSERT and only the partial unique index can stop it — the handler
        must answer politely instead of leaking IntegrityError.
        """
        from bot.handlers.v2 import sources as sources_module
        from bot.handlers.v2.sources import source_add

        # The winner's row is already committed...
        session.add(ExchangeConnection(user_id=user.id, platform=Platform.KWORK))
        await session.commit()

        # ...but the loser's connection listing ran before that commit.
        async def _sees_nothing(s: object, user_id: int) -> list:
            return []

        monkeypatch.setattr(sources_module, "_load_connections", _sees_nothing)
        update = make_update(callback_data="v2s:add:kwork")
        await source_add(update, make_context())  # must not raise

        answer_args = update.callback_query.answer.await_args
        assert "уже подключён" in answer_args.args[0]
        assert answer_args.kwargs.get("show_alert") is True
        async with session_factory() as check:
            rows = (
                (await check.execute(select(ExchangeConnection))).scalars().all()
            )
        assert len(rows) == 1  # no duplicate row was created
