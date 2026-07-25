"""CRM handler tests + card rendering + registration wiring."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.v2.cards import (
    client_card,
    project_card,
    proposal_card,
    reminder_card,
)
from bot.handlers.v2.crm_handlers import (
    client_note_start,
    client_stage,
    client_view,
    clients_list,
    reminder_snooze,
    reminder_write,
)
from bot.handlers.v2.router import v2_text_router
from core import crm
from core.models import (
    Client,
    Interaction,
    PipelineStage,
    Project,
    ProjectAnalysis,
    Proposal,
    ProposalMode,
    ProposalStatus,
    Reminder,
    ReminderStatus,
    utcnow,
)
from tests.unit.v2.conftest import make_context, make_update


async def _client(session: AsyncSession, user, **kwargs: object) -> Client:
    row = Client(user_id=user.id, name="Заказчик из теста", **kwargs)
    session.add(row)
    await session.commit()
    return row


class TestClientsList:
    async def test_empty_list_message(self, session_factory, user) -> None:
        """Empty CRM explains where clients come from."""
        update = make_update(text="/clients")
        await clients_list(update, make_context())
        text = update.message.reply_text.await_args.args[0]
        assert "Пока пусто" in text

    async def test_list_counts_active(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """Active vs total counters rendered."""
        await _client(session, user)
        await _client(session, user, pipeline_stage=PipelineStage.LOST)
        update = make_update(text="/clients")
        await clients_list(update, make_context())
        text = update.message.reply_text.await_args.args[0]
        assert "активных: 1 из 2" in text

    async def test_callback_path_edits_message(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """«👥 Клиенты» button edits in place."""
        await _client(session, user)
        update = make_update(callback_data="v2c:list")
        await clients_list(update, make_context())
        assert update.callback_query.edit_message_text.await_count == 1


class TestClientCardFlow:
    async def test_view_renders_card(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """Card shows stage and recent interactions."""
        client = await _client(session, user)
        await crm.log_interaction(
            session, client, crm.InteractionType.NOTE, "первая заметка"
        )
        await session.commit()
        update = make_update(callback_data=f"v2c:view:{client.id}")
        await client_view(update, make_context())
        text = update.callback_query.edit_message_text.await_args.args[0]
        assert "Заказчик из теста" in text
        assert "первая заметка" in text

    async def test_view_foreign_client_denied(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """Other users' clients are invisible."""
        client = await _client(session, user)
        update = make_update(
            telegram_id=999999, callback_data=f"v2c:view:{client.id}"
        )
        await client_view(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")

    async def test_stage_transition_valid(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """new_lead → proposal_sent via button."""
        client = await _client(session, user)
        update = make_update(
            callback_data=f"v2c:stage:{client.id}:proposal_sent"
        )
        await client_stage(update, make_context())
        async with session_factory() as check:
            row = await check.get(Client, client.id)
        assert row is not None
        assert row.pipeline_stage is PipelineStage.PROPOSAL_SENT

    async def test_stage_transition_invalid_alerts(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """§3.7: forbidden move → alert, stage unchanged."""
        client = await _client(session, user)
        update = make_update(callback_data=f"v2c:stage:{client.id}:completed")
        await client_stage(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")
        async with session_factory() as check:
            row = await check.get(Client, client.id)
        assert row is not None
        assert row.pipeline_stage is PipelineStage.NEW_LEAD

    async def test_note_flow_via_router(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """📝 Заметка → text router stores the note + interaction."""
        client = await _client(session, user)
        context = make_context()
        update = make_update(callback_data=f"v2c:note:{client.id}")
        await client_note_start(update, context)
        assert context.user_data["v2_note_client"] == client.id

        text_update = make_update(text="Просил перезвонить в понедельник")
        await v2_text_router(text_update, context)
        async with session_factory() as check:
            row = await check.get(Client, client.id)
            events = (await check.execute(select(Interaction))).scalars().all()
        assert row is not None
        assert "перезвонить" in row.notes
        assert any("перезвонить" in e.content for e in events)


class TestReminderCallbacks:
    async def _reminder(
        self, session: AsyncSession, user
    ) -> "tuple[Client, Reminder]":
        client = await _client(session, user)
        reminder = await crm.schedule_reminder(
            session, client, due_at=utcnow() - timedelta(minutes=1), message="ping"
        )
        await session.commit()
        return client, reminder

    async def test_snooze_postpones(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """⏳ Отложить: due_at moves ~24h forward, card deleted."""
        client, reminder = await self._reminder(session, user)
        update = make_update(callback_data=f"v2r:snooze:{reminder.id}")
        await reminder_snooze(update, make_context())
        async with session_factory() as check:
            row = await check.get(Reminder, reminder.id)
        assert row is not None
        assert row.due_at > utcnow() + timedelta(hours=23)
        update.callback_query.message.delete.assert_awaited()

    async def test_write_now_completes_and_opens_card(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """✍️ Написать сейчас: reminder done, card opened, no auto-message."""
        client, reminder = await self._reminder(session, user)
        update = make_update(
            callback_data=f"v2r:write:{reminder.id}:{client.id}"
        )
        await reminder_write(update, make_context())
        async with session_factory() as check:
            row = await check.get(Reminder, reminder.id)
        assert row is not None
        assert row.status is ReminderStatus.DONE
        text = update.callback_query.edit_message_text.await_args.args[0]
        assert "написать клиенту" in text


class TestCards:
    def test_project_card_variants(self, user) -> None:
        """Score, traffic light, red flags and manual-review mark render."""
        from core.models import Platform

        project = Project(
            source=Platform.KWORK,
            external_id="c-1",
            title="Нужен бот <b>",
            budget_min=20000,
            budget_max=30000,
            url="https://kwork.ru/projects/1",
        )
        analysis = ProjectAnalysis(
            project_id=1,
            win_probability=72.0,
            profitability_index=1.5,
            effective_hourly_rate=2200.0,
            net_payout=22000.0,
            client_red_flags=["нулевой рейтинг"],
            summary="Бот записи",
        )
        text = project_card(project, analysis)
        assert "72%" in text
        assert "\U0001f7e2" in text  # green light
        assert "нулевой рейтинг" in text
        assert "&lt;b&gt;" in text  # HTML escaped

        flagged = ProjectAnalysis(project_id=1, needs_manual_review=True)
        text2 = project_card(project, flagged)
        assert "Требует ручной проверки" in text2

    def test_proposal_and_reminder_and_client_cards(self, user) -> None:
        """Proposal warnings, reminder text and client card render."""
        proposal = Proposal(
            project_id=1,
            user_id=1,
            generated_text="Текст",
            status=ProposalStatus.DRAFT,
            mode=ProposalMode.AI,
            violations=["length: 10 слов — меньше 80"],
        )
        text = proposal_card(proposal)
        assert "Черновик" in text
        assert "Проверьте перед отправкой" in text

        client = Client(
            user_id=1,
            name="Иван",
            pipeline_stage=PipelineStage.NEGOTIATION,
            notes="тёплый лид",
        )
        reminder = Reminder(client_id=1, due_at=utcnow(), message="Напомнить")
        assert "Напоминание" in reminder_card(client, reminder)
        card = client_card(client, ["событие 1"])
        assert "Иван" in card and "событие 1" in card


class TestRegistration:
    def test_register_v2_handlers_attaches_group_5(self) -> None:
        """All V2 handlers land in a non-legacy group."""
        from telegram.ext import Application

        from bot.handlers.v2 import HANDLER_GROUP, register_v2_handlers

        application = (
            Application.builder().token("123456:TEST-token").build()
        )
        register_v2_handlers(application)
        assert HANDLER_GROUP in application.handlers
        assert len(application.handlers[HANDLER_GROUP]) >= 15
        assert 0 not in application.handlers  # legacy group untouched

    def test_register_v2_jobs_uses_legacy_cadence(self) -> None:
        """§12.7: V2 tick reuses MONITOR_INTERVAL_MINUTES, never faster."""
        from config import get_config
        from monitoring.worker import register_v2_jobs

        class FakeScheduler:
            def __init__(self) -> None:
                self.jobs: list = []

            def add_job(self, *args: object, **kwargs: object) -> None:
                self.jobs.append(kwargs)

        scheduler = FakeScheduler()
        register_v2_jobs(scheduler, application=None)  # type: ignore[arg-type]
        tick = next(j for j in scheduler.jobs if j["id"] == "v2_radar_tick")
        assert tick["minutes"] == get_config().MONITOR_INTERVAL_MINUTES
        assert any(j["id"] == "v2_reminders_tick" for j in scheduler.jobs)
