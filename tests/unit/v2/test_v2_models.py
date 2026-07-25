"""Model-layer tests: all §5 entities persist, constraints hold."""
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Client,
    ExchangeConnection,
    Interaction,
    InteractionType,
    PaymentStatus,
    PipelineStage,
    Platform,
    PortfolioItem,
    Project,
    ProjectAnalysis,
    Proposal,
    ProposalStatus,
    Reminder,
    Subscription,
    SubscriptionTier,
    User,
    utcnow,
)
from tests.unit.v2.conftest import make_project


async def test_all_entities_roundtrip(session: AsyncSession, user) -> None:
    """Every §5 entity can be inserted and read back."""
    connection = ExchangeConnection(
        user_id=user.id,
        platform=Platform.TG_CHANNEL,
        settings={"channel": "@orders"},
    )
    project = make_project(external_id="rt-1")
    session.add_all([connection, project])
    await session.flush()

    analysis = ProjectAnalysis(
        project_id=project.id,
        user_id=user.id,
        extracted_budget=25000,
        extracted_skills=["python"],
        client_red_flags=["нет рейтинга"],
        win_probability=61.5,
    )
    proposal = Proposal(
        project_id=project.id, user_id=user.id, generated_text="Текст отклика"
    )
    client = Client(user_id=user.id, name="Тестовый заказчик")
    session.add_all([analysis, proposal, client])
    await session.flush()

    interaction = Interaction(
        client_id=client.id, type=InteractionType.NOTE, content="заметка"
    )
    reminder = Reminder(
        client_id=client.id, due_at=utcnow() + timedelta(hours=48), message="ping"
    )
    item = PortfolioItem(user_id=user.id, title="Кейс", tags=["python"])
    subscription = Subscription(
        user_id=user.id,
        tier=SubscriptionTier.PRO,
        amount=599,
        status=PaymentStatus.PAID,
        period_start=utcnow(),
        period_end=utcnow() + timedelta(days=30),
    )
    session.add_all([interaction, reminder, item, subscription])
    await session.commit()

    loaded = (
        await session.execute(select(Project).where(Project.external_id == "rt-1"))
    ).scalar_one()
    assert loaded.source is Platform.KWORK
    loaded_analysis = (
        await session.execute(
            select(ProjectAnalysis).where(ProjectAnalysis.project_id == loaded.id)
        )
    ).scalar_one()
    assert loaded_analysis.win_probability == 61.5
    assert (await session.get(Client, client.id)).pipeline_stage is (
        PipelineStage.NEW_LEAD
    )
    assert (await session.get(Proposal, proposal.id)).status is ProposalStatus.DRAFT
    assert (await session.get(User, user.id)).skills == [
        "python",
        "telegram-боты",
        "парсинг",
    ]


async def test_project_unique_source_external_id(session: AsyncSession) -> None:
    """Dedup constraint (§3.1): same (source, external_id) cannot repeat."""
    session.add(make_project(external_id="dup-1"))
    await session.commit()
    session.add(make_project(external_id="dup-1"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_same_external_id_different_sources_ok(session: AsyncSession) -> None:
    """Same external_id on different platforms is NOT a conflict."""
    session.add(make_project(external_id="x-7", source=Platform.KWORK))
    session.add(make_project(external_id="x-7", source=Platform.FL_RU))
    await session.commit()
    rows = (await session.execute(select(Project))).scalars().all()
    assert len(rows) == 2


async def test_user_telegram_id_unique(session: AsyncSession, user) -> None:
    """One row per Telegram account."""
    session.add(User(telegram_id=user.telegram_id))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_client_cascade_deletes_children(
    session: AsyncSession, user
) -> None:
    """Deleting a client removes its interactions and reminders."""
    client = Client(user_id=user.id, name="C")
    session.add(client)
    await session.flush()
    session.add(
        Interaction(client_id=client.id, type=InteractionType.MESSAGE, content="hi")
    )
    session.add(
        Reminder(client_id=client.id, due_at=utcnow(), message="m")
    )
    await session.commit()

    await session.delete(client)
    await session.commit()
    assert (await session.execute(select(Interaction))).scalars().all() == []
    assert (await session.execute(select(Reminder))).scalars().all() == []
