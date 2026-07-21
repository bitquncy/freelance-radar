"""Unit tests for vacancy filters."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from services.filters import VacancyFilter, quick_budget_filter
from db.models import JobVacancy, FreelancerProfile


@pytest.fixture
def sample_vacancy():
    return JobVacancy(
        kwork_id="12345",
        url="https://kwork.ru/projects/12345/view",
        title="Python backend developer needed",
        description="Need Django developer for e-commerce project",
        budget="15000 ₽",
        budget_min=15000,
        budget_max=15000,
        source="kwork",
        fetched_at=datetime.now(),
    )


@pytest.fixture
def sample_profile():
    return FreelancerProfile(
        id=1,
        user_id=123456,
        skills="Python, Django, PostgreSQL",
        experience_years=3,
        blacklist_words="test, internship, free",
        whitelist_words="python, django, backend",
    )


class TestVacancyFilter:
    def _make_profile(self, **kwargs):
        """Helper to create profile with all filter fields."""
        defaults = {
            'id': 1, 'user_id': 123456,
            'skills': 'Python, Django, PostgreSQL',
            'experience_years': 3,
            'blacklist_words': 'test, internship, free',
            'whitelist_words': 'python, django, backend',
            'min_budget': 10000,
            'max_budget': 50000,
        }
        defaults.update(kwargs)
        return FreelancerProfile(**defaults)

    @pytest.mark.asyncio
    async def test_pre_filter_budget_min(self, sample_vacancy):
        """Test minimum budget pre-filter."""
        sample_vacancy.budget_max = 5000
        filter_engine = VacancyFilter(self._make_profile())
        filter_engine.blacklist_service.check_vacancy = AsyncMock(return_value=False)
        keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
        assert not keep
        assert "budget_too_low" in reason

    @pytest.mark.asyncio
    async def test_pre_filter_budget_max(self, sample_vacancy):
        """Test maximum budget pre-filter."""
        sample_vacancy.budget_min = 60000
        filter_engine = VacancyFilter(self._make_profile())
        filter_engine.blacklist_service.check_vacancy = AsyncMock(return_value=False)
        keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
        assert not keep
        assert "budget_too_high" in reason

    @pytest.mark.asyncio
    async def test_pre_filter_blacklist(self, sample_vacancy):
        """Test blacklist word filter."""
        sample_vacancy.title = "Free internship for students"
        filter_engine = VacancyFilter(self._make_profile())
        filter_engine.blacklist_service.check_vacancy = AsyncMock(return_value=False)
        keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
        assert not keep
        assert "blacklist" in reason.lower()

    @pytest.mark.asyncio
    async def test_pre_filter_whitelist_no_match(self, sample_vacancy):
        """Test whitelist when no words match."""
        sample_vacancy.title = "Graphic designer needed"
        sample_vacancy.description = "Looking for Photoshop expert"
        filter_engine = VacancyFilter(self._make_profile())
        filter_engine.blacklist_service.check_vacancy = AsyncMock(return_value=False)
        keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
        assert not keep
        assert "no_whitelist" in reason.lower()

    @pytest.mark.asyncio
    async def test_pre_filter_pass(self, sample_vacancy):
        """Test that valid vacancy passes filters."""
        filter_engine = VacancyFilter(self._make_profile())
        filter_engine.blacklist_service.check_vacancy = AsyncMock(return_value=False)
        keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
        assert keep
        assert reason is None

    def test_post_filter_low_score(self, sample_vacancy):
        """Test post-filter with low AI score."""
        sample_vacancy.ai_score = 15
        filter_engine = VacancyFilter()
        keep, reason = filter_engine.apply_post_filters(sample_vacancy)
        assert not keep
        assert "ai_score_too_low" in reason.lower()

    def test_post_filter_low_match(self, sample_vacancy):
        """Test post-filter with low match percentage."""
        sample_vacancy.match_percentage = 10
        filter_engine = VacancyFilter()
        keep, reason = filter_engine.apply_post_filters(sample_vacancy)
        assert not keep
        assert "match_too_low" in reason.lower()

    def test_post_filter_pass(self, sample_vacancy):
        """Test post-filter with good scores."""
        sample_vacancy.ai_score = 80
        sample_vacancy.match_percentage = 75
        filter_engine = VacancyFilter()
        keep, reason = filter_engine.apply_post_filters(sample_vacancy)
        assert keep
        assert reason is None


class TestQuickBudgetFilter:
    def test_within_range(self):
        assert quick_budget_filter("Budget 15000 rub", 10000, 50000)

    def test_below_min(self):
        assert not quick_budget_filter("Budget 5000 rub", 10000, 50000)

    def test_above_max(self):
        assert not quick_budget_filter("Budget 60000 rub", 10000, 50000)

    def test_no_numbers(self):
        assert quick_budget_filter("No budget specified", 10000, 50000)
