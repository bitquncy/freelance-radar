"""Unit tests for blacklist service."""
import pytest
import pytest_asyncio
import aiosqlite
import os
import tempfile
from datetime import datetime, timedelta

from services.blacklist import BlacklistService


@pytest.fixture
def db_path():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest_asyncio.fixture
async def blacklist_service(db_path):
    """Create a BlacklistService with a temporary database."""
    # Create the blacklist table
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                reason TEXT,
                added_at TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                expires_at TEXT,
                UNIQUE(entity_type, entity_id, user_id)
            )
        """)
        await db.commit()

    return BlacklistService(db_path)


class TestBlacklistService:
    @pytest.mark.asyncio
    async def test_add_to_blacklist(self, blacklist_service):
        """Test adding an entity to the blacklist."""
        bs = blacklist_service
        await bs.add_to_blacklist("vacancy", "12345", user_id=1, reason="test")

        assert await bs.is_blacklisted("vacancy", "12345")
        assert not await bs.is_blacklisted("vacancy", "99999")
        assert not await bs.is_blacklisted("customer", "12345")

    @pytest.mark.asyncio
    async def test_add_to_blacklist_with_ttl(self, blacklist_service):
        """Test adding with TTL expiration."""
        bs = blacklist_service
        # Add with 1 day TTL
        await bs.add_to_blacklist("vacancy", "12345", user_id=1, reason="test", ttl_days=1)

        assert await bs.is_blacklisted("vacancy", "12345")

    @pytest.mark.asyncio
    async def test_remove_from_blacklist(self, blacklist_service):
        """Test removing from blacklist."""
        bs = blacklist_service
        await bs.add_to_blacklist("vacancy", "12345", user_id=1, reason="test")
        assert await bs.is_blacklisted("vacancy", "12345")

        await bs.remove_from_blacklist("vacancy", "12345")
        assert not await bs.is_blacklisted("vacancy", "12345")

    @pytest.mark.asyncio
    async def test_get_blacklist(self, blacklist_service):
        """Test getting blacklist entries."""
        bs = blacklist_service
        await bs.add_to_blacklist("vacancy", "12345", user_id=1, reason="test1")
        await bs.add_to_blacklist("customer", "cust1", user_id=1, reason="test2")

        entries = await bs.get_blacklist()
        assert len(entries) == 2

        entries_vacancy = await bs.get_blacklist("vacancy")
        assert len(entries_vacancy) == 1
        assert entries_vacancy[0].entity_type == "vacancy"

    @pytest.mark.asyncio
    async def test_check_vacancy(self, blacklist_service):
        """Test vacancy check with both vacancy and customer."""
        bs = blacklist_service
        await bs.add_to_blacklist("vacancy", "12345", user_id=1, reason="test")

        # Vacancy is blacklisted
        assert await bs.check_vacancy("12345")
        # Different vacancy is not blacklisted
        assert not await bs.check_vacancy("99999")
        # Vacancy is blacklisted even if customer is not
        assert await bs.check_vacancy("12345", "cust1")

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, blacklist_service):
        """Test cleanup of expired entries."""
        bs = blacklist_service

        # Add entry with past expiration
        past_date = (datetime.now() - timedelta(days=1)).isoformat()
        async with aiosqlite.connect(bs.db_path) as db:
            await db.execute(
                "INSERT INTO blacklist (entity_type, entity_id, reason, added_at, user_id, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("vacancy", "12345", "test", datetime.now().isoformat(), 1, past_date)
            )
            await db.commit()

        removed = await bs.cleanup_expired()
        assert removed == 1
        assert not await bs.is_blacklisted("vacancy", "12345")

    @pytest.mark.asyncio
    async def test_get_blacklist_excludes_expired(self, blacklist_service):
        """Test that get_blacklist excludes expired entries."""
        bs = blacklist_service

        # Add expired entry
        past_date = (datetime.now() - timedelta(days=1)).isoformat()
        async with aiosqlite.connect(bs.db_path) as db:
            await db.execute(
                "INSERT INTO blacklist (entity_type, entity_id, reason, added_at, user_id, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("vacancy", "12345", "expired", datetime.now().isoformat(), 1, past_date)
            )
            await db.commit()

        entries = await bs.get_blacklist()
        assert len(entries) == 0
