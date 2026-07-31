"""Explicitly confirmed PostgreSQL restore helper."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess

CONFIRMATION = "DESTROY-AND-RESTORE"


def _is_postgres_url(url: str) -> bool:
    return url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = os.getenv("DATABASE_URL", "")
    if not _is_postgres_url(url):
        parser.error("DATABASE_URL must be PostgreSQL")
    if not args.dry_run and args.confirm != CONFIRMATION:
        parser.error(f"destructive restore requires --confirm {CONFIRMATION}")
    if args.dry_run:
        print("would run pg_restore with clean/if-exists against configured database")
        return 0
    if shutil.which("pg_restore") is None:
        parser.error("pg_restore is not available on PATH")
    command = ["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", url, args.backup]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
