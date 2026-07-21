"""Database connection manager with connection pooling for aiosqlite."""
import asyncio
import aiosqlite
from contextlib import asynccontextmanager
from typing import Optional

from config import DB_PATH
from services.logger_config import get_logger

logger = get_logger(__name__)


class Database:
    """Shared database connection manager.

    Provides long-lived connections for batch operations to avoid
    the overhead of opening/closing connections per query.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None
        self._ref_count = 0
        self._lock = asyncio.Lock()

    async def connect(self) -> aiosqlite.Connection:
        """Get or create shared connection with lock."""
        async with self._lock:
            if self._connection is None:
                self._connection = await aiosqlite.connect(self.db_path)
                await self._connection.execute("PRAGMA journal_mode=WAL")
                await self._connection.execute("PRAGMA synchronous=NORMAL")
                logger.debug("database.connection_opened")
            self._ref_count += 1
            return self._connection

    async def close(self) -> None:
        """Release connection reference and close if no more refs."""
        async with self._lock:
            self._ref_count = max(0, self._ref_count - 1)
            if self._ref_count == 0 and self._connection is not None:
                await self._connection.close()
                self._connection = None
                logger.debug("database.connection_closed")

    @asynccontextmanager
    async def transaction(self):
        """Context manager for a transaction block.

        Usage:
            async with db.transaction() as conn:
                await queries.save_vacancy(conn, vacancy)
                await queries.update_vacancy_ai_analysis(conn, ...)
        """
        conn = await self.connect()
        try:
            yield conn
            await conn.commit()
        except (aiosqlite.Error, ValueError, TypeError, OSError):
            await conn.rollback()
            raise
        finally:
            await self.close()

    @asynccontextmanager
    async def connection(self):
        """Context manager for a connection (auto-commit)."""
        conn = await self.connect()
        try:
            yield conn
        finally:
            await self.close()


# Global database instance
_db: Optional[Database] = None


def get_database() -> Database:
    """Get or create global database instance."""
    global _db
    if _db is None:
        _db = Database()
    return _db
