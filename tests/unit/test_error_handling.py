"""Unit tests for error handling improvements (no bare except Exception)."""
import pytest
from services.job_analyzer import JobAnalyzer
from db.models import JobVacancy, FreelancerProfile
from datetime import datetime


class TestJobAnalyzerErrorHandling:
    @pytest.fixture
    def analyzer(self):
        return JobAnalyzer()

    @pytest.fixture
    def sample_vacancy(self):
        return JobVacancy(
            kwork_id="12345",
            url="https://kwork.ru/projects/12345/view",
            title="Test",
            description="Test desc",
            source="kwork",
            fetched_at=datetime.now(),
        )

    @pytest.fixture
    def sample_profile(self):
        return FreelancerProfile(
            id=1, user_id=123456, skills="Python, Django"
        )

    def test_fallback_analysis_returns_valid_result(self, analyzer, sample_vacancy):
        """Test fallback analysis always returns valid structure."""
        result = analyzer._fallback_analysis(sample_vacancy, None)
        assert isinstance(result, dict)
        assert "suitable" in result
        assert "score" in result
        assert "priority" in result
        assert "match_percentage" in result
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100

    def test_error_response_format(self, analyzer):
        """Test error response has all required fields."""
        result = analyzer._error_response("Test error")
        assert result["suitable"] is False
        assert result["score"] == 0
        assert result["priority"] == "low"
        assert "Test error" in result["reason"]
        assert result["match_percentage"] == 0

    def test_clamp_int(self, analyzer):
        """Test _clamp_int helper."""
        assert analyzer._clamp_int(50, 0, 100) == 50
        assert analyzer._clamp_int(-10, 0, 100) == 0
        assert analyzer._clamp_int(150, 0, 100) == 100
        assert analyzer._clamp_int("invalid", 0, 100) == 0

    def test_validate_result_fixes_missing_fields(self, analyzer, sample_vacancy):
        """Test _validate_result fills missing fields."""
        incomplete = {"score": 50}
        result = analyzer._validate_result(incomplete, sample_vacancy, None)
        assert result["suitable"] is True  # score >= 50
        assert result["priority"] is not None
        assert result["match_percentage"] is not None
        assert "reason" in result
