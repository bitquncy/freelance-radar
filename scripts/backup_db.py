"""Safe PostgreSQL logical backup helper."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

CONFIRMATION = "RUN-BACKUP"


def _is_postgres_url(url: str) -> bool:
    return url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://"))


def _cli_postgres_url(url: str) -> str:
    """Преобразовать SQLAlchemy URL в формат libpq/pg_dump."""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url.removeprefix("postgresql+asyncpg://")
    if url.startswith("postgres://"):
        return "postgresql://" + url.removeprefix("postgres://")
    return url


def _build_output_path(output_dir: str) -> Path:
    return (
        Path(output_dir)
        / f"freelanceradar-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.dump"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=os.getenv("BACKUP_DIR", "backups"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    url = os.getenv("DATABASE_URL", "")
    if not _is_postgres_url(url):
        parser.error("DATABASE_URL must be PostgreSQL")
    if not args.dry_run and args.confirm != CONFIRMATION:
        parser.error(f"backup requires --confirm {CONFIRMATION}")

    output = _build_output_path(args.output_dir)
    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--file",
        str(output),
        _cli_postgres_url(url),
    ]
    if args.dry_run:
        print("would run pg_dump to", output)
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("pg_dump") is None:
        parser.error("pg_dump is not available on PATH")
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
