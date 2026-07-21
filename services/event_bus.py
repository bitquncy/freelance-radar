"""Simple event bus for decoupled communication between services."""
import asyncio
import time
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass

from services.logger_config import get_logger

logger = get_logger(__name__)


# Event names used throughout the application
class Events:
    """Event name constants."""
    VACANCIES_FETCHED = "vacancies.fetched"
    VACANCY_PRE_FILTERED = "vacancy.pre_filtered"
    VACANCY_SAVED = "vacancy.saved"
    VACANCY_ANALYZED = "vacancy.analyzed"
    VACANCY_NOTIFIED = "vacancy.notified"
    VACANCY_FILTERED = "vacancy.filtered"
    VACANCY_RESPONDED = "vacancy.responded"
    VACANCY_BLACKLISTED = "vacancy.blacklisted"
    CHECK_STARTED = "check.started"
    CHECK_COMPLETED = "check.completed"
    CHECK_ERROR = "check.error"
    AUTO_MODE_TRIGGERED = "auto_mode.triggered"
    METRICS_UPDATED = "metrics.updated"


@dataclass
class Event:
    """Event data container."""
    name: str
    data: Any
    timestamp: float


class EventBus:
    """Simple async event bus for publish/subscribe pattern."""

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
        self._middleware: List[Callable] = []
        self._event_log: List[Event] = []
        self._max_log_size: int = 1000

    def subscribe(self, event_name: str, handler: Callable) -> None:
        """Subscribe handler to an event."""
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)
        logger.debug("event_bus.subscribed", event=event_name, handler=handler.__name__)

    def unsubscribe(self, event_name: str, handler: Callable) -> None:
        """Unsubscribe handler from an event."""
        if event_name in self._handlers:
            self._handlers[event_name] = [
                h for h in self._handlers[event_name] if h != handler
            ]

    def add_middleware(self, middleware: Callable) -> None:
        """Add middleware to process events."""
        self._middleware.append(middleware)

    async def publish(self, event_name: str, data: Any = None) -> None:
        """Publish an event to all subscribers."""
        event = Event(name=event_name, data=data, timestamp=time.time())

        # Log event
        if len(self._event_log) >= self._max_log_size:
            self._event_log.pop(0)
        self._event_log.append(event)

        # Run middleware
        for middleware in self._middleware:
            try:
                await middleware(event)
            except (ValueError, TypeError, AttributeError, KeyError, IndexError, RuntimeError) as e:
                logger.error("event_bus.middleware_error", error=str(e))

        # Notify subscribers
        handlers = self._handlers.get(event_name, [])
        if not handlers:
            return

        logger.debug("event_bus.published", event=event_name, handlers=len(handlers))

        tasks = []
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    tasks.append(asyncio.create_task(handler(event)))
                else:
                    handler(event)
            except (ValueError, TypeError, AttributeError, KeyError, IndexError, RuntimeError) as e:
                logger.error("event_bus.handler_error", event=event_name, error=str(e))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_recent_events(self, limit: int = 100) -> List[Event]:
        """Get recent events from the log."""
        return self._event_log[-limit:]

    def get_handler_count(self) -> Dict[str, int]:
        """Get number of handlers per event."""
        return {name: len(handlers) for name, handlers in self._handlers.items()}

    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        return {
            "events_published": len(self._event_log),
            "handlers": self.get_handler_count(),
            "middleware_count": len(self._middleware),
        }


# Global event bus instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
