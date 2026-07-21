"""Integration tests for handlers."""
import pytest

from services.formatters import format_vacancy_full, format_vacancy_notification
from db.models import JobVacancy


@pytest.fixture
def sample_vacancy():
    return JobVacancy(
        kwork_id="test_123",
        url="https://kwork.ru/projects/test",
        title="Test Project",
        description="Test description for vacancy",
        budget="10000",
        budget_min=5000,
        budget_max=20000,
        deadline="5 дней",
        deadline_days=5,
        category="IT",
        subcategory="Backend",
        skills='["Python", "Django"]',
        proposals_count=5,
        customer_rating=4.5,
        customer_orders=10,
        source="kwork",
        ai_score=75,
        ai_priority="high",
        ai_risks="No risks",
        match_percentage=80,
    )


def test_format_vacancy_full(sample_vacancy):
    """Test full vacancy formatting."""
    result = format_vacancy_full(sample_vacancy)
    assert "Test Project" in result
    assert "Python" in result
    assert "75" in result
    assert "80%" in result


def test_format_vacancy_notification(sample_vacancy):
    """Test notification formatting."""
    analysis = {
        "priority": "high",
        "score": 75,
        "match_percentage": 80,
    }
    result = format_vacancy_notification(sample_vacancy, analysis)
    assert "Test Project" in result
    assert "75" in result
    assert "80%" in result


def test_format_vacancy_notification_low_priority(sample_vacancy):
    """Test notification formatting with low priority."""
    analysis = {
        "priority": "low",
        "score": 30,
        "match_percentage": 20,
    }
    result = format_vacancy_notification(sample_vacancy, analysis)
    assert "Test Project" in result
    assert "30" in result
    assert "20%" in result
