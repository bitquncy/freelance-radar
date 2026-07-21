"""Integration tests for monitor service."""
import pytest

from db.models import JobVacancy, FreelancerProfile
from services.filters import VacancyFilter


@pytest.fixture
def sample_vacancy():
    return JobVacancy(
        kwork_id="test_123",
        url="https://kwork.ru/projects/test",
        title="Test Project",
        description="Test description",
        budget="10000",
        budget_min=5000,
        budget_max=20000,
        deadline="5 дней",
        deadline_days=5,
        category="IT",
        skills='["Python", "Django"]',
        proposals_count=5,
        customer_rating=4.5,
        customer_orders=10,
        source="kwork",
    )


@pytest.fixture
def sample_profile():
    return FreelancerProfile(
        id=None,
        user_id=123,
        skills='["Python", "Django", "PostgreSQL"]',
        experience_years=3,
        preferred_categories='["IT", "Backend"]',
        hourly_rate=1500,
        min_budget=5000,
        max_budget=50000,
        min_customer_rating=3.0,
        max_proposals_count=20,
        whitelist_words='["Python", "Django"]',
        blacklist_words='["бесплатно", "тестовое"]',
    )


@pytest.mark.asyncio
async def test_pre_filters_budget(sample_vacancy, sample_profile):
    """Test budget pre-filter."""
    # Add whitelist words to title so whitelist filter passes
    sample_vacancy.title = "Python Django Backend Project"
    filter_engine = VacancyFilter(sample_profile)
    keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
    assert keep is True


@pytest.mark.asyncio
async def test_pre_filters_blacklist_word(sample_vacancy, sample_profile):
    """Test blacklist word pre-filter."""
    sample_vacancy.title = "Python Django Project"
    sample_vacancy.description = "Сделай бесплатно тестовое задание"
    filter_engine = VacancyFilter(sample_profile)
    keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
    assert keep is False
    assert "blacklist_word" in reason


@pytest.mark.asyncio
async def test_pre_filters_whitelist(sample_vacancy, sample_profile):
    """Test whitelist pre-filter."""
    sample_vacancy.title = "Обычное задание"
    sample_vacancy.description = "Сделай задание без навыков"
    filter_engine = VacancyFilter(sample_profile)
    keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
    assert keep is False
    assert "no_whitelist" in reason


@pytest.mark.asyncio
async def test_pre_filters_customer_rating(sample_vacancy, sample_profile):
    """Test customer rating pre-filter."""
    sample_vacancy.title = "Python Django Project"
    sample_vacancy.customer_rating = 2.0
    filter_engine = VacancyFilter(sample_profile)
    keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
    assert keep is False
    assert "customer_rating_too_low" in reason


@pytest.mark.asyncio
async def test_pre_filters_max_proposals(sample_vacancy, sample_profile):
    """Test max proposals pre-filter."""
    sample_vacancy.title = "Python Django Project"
    sample_vacancy.proposals_count = 25
    filter_engine = VacancyFilter(sample_profile)
    keep, reason = await filter_engine.apply_pre_filters(sample_vacancy)
    assert keep is False
    assert "too_many_proposals" in reason


@pytest.mark.asyncio
async def test_post_filters_low_score(sample_vacancy):
    """Test post-filter for low AI score."""
    sample_vacancy.ai_score = 20
    filter_engine = VacancyFilter()
    keep, reason = filter_engine.apply_post_filters(sample_vacancy)
    assert keep is False
    assert "ai_score_too_low" in reason


@pytest.mark.asyncio
async def test_post_filters_low_match(sample_vacancy):
    """Test post-filter for low match percentage."""
    sample_vacancy.match_percentage = 10
    filter_engine = VacancyFilter()
    keep, reason = filter_engine.apply_post_filters(sample_vacancy)
    assert keep is False
    assert "match_too_low" in reason


@pytest.mark.asyncio
async def test_post_filters_pass(sample_vacancy):
    """Test post-filter passing."""
    sample_vacancy.ai_score = 80
    sample_vacancy.match_percentage = 75
    filter_engine = VacancyFilter()
    keep, reason = filter_engine.apply_post_filters(sample_vacancy)
    assert keep is True
