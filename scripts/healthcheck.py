"""Health check script for Docker — async-correct, no config import.

Reads DB_PATH from the environment so the healthcheck doesn't need
the full secret set to run. Compatible with Docker HEALTHCHECK.
"""
import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

import aiosqlite

LOG_MAX_AGE_SECONDS = 3600


async def check_db(db_path: str) -> bool:
    """Check that the SQLite database is reachable and answers a query."""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT 1")
            row = await cursor.fetchone()
            return row is not None
    except Exception as exc:  # noqa: BLE001 - any failure means unhealthy
        print(f"db check failed: {exc}")
        return False


def check_log() -> bool:
    """Optional staleness probe for file logging (absent file = healthy)."""
    log_path = Path("logs/freelance_radar.log")
    if not log_path.exists():
        return True
    age = time.time() - log_path.stat().st_mtime
    if age >= LOG_MAX_AGE_SECONDS:
        print(f"log check failed: stale for {age:.0f}s")
        return False
    return True


def check_disk() -> bool:
    """Check disk space for data directory (cross-platform)."""
    db_path = os.environ.get("DB_PATH", "freelance_radar.db")
    data_dir = Path(db_path).parent if db_path else Path(".")
    try:
        usage = shutil.disk_usage(str(data_dir.resolve()))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 0.1:
            print(f"disk check failed: only {free_gb:.2f} GB free")
            return False
        return True
    except (OSError, ValueError):
        return True  # Skip check if unavailable


def main() -> int:
    """Run all probes; exit 0 only when everything is healthy."""
    db_path = os.environ.get("DB_PATH", "freelance_radar.db")
    db_ok = asyncio.run(check_db(db_path))
    log_ok = check_log()
    disk_ok = check_disk()

    if db_ok and log_ok:
        print(f"Healthcheck: OK")
        print(f"  db: {'✅' if db_ok else '❌'}")
        print(f"  log: {'✅' if log_ok else '❌'}")
        print(f"  disk: {'✅' if disk_ok else '❌'}")
        return 0
    print(f"Healthcheck: FAIL")
    print(f"  db: {'✅' if db_ok else '❌'}")
    print(f"  log: {'✅' if log_ok else '❌'}")
    print(f"  disk: {'✅' if disk_ok else '❌'}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
