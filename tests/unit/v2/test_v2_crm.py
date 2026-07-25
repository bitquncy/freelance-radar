"""CRM tests — §3.7 funnel diagram, §3.8 reminders."""
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import crm
from core.models import (
    Client,
    Interaction,
    InteractionType,
    PipelineStage,
    Proposal,
    Reminder,
    ReminderStatus,
    utcnow,
)


class TestFunnel:
    def test_diagram_edges_allowed(self) -> None:
        """Every edge from the §3.7 mermaid diagram is allowed."""
        edges = [
            (PipelineStage.NEW_LEAD, PipelineStage.PROPOSAL_SENT),
            (PipelineStage.PROPOSAL_SENT, PipelineStage.NEGOTIATION),
            (PipelineStage.NEGOTIATION, PipelineStage.WON),
            (PipelineStage.NEGOTIATION, PipelineStage.LOST),
            (PipelineStage.WON, PipelineStage.IN_PROGRESS),
            (PipelineStage.IN_PROGRESS, PipelineStage.COMPLETED),
            (PipelineStage.COMPLETED, PipelineStage.REPEAT_CLIENT),
            (PipelineStage.REPEAT_CLIENT, PipelineStage.NEW_LEAD),
        ]
        for current, target in edges:
            assert crm.can_transition(current, target), f"{current}->{target}"

    def test_shortcuts_forbidden(self) -> None:
        """Moves not present in the diagram are rejected."""
        assert not crm.can_transition(
            PipelineStage.NEW_LEAD, PipelineStage.WON
        )
        assert not crm.can_transition(
            PipelineStage.PROPOSAL_SENT, PipelineStage.COMPLETED
        )
        assert not crm.can_transition(PipelineStage.LOST, PipelineStage.NEW_LEAD)

    async def test_change_stage_logs_and_validates(
        self, session: AsyncSession, user
    ) -> None:
        """Valid moves log an interaction; invalid moves raise."""
        client = Client(user_id=user.id, name="К")
        session.add(client)
        await session.flush()

        await crm.change_stage(session, client, PipelineStage.PROPOSAL_SENT)
        assert client.pipeline_stage is PipelineStage.PROPOSAL_SENT
        events = (await session.execute(select(Interaction))).scalars().all()
        assert any("Этап" in e.content for e in events)

        with pytest.raises(crm.TransitionError):
            await crm.change_stage(session, client, PipelineStage.COMPLETED)

    async def test_negotiation_schedules_follow_up(
        self, session: AsyncSession, user
    ) -> None:
        """§3.8: entering negotiations arms the 24h reminder."""
        client = Client(
            user_id=user.id, name="К", pipeline_stage=PipelineStage.PROPOSAL_SENT
        )
        session.add(client)
        await session.flush()
        now = utcnow()
        await crm.change_stage(
            session, client, PipelineStage.NEGOTIATION, now=now
        )
        reminder = (await session.execute(select(Reminder))).scalars().one()
        assert reminder.due_at == now + crm.REMINDER_NEGOTIATION


class TestProposalToCrm:
    async def test_upsert_creates_client_and_reminder(
        self, session: AsyncSession, user, project
    ) -> None:
        """Sending a proposal auto-creates the card + 48h reminder (§3.7–3.8)."""
        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="t"
        )
        session.add(proposal)
        await session.flush()
        now = utcnow()
        client = await crm.upsert_client_for_proposal(
            session, user, project, proposal, now=now
        )
        assert client.pipeline_stage is PipelineStage.PROPOSAL_SENT
        assert client.last_contact_at == now
        reminder = (await session.execute(select(Reminder))).scalars().one()
        assert reminder.due_at == now + crm.REMINDER_AFTER_PROPOSAL
        events = (await session.execute(select(Interaction))).scalars().all()
        assert any(e.type is InteractionType.MESSAGE for e in events)

    async def test_upsert_reuses_existing_client(
        self, session: AsyncSession, user, project
    ) -> None:
        """Second proposal to the same order reuses the card."""
        first = Proposal(project_id=project.id, user_id=user.id, generated_text="1")
        second = Proposal(project_id=project.id, user_id=user.id, generated_text="2")
        session.add_all([first, second])
        await session.flush()
        client_a = await crm.upsert_client_for_proposal(
            session, user, project, first
        )
        client_b = await crm.upsert_client_for_proposal(
            session, user, project, second
        )
        assert client_a.id == client_b.id
        clients = (await session.execute(select(Client))).scalars().all()
        assert len(clients) == 1

    async def test_upsert_without_reminder_for_basic(
        self, session: AsyncSession, user, project
    ) -> None:
        """§7: Basic has no reminders — none scheduled."""
        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="t"
        )
        session.add(proposal)
        await session.flush()
        await crm.upsert_client_for_proposal(
            session, user, project, proposal, with_reminder=False
        )
        assert (await session.execute(select(Reminder))).scalars().all() == []

    async def test_active_clients_count(
        self, session: AsyncSession, user
    ) -> None:
        """Only active funnel stages count toward the §7 limit."""
        session.add_all(
            [
                Client(user_id=user.id, name="a"),
                Client(
                    user_id=user.id,
                    name="b",
                    pipeline_stage=PipelineStage.LOST,
                ),
                Client(
                    user_id=user.id,
                    name="c",
                    pipeline_stage=PipelineStage.COMPLETED,
                ),
                Client(
                    user_id=user.id,
                    name="d",
                    pipeline_stage=PipelineStage.IN_PROGRESS,
                ),
            ]
        )
        await session.flush()
        assert await crm.count_active_clients(session, user.id) == 2


class TestReminders:
    async def test_due_notified_snoozed_done_lifecycle(
        self, session: AsyncSession, user
    ) -> None:
        """§3.8: notify once → user snoozes or completes."""
        client = Client(user_id=user.id, name="К")
        session.add(client)
        await session.flush()
        now = utcnow()
        reminder = await crm.schedule_reminder(
            session, client, due_at=now - timedelta(minutes=1), message="ping"
        )
        future = await crm.schedule_reminder(
            session, client, due_at=now + timedelta(hours=5), message="later"
        )

        due = await crm.find_due_reminders(session, now=now)
        assert [r.id for r in due] == [reminder.id]

        await crm.mark_notified(session, reminder)
        assert await crm.find_due_reminders(session, now=now) == []

        await crm.snooze_reminder(session, reminder, now=now)
        assert reminder.status is ReminderStatus.PENDING
        assert reminder.due_at == now + crm.SNOOZE_DEFAULT

        await crm.complete_reminder(session, reminder)
        assert reminder.status is ReminderStatus.DONE
        assert future.status is ReminderStatus.PENDING
