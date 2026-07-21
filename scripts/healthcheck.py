"""Health check script for Docker."""
import sys
import aiosqlite
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH


def check_db() -> bool:
    """Check if database is accessible."""
    try:
        with aiosqlite.connect(DB_PATH) as db:
            db.execute("SELECT 1")
        return True
    except (aiosqlite.Error, OSError):
        return False


def check_log() -> bool:
    """Check if log file exists and is recent."""
    log_path = Path("logs/freelance_radar.log")
    if not log_path.exists():
        return False
    import time
    age = time.time() - log_path.stat().st_mtime
    return age < 600  # Last 10 minutes


if __name__ == "__main__":
    db_ok = check_db()
    log_ok = check_log()

    if db_ok and log_ok:
        print("OK")
        sys.exit(0)
    else:
        print(f"FAIL: db={db_ok}, log={log_ok}")
        sys.exit(1)
