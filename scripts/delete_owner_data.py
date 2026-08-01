"""Owner-scoped deletion helper with explicit confirmation."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select, update
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
)

CONFIRMATION = "DELETE-OWNER"


def _is_postgres_url(url: str) -> bool:
    return url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://"))


def _async_postgres_url(url: str) -> str:
    """Нормализовать URL для async SQLAlchemy engine."""
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    return url


async def _run(url: str, user_id: int, dry_run: bool) -> int:
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise LookupError(f"user_id={user_id} not found")
        clients = (
            (await session.execute(select(Client).where(Client.user_id == user_id)))
            .scalars()
            .all()
        )
        client_ids = [client.id for client in clients]
        projects = (
            (
                await session.execute(
                    select(PortfolioItem).where(PortfolioItem.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        proposal_rows = (
            (await session.execute(select(Proposal).where(Proposal.user_id == user_id)))
            .scalars()
            .all()
        )
        analysis_rows = (
            (
                await session.execute(
                    select(ProjectAnalysis).where(ProjectAnalysis.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        connection_rows = (
            (
                await session.execute(
                    select(ExchangeConnection).where(
                        ExchangeConnection.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        subscription_rows = (
            (
                await session.execute(
                    select(Subscription).where(Subscription.user_id == user_id)
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
        broadcast_campaigns = list(
            await session.scalars(
                select(BroadcastCampaign).where(
                    BroadcastCampaign.owner_telegram_id == user.telegram_id
                )
            )
        )
        broadcast_ids = [campaign.id for campaign in broadcast_campaigns]
        if dry_run:
            print(
                {
                    "clients": len(clients),
                    "portfolio_items": len(projects),
                    "proposals": len(proposal_rows),
                    "project_analyses": len(analysis_rows),
                    "exchange_connections": len(connection_rows),
                    "subscriptions": len(subscription_rows),
                    "broadcast_groups": len(broadcast_groups),
                    "broadcast_campaigns": len(broadcast_campaigns),
                }
            )
            await engine.dispose()
            return 0
        if broadcast_ids:
            await session.execute(
                delete(BroadcastTarget).where(
                    BroadcastTarget.broadcast_id.in_(broadcast_ids)
                )
            )
            await session.execute(
                delete(BroadcastCampaign).where(BroadcastCampaign.id.in_(broadcast_ids))
            )
        if broadcast_group_ids:
            await session.execute(
                delete(BroadcastRecipient).where(
                    BroadcastRecipient.group_id.in_(broadcast_group_ids)
                )
            )
            await session.execute(
                delete(BroadcastGroup).where(BroadcastGroup.id.in_(broadcast_group_ids))
            )
        if client_ids:
            await session.execute(
                delete(Reminder).where(Reminder.client_id.in_(client_ids))
            )
            await session.execute(
                delete(Interaction).where(Interaction.client_id.in_(client_ids))
            )
            await session.execute(delete(Client).where(Client.user_id == user_id))
        await session.execute(delete(Proposal).where(Proposal.user_id == user_id))
        await session.execute(
            delete(NotificationDelivery).where(NotificationDelivery.user_id == user_id)
        )
        await session.execute(
            delete(ProjectAnalysis).where(ProjectAnalysis.user_id == user_id)
        )
        await session.execute(
            delete(PortfolioItem).where(PortfolioItem.user_id == user_id)
        )
        await session.execute(
            delete(Subscription).where(Subscription.user_id == user_id)
        )
        connection_ids = [connection.id for connection in connection_rows]
        if connection_ids:
            # Проекты дедуплицируются глобально и могут быть нужны другим
            # пользователям, поэтому отвязываем источник вместо удаления.
            await session.execute(
                update(Project)
                .where(Project.source_connection_id.in_(connection_ids))
                .values(source_connection_id=None)
            )
        await session.execute(
            delete(ExchangeConnection).where(ExchangeConnection.user_id == user_id)
        )
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()
    await engine.dispose()
    print(f"deleted user_id={user_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.user_id <= 0:
        parser.error("--user-id must be positive")
    url = os.getenv("DATABASE_URL", "")
    if not _is_postgres_url(url):
        parser.error("DATABASE_URL must be PostgreSQL")
    if not args.dry_run and args.confirm != CONFIRMATION:
        parser.error(f"deletion requires --confirm {CONFIRMATION}")
    import asyncio

    return asyncio.run(_run(_async_postgres_url(url), args.user_id, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
