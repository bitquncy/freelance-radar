from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.models import Client, PortfolioItem, Subscription, User, utcnow

PG_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set — PostgreSQL owner workflow skipped")


@pytest.fixture(scope="module")
def seeded_owner(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, str]:
    root = Path(__file__).resolve().parents[2]

    # This file's tests may collect and run before test_postgres_smoke.py
    # (pytest sorts alphabetically: "owner_workflow" < "postgres_smoke"), so
    # the schema is not guaranteed to exist yet on a fresh PostgreSQL DB.
    # Alembic's async env calls asyncio.run(), which cannot execute inside
    # this already-running test loop — run the upgrade in a subprocess, same
    # approach as test_postgres_smoke.py.
    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env={**os.environ, "DATABASE_URL": PG_URL},
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert migration.returncode == 0, migration.stdout + migration.stderr

    engine = create_async_engine(PG_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _seed() -> int:
        async with factory() as session:
            user = User(telegram_id=int(utcnow().strftime("88%H%M%S%f")[:12]))
            session.add(user)
            await session.flush()
            session.add_all([
                PortfolioItem(user_id=user.id, title="case", description="desc"),
                Client(user_id=user.id, name="Acme"),
                Subscription(user_id=user.id, tier=user.subscription_tier, amount=300),
            ])
            await session.commit()
            return user.id

    import asyncio

    user_id = asyncio.run(_seed())
    return user_id, str(root)


@pytest.mark.parametrize(
    "script,args,expect_fragment",
    [
        ("scripts/export_owner_data.py", ["--dry-run"], "user"),
        ("scripts/delete_owner_data.py", ["--dry-run"], "clients"),
    ],
)
def test_owner_scripts_dry_run(seeded_owner: tuple[int, str], script: str, args: list[str], expect_fragment: str) -> None:
    user_id, root = seeded_owner
    result = subprocess.run(
        [sys.executable, script, "--user-id", str(user_id), *args],
        cwd=root,
        env={**os.environ, "DATABASE_URL": PG_URL},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert expect_fragment in result.stdout


def test_owner_delete_reports_dependency_counts(seeded_owner: tuple[int, str]) -> None:
    user_id, root = seeded_owner
    result = subprocess.run(
        [sys.executable, "scripts/delete_owner_data.py", "--user-id", str(user_id), "--dry-run"],
        cwd=root,
        env={**os.environ, "DATABASE_URL": PG_URL},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "proposals" in result.stdout and "project_analyses" in result.stdout
