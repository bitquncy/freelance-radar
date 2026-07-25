"""PostgreSQL dialect smoke test — runs only when TEST_PG_URL is set.

Verifies on a REAL PostgreSQL what SQLite unit tests cannot: partial unique
indexes (``postgresql_where``), savepoint recovery under asyncpg and the
Alembic chain. Locally: start any Postgres, then

    TEST_PG_URL=postgresql+asyncpg://user@host:5432/dbname pytest \
        tests/integration/test_postgres_smoke.py

CI skips it (no Postgres service wired — documented debt).
"""
import os
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core import billing
from core.models import (
    ExchangeConnection,
    PaymentStatus,
    Platform,
    Project,
    ProjectAnalysis,
    Subscription,
    SubscriptionTier,
    User,
    utcnow,
)

PG_URL = os.environ.get("TEST_PG_URL", "")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="TEST_PG_URL not set — PostgreSQL smoke skipped"
)


async def test_postgres_constraints_and_billing() -> None:
    """Schema (via alembic), constraints, savepoints and billing on PG."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    # Alembic's async env calls asyncio.run(), which cannot execute inside
    # this already-running test loop — run the upgrade in a subprocess.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env={**os.environ, "DATABASE_URL": PG_URL},
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    engine = create_async_engine(PG_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    marker = utcnow().strftime("%H%M%S%f")
    async with factory() as session:
        tables = set(
            (
                await session.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                )
            )
            .scalars()
            .all()
        )
        assert {"users", "projects", "subscriptions", "alembic_version"} <= tables

        user = User(
            telegram_id=int(f"77{marker[:7]}"),
            subscription_tier=SubscriptionTier.TRIAL,
            subscription_expires_at=utcnow() + timedelta(days=7),
        )
        session.add(user)
        await session.flush()

        project = Project(
            source=Platform.KWORK, external_id=f"pgsmoke-{marker}", title="PG"
        )
        session.add(project)
        await session.flush()

        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    Project(
                        source=Platform.KWORK,
                        external_id=f"pgsmoke-{marker}",
                        title="dup",
                    )
                )
                await session.flush()

        session.add(ProjectAnalysis(project_id=project.id, user_id=user.id))
        await session.flush()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    ProjectAnalysis(project_id=project.id, user_id=user.id)
                )
                await session.flush()

        session.add(ExchangeConnection(user_id=user.id, platform=Platform.KWORK))
        await session.flush()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    ExchangeConnection(user_id=user.id, platform=Platform.KWORK)
                )
                await session.flush()
        # TG channels are exempt from the partial unique index
        session.add(
            ExchangeConnection(
                user_id=user.id,
                platform=Platform.TG_CHANNEL,
                settings={"channel": "@a"},
            )
        )
        session.add(
            ExchangeConnection(
                user_id=user.id,
                platform=Platform.TG_CHANNEL,
                settings={"channel": "@b"},
            )
        )
        await session.flush()

        intent = billing.parse_payload(billing.build_payload(SubscriptionTier.PRO))
        charge = f"pg-{marker}"
        _, first = await billing.apply_paid_subscription(
            session, user, intent, charge
        )
        _, second = await billing.apply_paid_subscription(
            session, user, intent, charge
        )
        assert first is True and second is False
        subs = (
            (
                await session.execute(
                    select(Subscription).where(
                        Subscription.payment_charge_id == charge
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(subs) == 1 and subs[0].status is PaymentStatus.PAID
        await session.rollback()  # leave no smoke rows behind
    await engine.dispose()
