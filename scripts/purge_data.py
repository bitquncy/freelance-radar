"""Retention purge; dry-run by default and financial records are excluded."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import create_async_engine

from core.models import Interaction, Project


async def run(days: int, apply: bool) -> int:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            counts = {}
            for model in (Interaction, Project):
                counts[model.__tablename__] = (
                    await connection.execute(
                        select(func.count()).select_from(model).where(model.created_at < cutoff)
                    )
                ).scalar_one()
                if apply:
                    await connection.execute(delete(model).where(model.created_at < cutoff))
            print("apply" if apply else "dry-run", counts)
        return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=int(os.getenv("DATA_RETENTION_DAYS", "365")))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.days < 30:
        parser.error("retention must be at least 30 days")
    if args.apply and os.environ.get("RETENTION_PURGE_APPROVED") != "YES":
        parser.error("destructive purge requires RETENTION_PURGE_APPROVED=YES")
    return asyncio.run(run(args.days, args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
