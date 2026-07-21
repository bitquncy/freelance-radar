"""Unit tests for job analyzer."""
import pytest
from datetime import datetime

from services.job_analyzer import JobAnalyzer
from db.models import JobVacancy, FreelancerProfile


@pytest.fixture
def sample_vacancy():
    return JobVacancy(
        kwork_id="12345",
        url="https://kwork.ru/projects/12345/view",
        title="Python backend developer",
        description="Need Django developer for e-commerce project. Budget: 25000 rub. Deadline: 5 days.",
        budget="25000 ₽",
        budget_min=25000,
        budget_max=25000,
        deadline="5 дней",
        deadline_days=5,
        category="Programming",
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
        strong_sides="Fast delivery, clean code",
        hourly_rate=1500,
    )


class TestJobAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return JobAnalyzer()

    def test_build_system_prompt_without_profile(self, analyzer):
        """Test system prompt without profile."""
        prompt = analyzer._build_system_prompt()
        assert "помощник фрилансера" in prompt.lower()
        assert "score" in prompt.lower()
        assert "priority" in prompt.lower()

    def test_build_system_prompt_with_profile(self, analyzer, sample_profile):
        """Test system prompt includes profile."""
        prompt = analyzer._build_system_prompt(profile=sample_profile)
        assert "Python, Django, PostgreSQL" in prompt
        assert "3 лет" in prompt or "3" in prompt

    def test_build_system_prompt_with_custom(self, analyzer):
        """Test system prompt with custom prompt."""
        custom = "Only remote work"
        prompt = analyzer._build_system_prompt(custom_prompt=custom)
        assert "Only remote work" in prompt

    def test_build_user_prompt(self, analyzer, sample_vacancy):
        """Test user prompt construction."""
        prompt = analyzer._build_user_prompt(sample_vacancy)
        assert "Python backend developer" in prompt
        assert "25000" in prompt
        assert "5 дней" in prompt

    def test_build_user_prompt_with_profile(self, analyzer, sample_vacancy, sample_profile):
        """Test user prompt with profile context."""
        prompt = analyzer._build_user_prompt(sample_vacancy, sample_profile)
        assert "Python backend developer" in prompt
        # Profile info is in system prompt, not user prompt

    def test_error_response_format(self, analyzer):
        """Test error response has all required fields."""
        result = analyzer._error_response("Test error")
        assert result["suitable"] is False
        assert result["score"] == 0
        assert result["priority"] == "low"
        assert "Test error" in result["reason"]
        assert result["match_percentage"] == 0
        assert result["skills_required"] == []

    def test_format_profile_for_prompt(self, analyzer, sample_profile):
        """Test profile formatting."""
        text = analyzer._format_profile_for_prompt(sample_profile)
        assert "Python" in text
        assert "3" in text
        assert "1500" in text

    def test_format_profile_empty(self, analyzer):
        """Test empty profile formatting."""
        profile = FreelancerProfile(id=1, user_id=123)
        text = analyzer._format_profile_for_prompt(profile)
        assert "не заполнен" in text.lower() or text == "Профиль не заполнен."
