"""Unit tests for full-text search."""
import pytest
import aiosqlite
import tempfile
import os
from datetime import datetime

from db import queries
from db.models import JobVacancy


class TestSearchVacancies:
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
        # Create FTS5 table
        await conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vacancies_fts USING fts5(
                title, description, content='vacancies', content_rowid='id'
            )
        """)
        await conn.execute("""
            CREATE TRIGGER IF NOT EXISTS vacancies_fts_insert AFTER INSERT ON vacancies BEGIN
                INSERT INTO vacancies_fts(rowid, title, description)
                VALUES (new.id, new.title, new.description);
            END
        """)
        await conn.commit()
        yield conn
        await conn.close()
        os.unlink(path)

    def _make_vacancy(self, kwork_id: str, title: str, desc: str) -> JobVacancy:
        return JobVacancy(
            kwork_id=kwork_id,
            url=f"https://kwork.ru/{kwork_id}",
            title=title,
            description=desc,
            source="kwork",
            fetched_at=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_search_vacancies_basic(self, db):
        """Test basic FTS search."""
        vacancies = [
            self._make_vacancy("1", "Python Developer", "Need Django and Flask developer"),
            self._make_vacancy("2", "Java Developer", "Need Spring and Hibernate developer"),
            self._make_vacancy("3", "Python ML Engineer", "Machine learning with Python and TensorFlow"),
        ]
        for v in vacancies:
            await queries.save_vacancy(db, v)

        results = await queries.search_vacancies(db, "python", limit=10)
        assert len(results) == 2
        kwork_ids = {v.kwork_id for v in results}
        assert "1" in kwork_ids
        assert "3" in kwork_ids

    @pytest.mark.asyncio
    async def test_search_vacancies_phrase(self, db):
        """Test phrase search with quotes."""
        vacancies = [
            self._make_vacancy("1", "Python Developer", "Need Django and Flask developer"),
            self._make_vacancy("2", "Java Developer", "Need Spring and Hibernate developer"),
        ]
        for v in vacancies:
            await queries.save_vacancy(db, v)

        results = await queries.search_vacancies(db, '"Django and Flask"', limit=10)
        assert len(results) == 1
        assert results[0].kwork_id == "1"

    @pytest.mark.asyncio
    async def test_search_vacancies_empty(self, db):
        """Test empty query returns empty list."""
        results = await queries.search_vacancies(db, "", limit=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_vacancies_not_found(self, db):
        """Test search with no matches."""
        vacancies = [
            self._make_vacancy("1", "Python Developer", "Need Django"),
        ]
        for v in vacancies:
            await queries.save_vacancy(db, v)

        results = await queries.search_vacancies(db, "golang", limit=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_by_title_fallback(self, db):
        """Test LIKE fallback search."""
        vacancies = [
            self._make_vacancy("1", "Senior Python Developer", "Need Django"),
            self._make_vacancy("2", "Java Developer", "Need Spring"),
        ]
        for v in vacancies:
            await queries.save_vacancy(db, v)

        results = await queries.search_vacancies_by_title(db, "Python", limit=10)
        assert len(results) == 1
        assert results[0].kwork_id == "1"
