"""Unit tests for parsers."""

import json
from unittest.mock import AsyncMock

import pytest
from bs4 import BeautifulSoup

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

    def test_extracts_current_kwork_state_data(self, parser):
        """Kwork embeds projects into window.stateData instead of DOM cards."""
        state = {
            "wantsListData": {
                "pagination": {
                    "data": [
                        {
                            "id": 3228237,
                            "name": "Разработка Telegram-бота",
                            "description": "Нужен бот с PostgreSQL",
                            "priceLimit": "15000.00",
                            "max_days": "7",
                            "kwork_count": 3,
                            "user": {
                                "rating": "4,9",
                                "data": {"wants_count": "12"},
                            },
                        }
                    ]
                }
            }
        }
        html = (
            "<script>window.before=true;window.stateData="
            + json.dumps(state, ensure_ascii=False)
            + ";window.after=true;</script>"
        )

        extracted = parser._extract_json_data(BeautifulSoup(html, "html.parser"))
        cards = parser._parse_state_cards(extracted)

        assert len(cards) == 1
        assert cards[0]["kwork_id"] == "3228237"
        assert cards[0]["budget"] == "15000 ₽"
        assert cards[0]["deadline"] == "7 дней"
        assert cards[0]["proposals_count"] == 3
        assert cards[0]["customer_rating"] == 4.9
        assert cards[0]["customer_orders"] == 12
        assert cards[0]["_embedded_state"] is True

        vacancy = parser._build_vacancy_from_card(cards[0])
        assert vacancy is not None
        assert vacancy.kwork_id == "3228237"
        assert vacancy.budget_max == 15000
        assert vacancy.description == "Нужен бот с PostgreSQL"

    async def test_list_page_uses_state_data_without_dom_cards(self, parser):
        """Regression: the current JS-only list must not return an empty set."""
        state = {
            "wantsListData": {
                "pagination": {
                    "data": [
                        {
                            "id": 123456,
                            "name": "Новый проект",
                            "description": "Описание",
                            "priceLimit": 5000,
                            "max_days": 2,
                            "user": {"data": {}},
                        }
                    ]
                }
            }
        }
        page = AsyncMock()
        page.content.return_value = (
            "<html><body><div class='js-wants-list-preloaders'></div>"
            f"<script>window.stateData={json.dumps(state)};</script></body></html>"
        )
        context = AsyncMock()
        context.new_page.return_value = page
        parser._reserve_request = AsyncMock(return_value=True)

        cards = await parser._fetch_project_cards(context)

        assert [card["kwork_id"] for card in cards] == ["123456"]
        page.wait_for_selector.assert_awaited_once_with(
            ".want-card, .js-wants-list-preloaders",
            state="attached",
            timeout=20000,
        )
        page.close.assert_awaited_once()

    async def test_embedded_cards_skip_redundant_detail_requests(self, parser):
        """Встроенное полное описание не должно тратить лимит detail-страниц."""
        card = {
            "kwork_id": "123456",
            "url": "https://kwork.ru/projects/123456/view",
            "title": "Новый проект",
            "description": "Полное описание из stateData",
            "budget": "5000 ₽",
            "deadline": "2 дней",
            "_embedded_state": True,
        }
        context = AsyncMock()
        browser = AsyncMock()
        browser.new_context.return_value = context
        parser._can_make_request = AsyncMock(return_value=True)
        parser._get_browser = AsyncMock(return_value=browser)
        parser._fetch_project_cards = AsyncMock(return_value=[card])
        parser._fetch_detail_from_context = AsyncMock()
        parser.rate_limiter.sleep = AsyncMock()

        vacancies = await parser.fetch_vacancies()

        assert len(vacancies) == 1
        assert vacancies[0].description == "Полное описание из stateData"
        parser._fetch_detail_from_context.assert_not_awaited()
        parser.rate_limiter.sleep.assert_not_awaited()
        context.close.assert_awaited_once()

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
