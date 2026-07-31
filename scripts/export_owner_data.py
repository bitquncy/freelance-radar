"""Owner-scoped export helper for GDPR-style support requests."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.models import Client, Interaction, PortfolioItem, Project, ProjectAnalysis, Proposal, Reminder, Subscription, User, as_dict

CONFIRMATION = "EXPORT-OWNER"


def _is_postgres_url(url: str) -> bool:
    return url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://"))


async def _collect(session, user_id: int) -> dict[str, list[dict]]:
    user = await session.get(User, user_id)
    if user is None:
        raise LookupError(f"user_id={user_id} not found")
    clients = (await session.execute(select(Client).where(Client.user_id == user_id))).scalars().all()
    client_ids = [client.id for client in clients]
    reminders = []
    interactions = []
    if client_ids:
        reminders = (await session.execute(select(Reminder).where(Reminder.client_id.in_(client_ids)))).scalars().all()
        interactions = (
            await session.execute(
                select(Interaction).where(Interaction.client_id.in_(client_ids))
            )
        ).scalars().all()
    projects = (await session.execute(select(Project))).scalars().all()
    project_ids = [project.id for project in projects]
    analyses = []
    proposals = []
    if project_ids:
        analyses = (
            await session.execute(select(ProjectAnalysis).where(ProjectAnalysis.project_id.in_(project_ids)))
        ).scalars().all()
        proposals = (
            await session.execute(select(Proposal).where(Proposal.project_id.in_(project_ids)))
        ).scalars().all()
    return {
        "user": [as_dict(user)],
        "clients": [as_dict(item) for item in clients],
        "reminders": [as_dict(item) for item in reminders],
        "interactions": [as_dict(item) for item in interactions],
        "portfolio_items": [as_dict(item) for item in (await session.execute(select(PortfolioItem).where(PortfolioItem.user_id == user_id))).scalars().all()],
        "projects": [as_dict(item) for item in projects],
        "project_analyses": [as_dict(item) for item in analyses],
        "proposals": [as_dict(item) for item in proposals],
        "subscriptions": [as_dict(item) for item in (await session.execute(select(Subscription).where(Subscription.user_id == user_id))).scalars().all()],
    }


async def _run(url: str, user_id: int, output_dir: str, dry_run: bool) -> int:
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        payload = await _collect(session, user_id)
    if dry_run:
        print(json.dumps({k: len(v) for k, v in payload.items()}, indent=2, sort_keys=True))
        await engine.dispose()
        return 0
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = Path(output_dir) / f"owner-{user_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(path)
    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--output-dir", default=os.getenv("OWNER_EXPORT_DIR", "exports"))
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

    return asyncio.run(_run(url, args.user_id, args.output_dir, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
