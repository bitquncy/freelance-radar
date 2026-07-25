"""Health check script for Docker — async-correct and config-independent.

The previous version used a synchronous ``with`` over an aiosqlite
connection, which raises ``TypeError`` on every run — the container was
permanently "unhealthy" and orchestrators kept restarting a perfectly
healthy bot (restart loops then trigger mid-tick recovery paths).

This version:
    * actually awaits the DB probe (``asyncio.run``);
    * reads ``DB_PATH`` from the environment instead of importing ``config``
      (the healthcheck must not require the full secret set to run);
    * treats a MISSING log file as healthy — containers log to stdout, the
      file only exists when file logging is enabled;
    * catches ``Exception`` so an unexpected error means "unhealthy", not a
      traceback with a random exit code.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

import aiosqlite

LOG_MAX_AGE_SECONDS = 600


async def check_db(db_path: str) -> bool:
    """Check that the SQLite database is reachable and answers a query."""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("SELECT 1")
        return True
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


def main() -> int:
    """Run all probes; exit 0 only when everything is healthy."""
    db_path = os.environ.get("DB_PATH", "freelance_radar.db")
    db_ok = asyncio.run(check_db(db_path))
    log_ok = check_log()
    if db_ok and log_ok:
        print("OK")
        return 0
    print(f"FAIL: db={db_ok}, log={log_ok}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
