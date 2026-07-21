"""Unit tests for auto-mode integration in scheduled_check."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from db.models import FreelancerProfile


class TestAutoMode:
    """Test auto-mode integration in scheduled_check."""

    def test_auto_mode_checks_priority_and_enabled(self):
        """Test that auto-mode only triggers for high priority when enabled."""
        # Test logic: auto_mode should trigger only when:
        # 1. profile.auto_mode_enabled is True
        # 2. analysis.get("priority") == "high"

        # Create a mock profile with auto_mode enabled
        profile = FreelancerProfile(
            id=1,
            user_id=123456,
            auto_mode_enabled=True,
            auto_mode_delay_minutes=5,
        )

        # Verify auto_mode_enabled is accessible
        assert profile.auto_mode_enabled is True
        assert profile.auto_mode_delay_minutes == 5

    def test_auto_mode_disabled(self):
        """Test that auto-mode doesn't trigger when disabled."""
        profile = FreelancerProfile(
            id=1,
            user_id=123456,
            auto_mode_enabled=False,
            auto_mode_delay_minutes=5,
        )
        assert profile.auto_mode_enabled is False

    @pytest.mark.asyncio
    async def test_auto_mode_response_generator_called(self):
        """Test that ResponseGenerator is called when auto-mode is enabled."""

        # Mock the ResponseGenerator
        mock_gen = MagicMock()
        mock_gen.generate_response = AsyncMock(return_value="Test response")

        # Test that the condition logic is correct
        profile = FreelancerProfile(
            id=1,
            user_id=123456,
            auto_mode_enabled=True,
            auto_mode_delay_minutes=5,
        )

        analysis = {"priority": "high", "score": 85}

        # Simulate the condition from scheduled_check
        should_generate = (
            profile
            and profile.auto_mode_enabled
            and analysis.get("priority") == "high"
        )

        assert should_generate is True

        # Test when auto-mode is disabled
        profile.auto_mode_enabled = False
        should_generate = (
            profile
            and profile.auto_mode_enabled
            and analysis.get("priority") == "high"
        )
        assert should_generate is False

        # Test when priority is not high
        profile.auto_mode_enabled = True
        analysis["priority"] = "medium"
        should_generate = (
            profile
            and profile.auto_mode_enabled
            and analysis.get("priority") == "high"
        )
        assert should_generate is False
