"""Unit tests for parsers."""

import pytest

from parsers.kwork import KworkParser
from parsers.telegram_source import TelegramSourceParser


class TestKworkParser:
    @pytest.fixture
    def parser(self):
        return KworkParser()

    def test_extract_title(self, parser):
        """Test title extraction from HTML."""
        from bs4 import BeautifulSoup

        html = '<html><body><h1 class="wants-card__header-title">Test Project Title</h1></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        title = parser._extract_title(soup)
        assert title == "Test Project Title"

    def test_extract_title_fallback(self, parser):
        """Test title fallback to plain h1."""
        from bs4 import BeautifulSoup

        html = "<html><body><h1>Simple Title</h1></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        title = parser._extract_title(soup)
        assert title == "Simple Title"

    def test_extract_budget_range(self, parser):
        """Test budget range extraction."""
        from bs4 import BeautifulSoup

        html = '<html><body><div class="wants-card__header-price">15000 ₽</div></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        budget_text = parser._extract_budget_text(soup)
        assert budget_text == "15000 ₽"

    def test_extract_budget_range_with_range(self, parser):
        """Test budget range with min/max."""
        from bs4 import BeautifulSoup

        html = '<html><body><div class="price">10000 - 20000 ₽</div></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        budget_text = parser._extract_budget_text(soup)
        assert budget_text is not None
        min_val, max_val = parser._extract_budget_range(soup)
        assert min_val == 10000
        assert max_val == 20000

    def test_extract_deadline_days(self, parser):
        """Test deadline extraction in days."""
        days = parser._extract_deadline_days("3 дня")
        assert days == 3

    def test_extract_deadline_weeks(self, parser):
        """Test deadline extraction in weeks."""
        days = parser._extract_deadline_days("2 недели")
        assert days == 14

    def test_extract_deadline_none(self, parser):
        """Test deadline extraction with None."""
        days = parser._extract_deadline_days(None)
        assert days is None

    def test_extract_deadline_empty(self, parser):
        """Test deadline extraction with empty string."""
        days = parser._extract_deadline_days("")
        assert days is None

    def test_extract_category_from_breadcrumbs(self, parser):
        """Test category extraction from breadcrumbs."""
        from bs4 import BeautifulSoup

        html = """
        <html><body>
        <nav class="breadcrumb"><a>Home</a><a>Programming</a><a>Python</a></nav>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        category = parser._extract_category(soup)
        assert category == "Programming"

    def test_extract_skills(self, parser):
        """Test skills extraction."""
        from bs4 import BeautifulSoup

        html = """
        <html><body>
        <div class="skills"><a>Python</a><a>Django</a><span>PostgreSQL</span></div>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        skills = parser._extract_skills(soup)
        assert "Python" in skills
        assert "Django" in skills

    async def test_rate_limiter_status(self, parser):
        """Test rate limiter status."""
        status = await parser.rate_limiter.get_status()
        assert "requests_today" in status
        assert "daily_limit" in status
        assert "remaining" in status


class TestTelegramSourceParser:
    def test_extract_budget_from_text(self):
        """Test budget extraction from message text."""
        parser = TelegramSourceParser()
        text = "Need developer. Budget: 25000 rub"
        budget = parser._extract_budget(text)
        assert budget is not None

    def test_extract_deadline_days(self):
        """Test deadline extraction."""
        parser = TelegramSourceParser()
        text = "Срок: 5 дней"
        days = parser._extract_deadline_days(text)
        assert days == 5

    def test_extract_deadline_weeks(self):
        """Test deadline extraction in weeks."""
        parser = TelegramSourceParser()
        text = "Срок: 2 недели"
        days = parser._extract_deadline_days(text)
        assert days == 14

    def test_extract_deadline_hours(self):
        """Test deadline extraction in hours."""
        parser = TelegramSourceParser()
        text = "Срок: 24 часа"
        days = parser._extract_deadline_days(text)
        assert days == 1

    def test_extract_deadline_months(self):
        """Test deadline extraction in months."""
        parser = TelegramSourceParser()
        text = "Срок: 1 месяц"
        days = parser._extract_deadline_days(text)
        assert days == 30

    def test_extract_category_from_hashtags(self):
        """Test category from hashtags."""
        parser = TelegramSourceParser()
        text = "Need #python developer"
        category = parser._extract_category(text)
        assert category == "python"

    def test_extract_category_from_text(self):
        """Test category from text content."""
        parser = TelegramSourceParser()
        text = "Нужен разработчик на Django"
        category = parser._extract_category(text)
        assert category == "django"

    def test_extract_skills_from_text(self):
        """Test skills extraction from hashtags."""
        parser = TelegramSourceParser()
        text = "Need #python #django developer"
        skills = parser._extract_skills(text)
        assert "python" in skills
        assert "django" in skills

    def test_extract_skills_none(self):
        """Test skills extraction with no hashtags."""
        parser = TelegramSourceParser()
        text = "Need developer"
        skills = parser._extract_skills(text)
        assert skills is None
