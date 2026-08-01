"""Регрессии экспорта, удаления владельца и retention."""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.models import (
    Base,
    ExchangeConnection,
    Platform,
    Project,
    ProjectAnalysis,
    Proposal,
    Subscription,
    User,
    utcnow,
)
from scripts import delete_owner_data, export_owner_data, purge_data


async def test_export_is_tenant_scoped_and_json_serializable(session) -> None:
    owner = User(telegram_id=910001)
    stranger = User(telegram_id=910002)
    session.add_all([owner, stranger])
    await session.flush()
    owner_connection = ExchangeConnection(user_id=owner.id, platform=Platform.KWORK)
    stranger_connection = ExchangeConnection(
        user_id=stranger.id, platform=Platform.KWORK
    )
    session.add_all([owner_connection, stranger_connection])
    await session.flush()
    owner_project = Project(
        source_connection_id=owner_connection.id,
        source=Platform.KWORK,
        external_id="owner-project",
        title="owner",
    )
    stranger_project = Project(
        source_connection_id=stranger_connection.id,
        source=Platform.KWORK,
        external_id="stranger-project",
        title="stranger",
    )
    session.add_all([owner_project, stranger_project])
    await session.flush()
    session.add_all(
        [
            ProjectAnalysis(project_id=owner_project.id, user_id=owner.id),
            Proposal(
                project_id=owner_project.id,
                user_id=owner.id,
                generated_text="owner proposal",
            ),
            ProjectAnalysis(project_id=stranger_project.id, user_id=stranger.id),
            Proposal(
                project_id=stranger_project.id,
                user_id=stranger.id,
                generated_text="private stranger proposal",
            ),
        ]
    )
    await session.commit()

    payload = await export_owner_data._collect(session, owner.id)
    assert {row["id"] for row in payload["projects"]} == {owner_project.id}
    assert {row["user_id"] for row in payload["project_analyses"]} == {owner.id}
    assert {row["user_id"] for row in payload["proposals"]} == {owner.id}
    encoded = json.dumps(payload, default=export_owner_data._json_default)
    assert "private stranger proposal" not in encoded


async def _build_file_database(path: str) -> async_sessionmaker:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    return async_sessionmaker(
        create_async_engine(f"sqlite+aiosqlite:///{path}"),
        expire_on_commit=False,
    )


async def test_delete_removes_all_user_dependencies_and_keeps_project(
    tmp_path,
) -> None:
    db_path = tmp_path / "delete.db"
    factory = await _build_file_database(str(db_path))
    async with factory() as session:
        user = User(telegram_id=920001)
        session.add(user)
        await session.flush()
        connection = ExchangeConnection(user_id=user.id, platform=Platform.KWORK)
        session.add(connection)
        await session.flush()
        project = Project(
            source_connection_id=connection.id,
            source=Platform.KWORK,
            external_id="kept-project",
            title="kept",
        )
        session.add(project)
        await session.flush()
        session.add_all(
            [
                ProjectAnalysis(project_id=project.id, user_id=user.id),
                Proposal(project_id=project.id, user_id=user.id, generated_text="x"),
                Subscription(user_id=user.id, tier=user.subscription_tier, amount=300),
            ]
        )
        await session.commit()
        user_id = user.id
        project_id = project.id
    await factory.kw["bind"].dispose()

    url = f"sqlite+aiosqlite:///{db_path}"
    await delete_owner_data._run(url, user_id, dry_run=False)

    engine = create_async_engine(url)
    async with async_sessionmaker(engine)() as session:
        assert await session.get(User, user_id) is None
        assert (
            await session.scalar(select(func.count()).select_from(Subscription))
        ) == 0
        assert (await session.scalar(select(func.count()).select_from(Proposal))) == 0
        kept = await session.get(Project, project_id)
        assert kept is not None and kept.source_connection_id is None
    await engine.dispose()


async def test_retention_deletes_project_dependencies_in_fk_safe_order(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "purge.db"
    factory = await _build_file_database(str(db_path))
    async with factory() as session:
        user = User(telegram_id=930001)
        session.add(user)
        await session.flush()
        old = Project(
            source=Platform.KWORK,
            external_id="old",
            title="old",
            created_at=utcnow() - timedelta(days=400),
        )
        fresh = Project(source=Platform.KWORK, external_id="fresh", title="fresh")
        session.add_all([old, fresh])
        await session.flush()
        session.add_all(
            [
                ProjectAnalysis(project_id=old.id, user_id=user.id),
                Proposal(project_id=old.id, user_id=user.id, generated_text="old"),
                ProjectAnalysis(project_id=fresh.id, user_id=user.id),
            ]
        )
        await session.commit()
    await factory.kw["bind"].dispose()

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    await purge_data.run(days=365, apply=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with async_sessionmaker(engine)() as session:
        projects = (await session.scalars(select(Project))).all()
        assert [project.external_id for project in projects] == ["fresh"]
        analyses = (await session.scalars(select(ProjectAnalysis))).all()
        assert len(analyses) == 1 and analyses[0].project_id == projects[0].id
        assert (await session.scalar(select(func.count()).select_from(Proposal))) == 0
    await engine.dispose()
