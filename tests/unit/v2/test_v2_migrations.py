"""Alembic migration test: upgrade head builds the full §5 schema."""
import os
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[3]

SPEC_TABLES = {
    "users",
    "exchange_connections",
    "projects",
    "project_analyses",
    "proposals",
    "clients",
    "interactions",
    "reminders",
    "portfolio_items",
    "subscriptions",
}


def test_upgrade_head_creates_all_spec_tables(tmp_path: Path) -> None:
    """`alembic upgrade head` creates every AGENTS.md §5 entity table."""
    db_path = tmp_path / "mig.db"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    try:
        config = Config(str(REPO_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous

    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert SPEC_TABLES.issubset(tables)
