"""Unit tests for SenderService."""
import pytest
import aiosqlite
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from services.sender import SenderService


@pytest.fixture
def db_path(tmp_path):
    """Create temporary database for testing."""
    return str(tmp_path / "test_sender.db")


@pytest.fixture
async def setup_db(db_path):
    """Setup test database with required tables."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_cooldowns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL UNIQUE,
                last_sent_at TEXT NOT NULL,
                cooldown_seconds INTEGER NOT NULL
            )
        """)
        await db.commit()
    return db_path


@pytest.fixture
def sender():
    """Create SenderService instance with mocked dependencies."""
    return SenderService()


class TestSenderService:
    """Test cases for SenderService."""

    @pytest.mark.asyncio
    async def test_send_message_invalid_params(self, sender):
        """Test that send_message returns False for invalid params."""
        with patch('services.sender.DB_PATH', 'test.db'):
            result = await sender.send_message("", "test message")
            assert result is False

            result = await sender.send_message("test_chat", "")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_message_cooldown_active(self, sender, setup_db):
        """Test that send_message respects cooldown."""
        db_path = setup_db
        with patch('services.sender.DB_PATH', db_path):
            # Add a cooldown entry
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO chat_cooldowns (chat_id, last_sent_at, cooldown_seconds) VALUES (?, ?, ?)",
                    ("test_chat", datetime.now().isoformat(), 3600)
                )
                await db.commit()

            result = await sender.send_message("test_chat", "test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_message_success(self, sender, setup_db):
        """Test successful message sending."""
        db_path = setup_db
        with patch('services.sender.DB_PATH', db_path):
            # Mock Telegram parser
            mock_parser = AsyncMock()
            mock_parser.send_message_to_chat = AsyncMock(return_value=True)
            sender.telegram_parser = mock_parser

            result = await sender.send_message("test_chat", "test message", cooldown_seconds=60)
            assert result is True

            # Verify cooldown was updated
            async with aiosqlite.connect(db_path) as db:
                cursor = await db.execute(
                    "SELECT * FROM chat_cooldowns WHERE chat_id = ?",
                    ("test_chat",)
                )
                row = await cursor.fetchone()
                assert row is not None

    @pytest.mark.asyncio
    async def test_send_message_send_failed(self, sender, setup_db):
        """Test message send failure."""
        db_path = setup_db
        with patch('services.sender.DB_PATH', db_path):
            # Mock Telegram parser to fail
            mock_parser = AsyncMock()
            mock_parser.send_message_to_chat = AsyncMock(return_value=False)
            sender.telegram_parser = mock_parser

            result = await sender.send_message("test_chat", "test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_message_telegram_error(self, sender, setup_db):
        """Test message send failure due to Telegram error."""
        db_path = setup_db
        with patch('services.sender.DB_PATH', db_path):
            # Mock Telegram parser to raise exception
            mock_parser = AsyncMock()
            mock_parser.send_message_to_chat = AsyncMock(side_effect=Exception("Telegram error"))
            sender.telegram_parser = mock_parser

            # The error should be caught and result should be False
            result = await sender.send_message("test_chat", "test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_get_remaining_cooldown_no_cooldown(self, sender, setup_db):
        """Test get_remaining_cooldown when no cooldown exists."""
        db_path = setup_db
        with patch('services.sender.DB_PATH', db_path):
            remaining = await sender.get_remaining_cooldown("nonexistent_chat")
            assert remaining is None

    @pytest.mark.asyncio
    async def test_get_remaining_cooldown_active(self, sender, setup_db):
        """Test get_remaining_cooldown with active cooldown."""
        db_path = setup_db
        with patch('services.sender.DB_PATH', db_path):
            # Add a recent cooldown
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO chat_cooldowns (chat_id, last_sent_at, cooldown_seconds) VALUES (?, ?, ?)",
                    ("test_chat", datetime.now().isoformat(), 3600)
                )
                await db.commit()

            remaining = await sender.get_remaining_cooldown("test_chat")
            assert remaining is not None
            assert remaining > 0
            assert remaining <= 3600

    @pytest.mark.asyncio
    async def test_get_remaining_cooldown_expired(self, sender, setup_db):
        """Test get_remaining_cooldown when cooldown has expired."""
        db_path = setup_db
        with patch('services.sender.DB_PATH', db_path):
            # Add an expired cooldown
            past_time = (datetime.now() - timedelta(seconds=7200)).isoformat()
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO chat_cooldowns (chat_id, last_sent_at, cooldown_seconds) VALUES (?, ?, ?)",
                    ("test_chat", past_time, 3600)
                )
                await db.commit()

            remaining = await sender.get_remaining_cooldown("test_chat")
            assert remaining == 0

    @pytest.mark.asyncio
    async def test_cleanup(self, sender):
        """Test cleanup disconnects Telegram parser."""
        mock_parser = AsyncMock()
        sender.telegram_parser = mock_parser

        await sender.cleanup()
        mock_parser.disconnect.assert_called_once()
        assert sender.telegram_parser is None

    @pytest.mark.asyncio
    async def test_cleanup_no_parser(self, sender):
        """Test cleanup when no parser is set."""
        sender.telegram_parser = None
        await sender.cleanup()
        assert sender.telegram_parser is None

    @pytest.mark.asyncio
    async def test_send_message_default_cooldown(self, sender, setup_db):
        """Test that default cooldown is used when not specified."""
        db_path = setup_db
        with patch('services.sender.DB_PATH', db_path), \
             patch('services.sender.DEFAULT_COOLDOWN_SEC', 3600):
            mock_parser = AsyncMock()
            mock_parser.send_message_to_chat = AsyncMock(return_value=True)
            sender.telegram_parser = mock_parser

            result = await sender.send_message("test_chat", "test message")
            assert result is True
