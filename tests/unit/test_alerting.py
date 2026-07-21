"""Unit tests for alerting system."""
import pytest
from services.alerting import AlertingService, AlertRule, setup_default_rules


class TestAlertRule:
    def test_rule_creation(self):
        """Test rule creation."""
        rule = AlertRule(
            name="test_rule",
            condition=lambda ctx: ctx.get("count", 0) > 5,
            level="warning",
        )
        assert rule.name == "test_rule"
        assert rule.level == "warning"

    def test_rule_triggers(self):
        """Test rule triggers when condition is met."""
        rule = AlertRule(
            name="test_rule",
            condition=lambda ctx: ctx.get("count", 0) > 5,
            level="warning",
        )
        assert rule.check({"count": 10}) is True
        assert rule.last_triggered is not None
        assert rule.trigger_count == 1

    def test_rule_cooldown(self):
        """Test rule cooldown."""
        rule = AlertRule(
            name="test_rule",
            condition=lambda ctx: True,
            cooldown_seconds=60,
        )
        rule.check({})
        assert rule.check({}) is False  # Should be blocked by cooldown

    def test_rule_format_message(self):
        """Test message formatting."""
        rule = AlertRule(
            name="test_rule",
            condition=lambda ctx: True,
            message_template="Error: {error}",
        )
        msg = rule.format_message({"error": "test error"})
        assert msg == "Error: test error"


class TestAlertingService:
    @pytest.fixture
    def service(self):
        return AlertingService()

    def test_record_error(self, service):
        """Test error recording."""
        service.record_error("test_error", "test message")
        assert service.get_error_count("test_error") == 1

    def test_check_rules(self, service):
        """Test rule checking."""
        service.add_rule(AlertRule(
            name="test",
            condition=lambda ctx: ctx.get("error_count", 0) > 5,
            level="error",
        ))
        alerts = service.check_rules({"error_type": "test", "error_count": 10})
        assert len(alerts) == 1
        assert alerts[0].name == "test"

    def test_get_recent_alerts(self, service):
        """Test getting recent alerts."""
        service.add_rule(AlertRule(
            name="test",
            condition=lambda ctx: True,
            level="warning",
            cooldown_seconds=0,
        ))
        service.check_rules({})
        service.check_rules({})
        alerts = service.get_recent_alerts(10)
        assert len(alerts) == 2

    def test_acknowledge_alert(self, service):
        """Test alert acknowledgment."""
        service.add_rule(AlertRule(
            name="test",
            condition=lambda ctx: True,
            level="warning",
        ))
        service.check_rules({})
        assert service.acknowledge_alert(0) is True
        alerts = service.get_recent_alerts()
        assert alerts[0].acknowledged is True

    def test_get_stats(self, service):
        """Test statistics."""
        service.add_rule(AlertRule(
            name="test",
            condition=lambda ctx: True,
        ))
        stats = service.get_stats()
        assert stats["rules"] == 1
        assert stats["total_alerts"] == 0

    def test_reset(self, service):
        """Test reset."""
        service.add_rule(AlertRule(
            name="test",
            condition=lambda ctx: True,
        ))
        service.check_rules({})
        service.reset()
        assert len(service.get_recent_alerts()) == 0


class TestSetupDefaultRules:
    def test_default_rules_created(self):
        """Test that default rules are created."""
        service = AlertingService()
        setup_default_rules(service)
        assert "parsing_errors_high" in service._rules
        assert "kwork_blocked" in service._rules
        assert "openai_errors_high" in service._rules
        assert "monitor_down" in service._rules
