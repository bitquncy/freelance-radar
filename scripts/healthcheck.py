"""Container readiness probe for configured V2 database and writable disk."""
import asyncio
import os
import shutil
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite:///") and "+aiosqlite" not in url:
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


async def check_db(url: str) -> bool:
    engine = create_async_engine(normalize_url(url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            return (await connection.execute(text("SELECT 1"))).scalar_one() == 1
    except Exception as exc:  # noqa: BLE001
        print(f"db check failed: {type(exc).__name__}")
        return False
    finally:
        await engine.dispose()


def check_disk() -> bool:
    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".readiness"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        minimum = int(os.environ.get("MIN_DISK_FREE_MB", "100")) * 1024 * 1024
        return shutil.disk_usage(data_dir).free >= minimum
    except (OSError, ValueError):
        return False


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        db_path = os.environ.get("DB_PATH", "freelance_radar_v2.db")
        # Do not let SQLite silently create a missing parent during readiness.
        parent = Path(db_path).parent
        if parent != Path(".") and not parent.exists():
            print("db=fail disk=fail")
            return 1
        url = f"sqlite+aiosqlite:///{db_path}"
    db_ok = asyncio.run(check_db(url))
    disk_ok = check_disk()
    print(f"db={'ok' if db_ok else 'fail'} disk={'ok' if disk_ok else 'fail'}")
    return 0 if db_ok and disk_ok else 1


if __name__ == "__main__":
    sys.exit(main())
