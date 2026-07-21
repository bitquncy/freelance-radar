"""Unit tests for multi-URL source feature."""
import pytest
import aiosqlite
from unittest.mock import AsyncMock, patch

from db.models import Source
from services.monitor import MonitorService


@pytest.fixture
async def setup_db(tmp_path):
    """Setup test database with sources table."""
    db_path = str(tmp_path / "test_multi_url.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                url TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                urls TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vacancies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kwork_id TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                budget TEXT,
                budget_min INTEGER,
                budget_max INTEGER,
                deadline TEXT,
                deadline_days INTEGER,
                category TEXT,
                subcategory TEXT,
                skills TEXT,
                proposals_count INTEGER,
                customer_rating REAL,
                customer_orders INTEGER,
                source TEXT NOT NULL DEFAULT 'kwork',
                fetched_at TEXT NOT NULL,
                analyzed INTEGER NOT NULL DEFAULT 0,
                responded INTEGER NOT NULL DEFAULT 0,
                ai_score INTEGER,
                ai_priority TEXT,
                ai_risks TEXT,
                match_percentage INTEGER,
                filtered_out INTEGER NOT NULL DEFAULT 0,
                filter_reason TEXT
            )
        """)
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


class TestSourceModel:
    """Test Source model with urls field."""

    def test_source_urls_list_property(self):
        """Test urls_list property returns list from JSON."""
        source = Source(
            id=1,
            name="test",
            source_type="telegram",
            url="https://t.me/channel1",
            urls='["https://t.me/channel1", "https://t.me/channel2"]'
        )
        assert source.urls_list == ["https://t.me/channel1", "https://t.me/channel2"]

    def test_source_urls_list_property_empty(self):
        """Test urls_list property returns empty list when urls is None."""
        source = Source(
            id=1,
            name="test",
            source_type="telegram",
            url="https://t.me/channel1",
            urls=None
        )
        assert source.urls_list == []

    def test_source_urls_list_setter(self):
        """Test urls_list setter sets JSON string."""
        source = Source(
            id=1,
            name="test",
            source_type="telegram",
            url="https://t.me/channel1",
            urls=None
        )
        source.urls_list = ["https://t.me/channel1", "https://t.me/channel2"]
        assert source.urls == '["https://t.me/channel1", "https://t.me/channel2"]'

    def test_source_urls_list_setter_string(self):
        """Test urls_list setter with string input."""
        source = Source(
            id=1,
            name="test",
            source_type="telegram",
            url="https://t.me/channel1",
            urls=None
        )
        source.urls_list = "https://t.me/channel1, https://t.me/channel2"
        assert source.urls is not None


class TestSourceQueries:
    """Test source queries with urls field."""

    @pytest.mark.asyncio
    async def test_add_source_with_urls(self, setup_db):
        """Test adding source with multiple URLs."""
        from db.queries import add_source, get_all_sources

        db_path = setup_db
        async with aiosqlite.connect(db_path) as db:
            source = Source(
                id=None,
                name="Test Telegram",
                source_type="telegram",
                url="https://t.me/channel1",
                enabled=True,
                urls='["https://t.me/channel1", "https://t.me/channel2"]'
            )
            source_id = await add_source(db, source)
            assert source_id > 0

            sources = await get_all_sources(db)
            assert len(sources) == 1
            assert sources[0].urls_list == ["https://t.me/channel1", "https://t.me/channel2"]

    @pytest.mark.asyncio
    async def test_add_source_without_urls(self, setup_db):
        """Test adding source without urls field (backward compatibility)."""
        from db.queries import add_source, get_all_sources

        db_path = setup_db
        async with aiosqlite.connect(db_path) as db:
            source = Source(
                id=None,
                name="Test Kwork",
                source_type="kwork",
                url=None,
                enabled=True
            )
            source_id = await add_source(db, source)
            assert source_id > 0

            sources = await get_all_sources(db)
            assert len(sources) == 1
            assert sources[0].urls_list == []

    @pytest.mark.asyncio
    async def test_get_enabled_sources_with_urls(self, setup_db):
        """Test getting enabled sources with urls."""
        from db.queries import add_source, get_enabled_sources

        db_path = setup_db
        async with aiosqlite.connect(db_path) as db:
            source = Source(
                id=None,
                name="Test Telegram",
                source_type="telegram",
                url="https://t.me/channel1",
                enabled=True,
                urls='["https://t.me/channel1", "https://t.me/channel2"]'
            )
            await add_source(db, source)

            sources = await get_enabled_sources(db)
            assert len(sources) == 1
            assert sources[0].urls_list == ["https://t.me/channel1", "https://t.me/channel2"]

    @pytest.mark.asyncio
    async def test_get_enabled_sources_excludes_disabled(self, setup_db):
        """Test that disabled sources are not returned."""
        from db.queries import add_source, get_enabled_sources

        db_path = setup_db
        async with aiosqlite.connect(db_path) as db:
            source = Source(
                id=None,
                name="Disabled Source",
                source_type="telegram",
                url="https://t.me/channel1",
                enabled=False,
                urls='["https://t.me/channel1"]'
            )
            await add_source(db, source)

            sources = await get_enabled_sources(db)
            assert len(sources) == 0


class TestMonitorMultiUrl:
    """Test MonitorService with multiple URLs per source."""

    @pytest.mark.asyncio
    async def test_fetch_all_vacancies_multiple_urls(self, setup_db):
        """Test that monitor processes multiple URLs per source."""
        from db.queries import add_source

        db_path = setup_db
        with patch('services.monitor.DB_PATH', db_path):
            monitor = MonitorService()
            monitor.telegram_parser = AsyncMock()
            monitor.telegram_parser.fetch_messages_from_channel = AsyncMock(return_value=[])

            async with aiosqlite.connect(db_path) as db:
                source = Source(
                    id=None,
                    name="Multi Channel",
                    source_type="telegram",
                    url=None,
                    enabled=True,
                    urls='["https://t.me/channel1", "https://t.me/channel2"]'
                )
                await add_source(db, source)

            with patch('services.monitor.queries.get_enabled_sources', new_callable=AsyncMock) as mock_get:
                mock_source = Source(
                    id=1,
                    name="Multi Channel",
                    source_type="telegram",
                    url=None,
                    enabled=True,
                    urls='["https://t.me/channel1", "https://t.me/channel2"]'
                )
                mock_get.return_value = [mock_source]

                await monitor.fetch_all_vacancies()

                assert monitor.telegram_parser.fetch_messages_from_channel.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_all_vacancies_legacy_url(self, setup_db):
        """Test that monitor processes legacy url field."""
        db_path = setup_db
        with patch('services.monitor.DB_PATH', db_path):
            monitor = MonitorService()
            monitor.telegram_parser = AsyncMock()
            monitor.telegram_parser.fetch_messages_from_channel = AsyncMock(return_value=[])

            with patch('services.monitor.queries.get_enabled_sources', new_callable=AsyncMock) as mock_get:
                mock_source = Source(
                    id=1,
                    name="Legacy Source",
                    source_type="telegram",
                    url="https://t.me/channel1",
                    enabled=True,
                    urls=None
                )
                mock_get.return_value = [mock_source]

                await monitor.fetch_all_vacancies()

                assert monitor.telegram_parser.fetch_messages_from_channel.call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_all_vacancies_mixed_urls(self, setup_db):
        """Test that monitor processes both legacy url and new urls field."""
        db_path = setup_db
        with patch('services.monitor.DB_PATH', db_path):
            monitor = MonitorService()
            monitor.telegram_parser = AsyncMock()
            monitor.telegram_parser.fetch_messages_from_channel = AsyncMock(return_value=[])

            with patch('services.monitor.queries.get_enabled_sources', new_callable=AsyncMock) as mock_get:
                mock_source = Source(
                    id=1,
                    name="Mixed Source",
                    source_type="telegram",
                    url="https://t.me/legacy_channel",
                    enabled=True,
                    urls='["https://t.me/channel1", "https://t.me/channel2"]'
                )
                mock_get.return_value = [mock_source]

                await monitor.fetch_all_vacancies()

                assert monitor.telegram_parser.fetch_messages_from_channel.call_count == 2
