"""Unit tests for batch database queries."""
import pytest
import aiosqlite
import tempfile
import os
from datetime import datetime

from db import queries
from db.models import JobVacancy


class TestBatchQueries:
    @pytest.fixture
    async def db(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = await aiosqlite.connect(path)
        # Create vacancies table
        await conn.execute("""
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
        await conn.commit()
        yield conn
        await conn.close()
        os.unlink(path)

    def _make_vacancy(self, kwork_id: str, title: str = "Test") -> JobVacancy:
        return JobVacancy(
            kwork_id=kwork_id,
            url=f"https://kwork.ru/{kwork_id}",
            title=title,
            description="Test description",
            source="kwork",
            fetched_at=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_batch_save_vacancies(self, db):
        """Test bulk save of multiple vacancies."""
        vacancies = [
            self._make_vacancy("123", "First"),
            self._make_vacancy("456", "Second"),
            self._make_vacancy("789", "Third"),
        ]
        count = await queries.batch_save_vacancies(db, vacancies)
        assert count == 3

        # Verify all exist
        for v in vacancies:
            assert await queries.is_vacancy_seen(db, v.kwork_id)

    @pytest.mark.asyncio
    async def test_batch_save_empty_list(self, db):
        """Test bulk save with empty list."""
        count = await queries.batch_save_vacancies(db, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_batch_update_vacancy_ai_analysis(self, db):
        """Test bulk update of AI analysis fields."""
        # Insert test data first
        vacancies = [
            self._make_vacancy("111", "One"),
            self._make_vacancy("222", "Two"),
        ]
        await queries.batch_save_vacancies(db, vacancies)

        updates = [
            (75, "high", "no risks", 80, "111"),
            (45, "medium", "some risks", 50, "222"),
        ]
        count = await queries.batch_update_vacancy_ai_analysis(db, updates)
        assert count == 2

        # Verify updates
        v1 = await queries.get_vacancy_by_kwork_id(db, "111")
        assert v1.ai_score == 75
        assert v1.ai_priority == "high"
        assert v1.match_percentage == 80

        v2 = await queries.get_vacancy_by_kwork_id(db, "222")
        assert v2.ai_score == 45
        assert v2.ai_priority == "medium"

    @pytest.mark.asyncio
    async def test_batch_update_empty_list(self, db):
        """Test bulk update with empty list."""
        count = await queries.batch_update_vacancy_ai_analysis(db, [])
        assert count == 0
