"""Async database engine/session management for V2 models.

Uses ``DATABASE_URL`` from config. Defaults to a local SQLite file for
development; production should point at PostgreSQL (AGENTS.md §4.2).
Schema is managed by Alembic (``alembic upgrade head``); for SQLite dev
convenience :func:`init_v2_db` creates tables directly.
"""
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.models import Base

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def normalize_database_url(url: str) -> str:
    """Normalize a DATABASE_URL to an async SQLAlchemy driver URL.

    Args:
        url: Raw URL (e.g. ``postgres://...`` from a hosting provider).

    Returns:
        URL with an async driver (``asyncpg`` / ``aiosqlite``).
    """
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite:///") and "+aiosqlite" not in url:
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


def get_engine() -> AsyncEngine:
    """Get or lazily create the global async engine from config."""
    global _engine
    if _engine is None:
        from config import get_config

        url = normalize_database_url(get_config().DATABASE_URL)
        _engine = create_async_engine(url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or lazily create the global async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


def set_session_factory(
    factory: Optional[async_sessionmaker[AsyncSession]],
) -> None:
    """Override the global session factory (used by tests)."""
    global _session_factory
    _session_factory = factory


async def init_v2_db(engine: Optional[AsyncEngine] = None) -> None:
    """Create all V2 tables directly (tests/dev tooling ONLY).

    Production startup must use :func:`run_v2_migrations` — ``create_all``
    bypasses ``alembic_version`` and breaks every future schema migration.
    """
    eng = engine or get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def run_v2_migrations() -> None:
    """Apply Alembic migrations up to head (the production schema path).

    Runs synchronously BEFORE the bot's event loop starts (alembic's async
    env calls ``asyncio.run`` internally). Works for SQLite and PostgreSQL
    alike, and records ``alembic_version`` so future upgrades apply cleanly.

    Event-loop safety: ``asyncio.run`` inside alembic's env sets the current
    event loop to ``None`` on exit. The caller's loop is captured and
    restored here, otherwise everything after this call that relies on the
    current loop (APScheduler ``start()``, PTB polling) crashes with
    "There is no current event loop".
    """
    import asyncio
    from pathlib import Path

    import alembic.command as alembic_command
    from alembic.config import Config as AlembicConfig

    try:
        previous_loop: Optional[asyncio.AbstractEventLoop] = (
            asyncio.get_event_loop()
        )
    except RuntimeError:
        previous_loop = None

    root = Path(__file__).resolve().parent.parent
    config = AlembicConfig(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    try:
        alembic_command.upgrade(config, "head")
    finally:
        if previous_loop is not None:
            asyncio.set_event_loop(previous_loop)


async def dispose_engine() -> None:
    """Dispose the global engine (graceful shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
