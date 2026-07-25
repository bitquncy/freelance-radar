"""CRM funnel, interactions and reminders — AGENTS.md §3.7–3.8.

The funnel transitions mirror the §3.7 diagram exactly. Reminders follow
§3.8 defaults: 48h after a proposal, 24h after the last message in
negotiations; the system never messages the client on its own.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Set

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Client,
    Interaction,
    InteractionType,
    PipelineStage,
    Project,
    Proposal,
    Reminder,
    ReminderStatus,
    User,
    utcnow,
)

# §3.7 diagram, edge for edge.
ALLOWED_TRANSITIONS: Dict[PipelineStage, Set[PipelineStage]] = {
    PipelineStage.NEW_LEAD: {PipelineStage.PROPOSAL_SENT},
    PipelineStage.PROPOSAL_SENT: {PipelineStage.NEGOTIATION},
    PipelineStage.NEGOTIATION: {PipelineStage.WON, PipelineStage.LOST},
    PipelineStage.WON: {PipelineStage.IN_PROGRESS},
    PipelineStage.IN_PROGRESS: {PipelineStage.COMPLETED},
    PipelineStage.COMPLETED: {PipelineStage.REPEAT_CLIENT},
    PipelineStage.REPEAT_CLIENT: {PipelineStage.NEW_LEAD},
    PipelineStage.LOST: set(),
}

#: Stages counted against the Basic tier's "15 активных клиентов" limit (§7).
ACTIVE_STAGES: Set[PipelineStage] = {
    PipelineStage.NEW_LEAD,
    PipelineStage.PROPOSAL_SENT,
    PipelineStage.NEGOTIATION,
    PipelineStage.WON,
    PipelineStage.IN_PROGRESS,
    PipelineStage.REPEAT_CLIENT,
}

STAGE_TITLES: Dict[PipelineStage, str] = {
    PipelineStage.NEW_LEAD: "Новый лид",
    PipelineStage.PROPOSAL_SENT: "Отклик отправлен",
    PipelineStage.NEGOTIATION: "Переговоры",
    PipelineStage.WON: "Заказ получен",
    PipelineStage.LOST: "Отказ",
    PipelineStage.IN_PROGRESS: "В работе",
    PipelineStage.COMPLETED: "Завершён",
    PipelineStage.REPEAT_CLIENT: "Повторный клиент",
}

REMINDER_AFTER_PROPOSAL = timedelta(hours=48)
REMINDER_NEGOTIATION = timedelta(hours=24)
SNOOZE_DEFAULT = timedelta(hours=24)


class TransitionError(Exception):
    """Raised on a funnel transition not allowed by §3.7."""


def can_transition(current: PipelineStage, target: PipelineStage) -> bool:
    """Check whether a funnel transition is allowed (§3.7)."""
    return target in ALLOWED_TRANSITIONS.get(current, set())


def allowed_next_stages(current: PipelineStage) -> List[PipelineStage]:
    """List allowed next stages for UI buttons."""
    return sorted(ALLOWED_TRANSITIONS.get(current, set()), key=lambda s: s.value)


async def count_active_clients(session: AsyncSession, user_id: int) -> int:
    """Count clients in active funnel stages for tariff gating (§7)."""
    result = await session.execute(
        select(Client).where(
            Client.user_id == user_id,
            Client.pipeline_stage.in_(list(ACTIVE_STAGES)),
        )
    )
    return len(result.scalars().all())


async def log_interaction(
    session: AsyncSession,
    client: Client,
    interaction_type: InteractionType,
    content: str,
    touch_contact: bool = False,
    now: Optional[datetime] = None,
) -> Interaction:
    """Record an interaction; optionally update ``last_contact_at``."""
    interaction = Interaction(
        client_id=client.id, type=interaction_type, content=content
    )
    session.add(interaction)
    if touch_contact:
        client.last_contact_at = now or utcnow()
    await session.flush()
    return interaction


async def change_stage(
    session: AsyncSession,
    client: Client,
    target: PipelineStage,
    now: Optional[datetime] = None,
) -> Client:
    """Move a client through the funnel, enforcing §3.7 transitions.

    Entering negotiations schedules the 24h follow-up reminder (§3.8).

    Raises:
        TransitionError: If the transition is not allowed.
    """
    if not can_transition(client.pipeline_stage, target):
        raise TransitionError(
            f"Переход {client.pipeline_stage.value} → {target.value} не разрешён"
        )
    old = client.pipeline_stage
    client.pipeline_stage = target
    await log_interaction(
        session,
        client,
        InteractionType.NOTE,
        f"Этап: {STAGE_TITLES[old]} → {STAGE_TITLES[target]}",
    )
    if target is PipelineStage.NEGOTIATION:
        await schedule_reminder(
            session,
            client,
            due_at=(now or utcnow()) + REMINDER_NEGOTIATION,
            message="Клиент молчит в переговорах — пора написать.",
        )
    await session.flush()
    return client


async def upsert_client_for_proposal(
    session: AsyncSession,
    user: User,
    project: Project,
    proposal: Proposal,
    now: Optional[datetime] = None,
    with_reminder: bool = True,
) -> Client:
    """Create/update the client card when a proposal is sent (§3.7).

    The card is keyed by ``platform_client_id`` (per-project fallback key when
    the source exposes no client identity — MVP limitation, documented).
    ``with_reminder=False`` skips the 48h follow-up for tariffs without
    reminders (§7: Basic).
    """
    moment = now or utcnow()
    platform_client_id = f"{project.source.value}:{project.external_id}"

    async def _find() -> Optional[Client]:
        result = await session.execute(
            select(Client).where(
                Client.user_id == user.id,
                Client.platform_client_id == platform_client_id,
            )
        )
        return result.scalar_one_or_none()

    client = await _find()
    if client is None:
        # Savepoint + retry: a concurrent send of the same proposal must
        # converge on ONE card (unique user_id+platform_client_id).
        try:
            async with session.begin_nested():
                client = Client(
                    user_id=user.id,
                    platform_client_id=platform_client_id,
                    name=f"Заказчик: {project.title[:60]}",
                    pipeline_stage=PipelineStage.NEW_LEAD,
                )
                session.add(client)
                await session.flush()
        except IntegrityError:
            existing = await _find()
            if existing is None:  # pragma: no cover - constraint guarantees it
                raise
            client = existing
    if client.pipeline_stage is PipelineStage.NEW_LEAD:
        client.pipeline_stage = PipelineStage.PROPOSAL_SENT
    await log_interaction(
        session,
        client,
        InteractionType.MESSAGE,
        f"Отклик #{proposal.id} отправлен: {project.title[:80]}",
        touch_contact=True,
        now=moment,
    )
    if with_reminder:
        await schedule_reminder(
            session,
            client,
            due_at=moment + REMINDER_AFTER_PROPOSAL,
            message=(
                f"Нет ответа по отклику на «{project.title[:60]}» — напомнить о себе?"
            ),
        )
    await session.flush()
    return client


async def schedule_reminder(
    session: AsyncSession,
    client: Client,
    due_at: datetime,
    message: str,
) -> Reminder:
    """Schedule a follow-up reminder (§3.8)."""
    reminder = Reminder(client_id=client.id, due_at=due_at, message=message)
    session.add(reminder)
    await session.flush()
    return reminder


async def find_due_reminders(
    session: AsyncSession, now: Optional[datetime] = None
) -> Sequence[Reminder]:
    """Find PENDING reminders whose time has come (notified once, §3.8)."""
    moment = now or utcnow()
    result = await session.execute(
        select(Reminder).where(
            Reminder.status == ReminderStatus.PENDING,
            Reminder.due_at <= moment,
        )
    )
    return result.scalars().all()


async def mark_notified(session: AsyncSession, reminder: Reminder) -> Reminder:
    """Mark a reminder as delivered to the user (no re-notification)."""
    reminder.status = ReminderStatus.NOTIFIED
    await session.flush()
    return reminder


async def snooze_reminder(
    session: AsyncSession,
    reminder: Reminder,
    delay: timedelta = SNOOZE_DEFAULT,
    now: Optional[datetime] = None,
) -> Reminder:
    """Postpone a reminder («отложить», §3.8)."""
    reminder.due_at = (now or utcnow()) + delay
    reminder.status = ReminderStatus.PENDING
    await session.flush()
    return reminder


async def complete_reminder(session: AsyncSession, reminder: Reminder) -> Reminder:
    """Complete a reminder («написать сейчас» → done)."""
    reminder.status = ReminderStatus.DONE
    await session.flush()
    return reminder
