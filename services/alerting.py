"""Alerting system for FreelanceRadar bot.

Monitors for error patterns and sends alerts to the owner.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import deque

from services.logger_config import get_logger

logger = get_logger(__name__)


@dataclass
class Alert:
    """Alert data."""
    name: str
    level: str  # "warning", "error", "critical"
    message: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False


class AlertRule:
    """Alert rule definition."""

    def __init__(
        self,
        name: str,
        condition: callable,
        level: str = "warning",
        cooldown_seconds: int = 300,
        message_template: str = "",
    ):
        self.name = name
        self.condition = condition
        self.level = level
        self.cooldown_seconds = cooldown_seconds
        self.message_template = message_template
        self.last_triggered: Optional[datetime] = None
        self.trigger_count: int = 0

    def check(self, context: Dict[str, Any]) -> bool:
        """Check if the rule should trigger.

        Args:
            context: Dictionary with context data for the condition.

        Returns:
            True if alert should be triggered.
        """
        # Check cooldown
        if self.last_triggered:
            elapsed = (datetime.now() - self.last_triggered).total_seconds()
            if elapsed < self.cooldown_seconds:
                return False

        # Check condition
        try:
            if self.condition(context):
                self.last_triggered = datetime.now()
                self.trigger_count += 1
                return True
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            logger.error("alerting.rule_check_error", rule=self.name, error=str(e))

        return False

    def format_message(self, context: Dict[str, Any]) -> str:
        """Format alert message with context data."""
        try:
            return self.message_template.format(**context)
        except (KeyError, ValueError):
            return self.message_template


class AlertingService:
    """Alerting service that monitors for error patterns and sends alerts."""

    def __init__(self, max_history: int = 100):
        self._rules: Dict[str, AlertRule] = {}
        self._alerts: deque = deque(maxlen=max_history)
        self._error_counts: Dict[str, deque] = {}
        self._error_window_seconds = 600  # 10 minutes

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule."""
        self._rules[rule.name] = rule
        logger.debug("alerting.rule_added", rule_name=rule.name)

    def remove_rule(self, name: str) -> None:
        """Remove an alert rule."""
        self._rules.pop(name, None)

    def record_error(self, error_type: str, error_message: str) -> None:
        """Record an error for pattern detection."""
        now = datetime.now()
        if error_type not in self._error_counts:
            self._error_counts[error_type] = deque(maxlen=1000)

        self._error_counts[error_type].append(now)

        # Clean old entries
        cutoff = now - timedelta(seconds=self._error_window_seconds)
        self._error_counts[error_type] = deque(
            [t for t in self._error_counts[error_type] if t > cutoff],
            maxlen=1000,
        )

    def check_rules(self, context: Dict[str, Any]) -> List[Alert]:
        """Check all alert rules and return triggered alerts.

        Args:
            context: Dictionary with context data for rule conditions.

        Returns:
            List of triggered alerts.
        """
        triggered = []
        for rule in self._rules.values():
            if rule.check(context):
                alert = Alert(
                    name=rule.name,
                    level=rule.level,
                    message=rule.format_message(context),
                    timestamp=datetime.now(),
                    metadata=context,
                )
                self._alerts.append(alert)
                logger.warning(
                    "alerting.alert_triggered",
                    alert_name=rule.name,
                    level=rule.level,
                    message=alert.message,
                )
                triggered.append(alert)
        return triggered

    def get_error_count(self, error_type: str, window_seconds: int = 600) -> int:
        """Get error count for a specific type within a time window."""
        if error_type not in self._error_counts:
            return 0
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        return sum(1 for t in self._error_counts[error_type] if t > cutoff)

    def get_recent_alerts(self, limit: int = 100) -> List[Alert]:
        """Get recent alerts."""
        return list(self._alerts)[-limit:]

    def acknowledge_alert(self, index: int) -> bool:
        """Acknowledge an alert by index."""
        if 0 <= index < len(self._alerts):
            self._alerts[index].acknowledged = True
            return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get alerting statistics."""
        return {
            "rules": len(self._rules),
            "total_alerts": len(self._alerts),
            "unacknowledged": sum(1 for a in self._alerts if not a.acknowledged),
            "error_types": len(self._error_counts),
            "error_counts": {
                k: len(v) for k, v in self._error_counts.items()
            },
        }

    def reset(self) -> None:
        """Reset alerting state."""
        self._alerts.clear()
        self._error_counts.clear()
        for rule in self._rules.values():
            rule.last_triggered = None
            rule.trigger_count = 0


# Default alert rules
def setup_default_rules(alerting: AlertingService) -> None:
    """Set up default alert rules for common issues."""

    # Rule: More than 5 parsing errors in 10 minutes
    alerting.add_rule(AlertRule(
        name="parsing_errors_high",
        condition=lambda ctx: ctx.get("error_type", "") == "parsing" and ctx.get("error_count", 0) > 5,
        level="error",
        cooldown_seconds=600,
        message_template="Более 5 ошибок парсинга за 10 минут ({error_count} ошибок)",
    ))

    # Rule: Kwork blocked (captcha)
    alerting.add_rule(AlertRule(
        name="kwork_blocked",
        condition=lambda ctx: ctx.get("error_type", "") == "kwork_blocked",
        level="critical",
        cooldown_seconds=3600,
        message_template="Kwork заблокировал парсинг (captcha). Проверьте.",
    ))

    # Rule: OpenAI errors > 5 in a row
    alerting.add_rule(AlertRule(
        name="openai_errors_high",
        condition=lambda ctx: ctx.get("error_type", "") == "openai" and ctx.get("error_count", 0) > 5,
        level="error",
        cooldown_seconds=300,
        message_template="Более 5 ошибок OpenAI API ({error_count} ошибок).",
    ))

    # Rule: Monitor not running for > 40 minutes
    alerting.add_rule(AlertRule(
        name="monitor_down",
        condition=lambda ctx: ctx.get("minutes_since_check", 0) > 40,
        level="critical",
        cooldown_seconds=1800,
        message_template="Мониторинг не работает {minutes_since_check} минут.",
    ))


# Global alerting service
_alerting: Optional[AlertingService] = None


def get_alerting() -> AlertingService:
    """Get or create global alerting service."""
    global _alerting
    if _alerting is None:
        _alerting = AlertingService()
        setup_default_rules(_alerting)
    return _alerting
