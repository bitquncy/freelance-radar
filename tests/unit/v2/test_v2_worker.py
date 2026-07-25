"""Worker pipeline tests — §4.1/§6.2: fetch → collect → analyze → notify."""
from datetime import timedelta
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import crm
from core.models import (
    Client,
    ExchangeConnection,
    Platform,
    Project,
    ProjectAnalysis,
    Reminder,
    ReminderStatus,
    SubscriptionTier,
    utcnow,
)
from monitoring.adapters.base import RawListing, SourceAdapter
from monitoring.worker import (
    analyze_project_for_user,
    build_adapters,
    connection_matches_project,
    run_radar_tick,
    run_reminders_tick,
)
from tests.unit.v2.conftest import FakeLLM, make_project

EXTRACTION_JSON = (
    '{"budget_min": 20000, "budget_max": 30000, "currency": "RUB",'
    ' "deadline_days": 14, "required_skills": ["python"],'
    ' "client_red_flags": [], "summary": "Бот записи"}'
)


class FakeAdapter(SourceAdapter):
    platform = Platform.KWORK

    def __init__(self, listings: List[RawListing]) -> None:
        self._listings = listings

    async def fetch(self) -> List[RawListing]:
        return self._listings


class BrokenAdapter(SourceAdapter):
    platform = Platform.FL_RU

    async def fetch(self) -> List[RawListing]:
        raise ConnectionError("source down")


class NotifyRecorder:
    def __init__(self) -> None:
        self.sent: List[dict] = []

    async def __call__(
        self, application: object, chat_id: int, text: str, markup: object = None
    ) -> None:
        self.sent.append({"chat_id": chat_id, "text": text, "markup": markup})


def _listing(external_id: str = "w-1") -> RawListing:
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


class TestHelpers:
    def test_build_adapters_from_connections(self, user) -> None:
        """Adapter set mirrors the platforms users connected."""
        connections = [
            ExchangeConnection(user_id=1, platform=Platform.KWORK),
            ExchangeConnection(
                user_id=1,
                platform=Platform.TG_CHANNEL,
                settings={"channel": "@orders"},
            ),
        ]
        adapters = build_adapters(connections)
        platforms = {a.platform for a in adapters}
        assert platforms == {Platform.KWORK, Platform.TG_CHANNEL}

    def test_connection_matching(self) -> None:
        """Platform must match; TG requires the exact channel."""
        kwork_conn = ExchangeConnection(user_id=1, platform=Platform.KWORK)
        project = make_project()
        assert connection_matches_project(kwork_conn, project)

        tg_conn = ExchangeConnection(
            user_id=1,
            platform=Platform.TG_CHANNEL,
            settings={"channel": "@orders"},
        )
        tg_project = make_project(
            external_id="t1",
            source=Platform.TG_CHANNEL,
            raw_payload={"channel": "@orders"},
        )
        other_channel = make_project(
            external_id="t2",
            source=Platform.TG_CHANNEL,
            raw_payload={"channel": "@another"},
        )
        assert connection_matches_project(tg_conn, tg_project)
        assert not connection_matches_project(tg_conn, other_channel)
        assert not connection_matches_project(tg_conn, project)


class TestAnalyze:
    async def test_llm_extraction_path(
        self, session: AsyncSession, user, project
    ) -> None:
        """LLM extraction feeds scoring; analysis is persisted."""
        analysis = await analyze_project_for_user(
            session, project, user, FakeLLM([EXTRACTION_JSON]), "cheap-model"
        )
        await session.commit()
        assert analysis.extracted_budget == 30000
        assert analysis.extracted_skills == ["python"]
        assert analysis.win_probability is not None
        assert analysis.profitability_index is not None

    async def test_no_llm_fallback_path(
        self, session: AsyncSession, user, project
    ) -> None:
        """MVP no-LLM mode: parser budgets + heuristic scoring (§14 MVP)."""
        analysis = await analyze_project_for_user(
            session, project, user, None, "unused"
        )
        assert analysis.extracted_budget == 30000
        assert analysis.win_probability is not None


class TestRadarTick:
    async def test_full_tick_analyzes_and_notifies(
        self, session_factory, user, kwork_connection
    ) -> None:
        """New listing → project → analysis → user notification."""
        notify = NotifyRecorder()
        stats = await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[FakeAdapter([_listing()])],
            llm=FakeLLM([EXTRACTION_JSON]),
            notify=notify,
            extraction_model="cheap",
            auto_llm=False,
        )
        assert stats.listings_fetched == 1
        assert stats.new_projects == 1
        assert stats.analyses == 1
        assert stats.notifications == 1
        assert notify.sent[0]["chat_id"] == user.telegram_id
        assert "Вероятность" in notify.sent[0]["text"]

        async with session_factory() as session:
            projects = (await session.execute(select(Project))).scalars().all()
            analyses = (
                (await session.execute(select(ProjectAnalysis))).scalars().all()
            )
        assert len(projects) == 1
        assert len(analyses) == 1

    async def test_second_tick_is_idempotent(
        self, session_factory, user, kwork_connection
    ) -> None:
        """The same listing on the next tick creates nothing new."""
        adapter = FakeAdapter([_listing()])
        notify = NotifyRecorder()
        await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[adapter],
            llm=FakeLLM([EXTRACTION_JSON]),
            notify=notify,
            extraction_model="cheap",
            auto_llm=False,
        )
        stats = await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[adapter],
            llm=FakeLLM([]),
            notify=notify,
            extraction_model="cheap",
            auto_llm=False,
        )
        assert stats.new_projects == 0
        assert stats.analyses == 0
        assert len(notify.sent) == 1

    async def test_broken_adapter_is_isolated(
        self, session_factory, user, kwork_connection
    ) -> None:
        """§3.1: one failing source never kills the tick."""
        notify = NotifyRecorder()
        stats = await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[BrokenAdapter(), FakeAdapter([_listing("w-9")])],
            llm=FakeLLM([EXTRACTION_JSON]),
            notify=notify,
            extraction_model="cheap",
            auto_llm=False,
        )
        assert stats.new_projects == 1
        assert len(stats.errors) == 1

    async def test_quota_enforced_for_basic(
        self, session_factory, session: AsyncSession, user, kwork_connection
    ) -> None:
        """§7: Basic — 50 анализов/мес; 51-й скипается."""
        user.subscription_tier = SubscriptionTier.BASIC
        for i in range(50):
            project = make_project(
                external_id=f"old-{i}",
                title=f"Старый заказ №{i}: дизайн логотипа и айдентика",
                budget_min=5000 + i,
                budget_max=None,
            )
            session.add(project)
            await session.flush()
            session.add(
                ProjectAnalysis(project_id=project.id, user_id=user.id)
            )
        await session.commit()

        notify = NotifyRecorder()
        stats = await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[FakeAdapter([_listing("fresh-1")])],
            llm=None,
            notify=notify,
            extraction_model="cheap",
            auto_llm=False,
        )
        assert stats.new_projects == 1
        assert stats.analyses == 0
        assert stats.skipped_quota == 1
        assert notify.sent == []

    async def test_expired_subscription_gets_nothing(
        self, session_factory, session: AsyncSession, user, kwork_connection
    ) -> None:
        """Expired tier → no analysis, no notification."""
        user.subscription_expires_at = utcnow() - timedelta(days=1)
        await session.commit()
        notify = NotifyRecorder()
        stats = await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[FakeAdapter([_listing("x-1")])],
            llm=None,
            notify=notify,
            extraction_model="cheap",
            auto_llm=False,
        )
        assert stats.analyses == 0
        assert notify.sent == []

    async def test_no_connections_no_work(self, session_factory, user) -> None:
        """Without connections the tick exits immediately."""
        stats = await run_radar_tick(
            None,
            session_factory=session_factory,
            adapters=[FakeAdapter([_listing()])],
            llm=None,
            auto_llm=False,
        )
        assert stats.listings_fetched == 0


class TestRemindersTick:
    async def test_due_reminder_notified_once(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """§3.8: deliver with action buttons, mark NOTIFIED, no repeats."""
        client = Client(user_id=user.id, name="Клиент")
        session.add(client)
        await session.flush()
        reminder = await crm.schedule_reminder(
            session, client, due_at=utcnow() - timedelta(minutes=5), message="ping"
        )
        await session.commit()

        notify = NotifyRecorder()
        delivered = await run_reminders_tick(
            None, session_factory=session_factory, notify=notify
        )
        assert delivered == 1
        assert "Напоминание" in notify.sent[0]["text"]

        async with session_factory() as check:
            row = await check.get(Reminder, reminder.id)
            assert row is not None and row.status is ReminderStatus.NOTIFIED

        assert (
            await run_reminders_tick(
                None, session_factory=session_factory, notify=notify
            )
            == 0
        )

    async def test_basic_tier_reminder_dropped(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """§7: reminders are Pro+ — Basic users are not pinged."""
        user.subscription_tier = SubscriptionTier.BASIC
        client = Client(user_id=user.id, name="Клиент")
        session.add(client)
        await session.flush()
        await crm.schedule_reminder(
            session, client, due_at=utcnow() - timedelta(minutes=5), message="ping"
        )
        await session.commit()

        notify = NotifyRecorder()
        delivered = await run_reminders_tick(
            None, session_factory=session_factory, notify=notify
        )
        assert delivered == 0
        assert notify.sent == []
