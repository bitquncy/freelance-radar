"""Owner-scoped export helper for GDPR-style support requests."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.models import (
    BroadcastCampaign,
    BroadcastGroup,
    BroadcastRecipient,
    BroadcastTarget,
    Client,
    ExchangeConnection,
    Interaction,
    NotificationDelivery,
    PortfolioItem,
    Project,
    ProjectAnalysis,
    Proposal,
    Reminder,
    Subscription,
    User,
    as_dict,
)

CONFIRMATION = "EXPORT-OWNER"


def _is_postgres_url(url: str) -> bool:
    return url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://"))


def _async_postgres_url(url: str) -> str:
    """Нормализовать URL для async SQLAlchemy engine."""
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    return url


async def _collect(session, user_id: int) -> dict[str, list[dict]]:
    user = await session.get(User, user_id)
    if user is None:
        raise LookupError(f"user_id={user_id} not found")
    clients = (
        (await session.execute(select(Client).where(Client.user_id == user_id)))
        .scalars()
        .all()
    )
    client_ids = [client.id for client in clients]
    reminders = []
    interactions = []
    if client_ids:
        reminders = (
            (
                await session.execute(
                    select(Reminder).where(Reminder.client_id.in_(client_ids))
                )
            )
            .scalars()
            .all()
        )
        interactions = (
            (
                await session.execute(
                    select(Interaction).where(Interaction.client_id.in_(client_ids))
                )
            )
            .scalars()
            .all()
        )
    connections = (
        (
            await session.execute(
                select(ExchangeConnection).where(ExchangeConnection.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    analyses = (
        (
            await session.execute(
                select(ProjectAnalysis).where(ProjectAnalysis.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    proposals = (
        (await session.execute(select(Proposal).where(Proposal.user_id == user_id)))
        .scalars()
        .all()
    )
    deliveries = (
        (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    broadcast_groups = list(
        await session.scalars(
            select(BroadcastGroup).where(
                BroadcastGroup.owner_telegram_id == user.telegram_id
            )
        )
    )
    broadcast_group_ids = [group.id for group in broadcast_groups]
    broadcast_recipients = (
        list(
            await session.scalars(
                select(BroadcastRecipient).where(
                    BroadcastRecipient.group_id.in_(broadcast_group_ids)
                )
            )
        )
        if broadcast_group_ids
        else []
    )
    broadcast_campaigns = list(
        await session.scalars(
            select(BroadcastCampaign).where(
                BroadcastCampaign.owner_telegram_id == user.telegram_id
            )
        )
    )
    broadcast_ids = [campaign.id for campaign in broadcast_campaigns]
    broadcast_targets = (
        list(
            await session.scalars(
                select(BroadcastTarget).where(
                    BroadcastTarget.broadcast_id.in_(broadcast_ids)
                )
            )
        )
        if broadcast_ids
        else []
    )

    connection_ids = [connection.id for connection in connections]
    referenced_project_ids = {
        *(analysis.project_id for analysis in analyses),
        *(proposal.project_id for proposal in proposals),
    }
    project_filters = []
    if connection_ids:
        project_filters.append(Project.source_connection_id.in_(connection_ids))
    if referenced_project_ids:
        project_filters.append(Project.id.in_(referenced_project_ids))
    projects = []
    if project_filters:
        projects = (
            (await session.execute(select(Project).where(or_(*project_filters))))
            .scalars()
            .all()
        )
    return {
        "user": [as_dict(user)],
        "clients": [as_dict(item) for item in clients],
        "reminders": [as_dict(item) for item in reminders],
        "interactions": [as_dict(item) for item in interactions],
        "portfolio_items": [
            as_dict(item)
            for item in (
                await session.execute(
                    select(PortfolioItem).where(PortfolioItem.user_id == user_id)
                )
            )
            .scalars()
            .all()
        ],
        "exchange_connections": [as_dict(item) for item in connections],
        "projects": [as_dict(item) for item in projects],
        "project_analyses": [as_dict(item) for item in analyses],
        "proposals": [as_dict(item) for item in proposals],
        "notification_deliveries": [as_dict(item) for item in deliveries],
        "subscriptions": [
            as_dict(item)
            for item in (
                await session.execute(
                    select(Subscription).where(Subscription.user_id == user_id)
                )
            )
            .scalars()
            .all()
        ],
        "broadcast_groups": [as_dict(item) for item in broadcast_groups],
        "broadcast_recipients": [as_dict(item) for item in broadcast_recipients],
        "broadcast_campaigns": [as_dict(item) for item in broadcast_campaigns],
        "broadcast_targets": [as_dict(item) for item in broadcast_targets],
    }


def _json_default(value: object) -> object:
    """Преобразовать типы моделей в безопасные JSON-значения."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


async def _run(url: str, user_id: int, output_dir: str, dry_run: bool) -> int:
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        payload = await _collect(session, user_id)
    if dry_run:
        print(
            json.dumps(
                {k: len(v) for k, v in payload.items()}, indent=2, sort_keys=True
            )
        )
        await engine.dispose()
        return 0
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = Path(output_dir) / f"owner-{user_id}.json"
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    print(path)
    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument(
        "--output-dir", default=os.getenv("OWNER_EXPORT_DIR", "exports")
    )
    parser.add_argument("--confirm", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.user_id <= 0:
        parser.error("--user-id must be positive")
    url = os.getenv("DATABASE_URL", "")
    if not _is_postgres_url(url):
        parser.error("DATABASE_URL must be PostgreSQL")
    if not args.dry_run and args.confirm != CONFIRMATION:
        parser.error(f"export requires --confirm {CONFIRMATION}")
    import asyncio

    return asyncio.run(
        _run(_async_postgres_url(url), args.user_id, args.output_dir, args.dry_run)
    )


if __name__ == "__main__":
    raise SystemExit(main())
