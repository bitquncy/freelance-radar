"""Unit tests for database connection manager."""
import pytest
import tempfile
import os

from db.database import Database


class TestDatabase:
    @pytest.fixture
    def db_path(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        yield path
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_connection(self, db_path):
        """Test connection opens and closes."""
        db = Database(db_path)
        conn = await db.connect()
        assert conn is not None
        await db.close()

    @pytest.mark.asyncio
    async def test_connection_context_manager(self, db_path):
        """Test connection context manager."""
        db = Database(db_path)
        async with db.connection() as conn:
            cursor = await conn.execute("SELECT 1")
            row = await cursor.fetchone()
            assert row[0] == 1

    @pytest.mark.asyncio
    async def test_transaction_commit(self, db_path):
        """Test transaction commits on success."""
        db = Database(db_path)
        async with db.connection() as conn:
            await conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")

        async with db.transaction() as conn:
            await conn.execute("INSERT INTO test (name) VALUES (?)", ("hello",))

        async with db.connection() as conn:
            cursor = await conn.execute("SELECT name FROM test")
            row = await cursor.fetchone()
            assert row[0] == "hello"

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, db_path):
        """Test transaction rolls back on exception."""
        db = Database(db_path)
        async with db.connection() as conn:
            await conn.execute("CREATE TABLE test2 (id INTEGER PRIMARY KEY, name TEXT)")

        try:
            async with db.transaction() as conn:
                await conn.execute("INSERT INTO test2 (name) VALUES (?)", ("hello",))
                raise ValueError("test error")
        except ValueError:
            pass

        async with db.connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM test2")
            row = await cursor.fetchone()
            assert row[0] == 0
