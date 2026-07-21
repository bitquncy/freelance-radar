"""Simple tracing system for FreelanceRadar bot.

Provides span-based tracing without external dependencies.
Each span has a name, start time, end time, parent span, and attributes.
"""
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from contextlib import contextmanager

from services.logger_config import get_logger

logger = get_logger(__name__)


@dataclass
class Span:
    """A single tracing span."""
    name: str
    start_time: float
    end_time: float = 0.0
    parent_id: Optional[str] = None
    span_id: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "OK"

    def __post_init__(self):
        if not self.span_id:
            import hashlib
            self.span_id = hashlib.md5(
                f"{self.name}_{self.start_time}".encode()
            ).hexdigest()[:8]

    def finish(self, status: str = "OK") -> None:
        """Finish the span."""
        self.end_time = time.time()
        self.status = status

    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        if self.end_time == 0:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        """Add an event to the span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self.attributes[key] = value

    def to_dict(self) -> Dict[str, Any]:
        """Convert span to dictionary."""
        return {
            "name": self.name,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms(),
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


class Tracer:
    """Simple tracer for creating and managing spans."""

    def __init__(self):
        self._spans: List[Span] = []
        self._current_span: Optional[Span] = None
        self._max_spans: int = 1000

    def start_span(self, name: str, parent_id: Optional[str] = None) -> Span:
        """Start a new span.

        Args:
            name: Span name.
            parent_id: Parent span ID (optional).

        Returns:
            New span instance.
        """
        span = Span(
            name=name,
            start_time=time.time(),
            parent_id=parent_id or (self._current_span.span_id if self._current_span else None),
        )

        if len(self._spans) >= self._max_spans:
            self._spans.pop(0)

        self._spans.append(span)
        self._current_span = span
        return span

    def end_span(self, span: Span, status: str = "OK") -> None:
        """End a span.

        Args:
            span: Span to end.
            status: Span status (OK or ERROR).
        """
        span.finish(status)
        logger.debug(
            "tracing.span_completed",
            span_name=span.name,
            duration_ms=span.duration_ms(),
            status=status,
            span_id=span.span_id,
        )

    @contextmanager
    def span(self, name: str, parent_id: Optional[str] = None):
        """Context manager for a span.

        Usage:
            with tracer.span("my_operation"):
                do_work()
        """
        span = self.start_span(name, parent_id)
        try:
            yield span
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            span.set_attribute("error", str(e))
            span.set_attribute("error_type", type(e).__name__)
            span.add_event("error", {"message": str(e)})
            raise
        finally:
            self.end_span(span)

    async def async_span(self, name: str, parent_id: Optional[str] = None):
        """Async context manager for a span."""
        span = self.start_span(name, parent_id)
        try:
            yield span
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            span.set_attribute("error", str(e))
            span.set_attribute("error_type", type(e).__name__)
            span.add_event("error", {"message": str(e)})
            raise
        finally:
            self.end_span(span)

    def get_span(self, span_id: str) -> Optional[Span]:
        """Get a span by ID."""
        for span in self._spans:
            if span.span_id == span_id:
                return span
        return None

    def get_recent_spans(self, limit: int = 100) -> List[Span]:
        """Get recent spans."""
        return self._spans[-limit:]

    def get_spans_by_name(self, name: str) -> List[Span]:
        """Get all spans with a given name."""
        return [s for s in self._spans if s.name == name]

    def get_stats(self) -> Dict[str, Any]:
        """Get tracing statistics."""
        if not self._spans:
            return {"total_spans": 0, "avg_duration_ms": 0}

        durations = [s.duration_ms() for s in self._spans]
        return {
            "total_spans": len(self._spans),
            "avg_duration_ms": sum(durations) / len(durations),
            "max_duration_ms": max(durations),
            "min_duration_ms": min(durations),
            "error_count": sum(1 for s in self._spans if s.status == "ERROR"),
        }

    def to_trace(self, root_span_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Convert spans to trace format."""
        if root_span_id:
            # Build tree from root
            return self._build_trace_tree(root_span_id)
        return [s.to_dict() for s in self._spans]

    def _build_trace_tree(self, root_id: str) -> List[Dict[str, Any]]:
        """Build a trace tree from a root span."""
        root = self.get_span(root_id)
        if not root:
            return []

        result = [root.to_dict()]
        for span in self._spans:
            if span.parent_id == root_id:
                result.extend(self._build_trace_tree(span.span_id))
        return result

    def reset(self) -> None:
        """Reset all spans."""
        self._spans.clear()
        self._current_span = None


# Global tracer instance
_tracer: Optional[Tracer] = None


def get_tracer() -> Tracer:
    """Get or create global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
