"""Unit tests for formatters and text utilities."""
from services.text_utils import esc, esc_md, truncate


class TestEsc:
    def test_escape_html(self):
        """Test HTML escaping."""
        assert esc("<b>test</b>") == "&lt;b&gt;test&lt;/b&gt;"
        assert esc("test & more") == "test &amp; more"
        assert esc("") == ""

    def test_escape_none(self):
        """Test escaping None."""
        assert esc(None) == ""

    def test_escape_numbers(self):
        """Test escaping numbers."""
        assert esc(123) == "123"


class TestEscMd:
    def test_escape_markdown(self):
        """Test Markdown escaping."""
        result = esc_md("test_string")
        assert result.startswith("test")

    def test_escape_empty(self):
        """Test escaping empty string."""
        assert esc_md("") == ""


class TestTruncate:
    def test_truncate_short(self):
        """Test truncation of short text."""
        assert truncate("hello", 10) == "hello"

    def test_truncate_long(self):
        """Test truncation of long text."""
        result = truncate("hello world this is a long text", 10)
        assert len(result) <= 10
        assert result.endswith("\u2026")

    def test_truncate_none(self):
        """Test truncation of None."""
        assert truncate(None, 10) == ""


class TestFormatVacancy:
    def test_format_vacancy_full(self):
        """Test full vacancy formatting."""
        from services.formatters import format_vacancy_full
        from db.models import JobVacancy
        from datetime import datetime

        vacancy = JobVacancy(
            kwork_id="123",
            url="https://kwork.ru/123",
            title="Test",
            description="Test desc",
            source="kwork",
            fetched_at=datetime.now(),
        )
        result = format_vacancy_full(vacancy)
        assert "Test" in result
        assert "123" in result
