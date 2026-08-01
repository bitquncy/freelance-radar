from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.backup_db import _cli_postgres_url as backup_url
from scripts.delete_owner_data import _async_postgres_url as delete_url
from scripts.export_owner_data import _async_postgres_url as export_url
from scripts.restore_db import _cli_postgres_url as restore_url


def _run(
    command: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, env=env, timeout=60)


def test_backup_restore_scripts_help_and_dry_run(tmp_path: Path) -> None:
    base_env = {**os.environ, "DATABASE_URL": "postgresql://user:pass@localhost/db"}
    backup = _run(
        [
            sys.executable,
            "scripts/backup_db.py",
            "--dry-run",
            "--output-dir",
            str(tmp_path),
        ],
        env=base_env,
    )
    assert backup.returncode == 0, backup.stdout + backup.stderr
    assert "would run pg_dump" in backup.stdout

    restore = _run(
        [sys.executable, "scripts/restore_db.py", "backup.dump", "--dry-run"],
        env=base_env,
    )
    assert restore.returncode == 0, restore.stdout + restore.stderr
    assert "would run pg_restore" in restore.stdout


def test_owner_scripts_require_confirmation() -> None:
    env = {**os.environ, "DATABASE_URL": "postgresql://user:pass@localhost/db"}
    export = _run(
        [sys.executable, "scripts/export_owner_data.py", "--user-id", "1"], env=env
    )
    assert export.returncode != 0
    assert "EXPORT-OWNER" in export.stderr

    delete = _run(
        [sys.executable, "scripts/delete_owner_data.py", "--user-id", "1"], env=env
    )
    assert delete.returncode != 0
    assert "DELETE-OWNER" in delete.stderr


def test_purge_requires_explicit_approval_for_apply() -> None:
    env = {**os.environ, "DATABASE_URL": "postgresql://user:pass@localhost/db"}
    purge = _run([sys.executable, "scripts/purge_data.py", "--apply"], env=env)
    assert purge.returncode != 0
    assert "RETENTION_PURGE_APPROVED=YES" in purge.stderr


def test_database_urls_are_normalized_for_each_driver() -> None:
    sqlalchemy_url = "postgresql+asyncpg://user:pass@db/radar"
    assert backup_url(sqlalchemy_url) == "postgresql://user:pass@db/radar"
    assert restore_url(sqlalchemy_url) == "postgresql://user:pass@db/radar"
    libpq_url = "postgresql://user:pass@db/radar"
    assert export_url(libpq_url) == sqlalchemy_url
    assert delete_url(libpq_url) == sqlalchemy_url
