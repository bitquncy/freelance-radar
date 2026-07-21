"""Unit tests for tracing system."""
import pytest
import time
from services.tracing import Tracer, Span


class TestSpan:
    def test_span_creation(self):
        """Test span creation."""
        span = Span(name="test", start_time=time.time())
        assert span.name == "test"
        assert span.span_id != ""
        assert span.status == "OK"

    def test_span_finish(self):
        """Test span finish."""
        span = Span(name="test", start_time=time.time())
        time.sleep(0.01)
        span.finish("OK")
        assert span.end_time > 0
        assert span.duration_ms() > 0

    def test_span_add_event(self):
        """Test span event addition."""
        span = Span(name="test", start_time=time.time())
        span.add_event("error", {"message": "test error"})
        assert len(span.events) == 1
        assert span.events[0]["name"] == "error"

    def test_span_set_attribute(self):
        """Test span attribute setting."""
        span = Span(name="test", start_time=time.time())
        span.set_attribute("key", "value")
        assert span.attributes["key"] == "value"

    def test_span_to_dict(self):
        """Test span to_dict conversion."""
        span = Span(name="test", start_time=time.time())
        span.finish()
        d = span.to_dict()
        assert d["name"] == "test"
        assert d["status"] == "OK"


class TestTracer:
    @pytest.fixture
    def tracer(self):
        return Tracer()

    def test_start_span(self, tracer):
        """Test span start."""
        span = tracer.start_span("test_operation")
        assert span.name == "test_operation"
        assert len(tracer._spans) == 1

    def test_end_span(self, tracer):
        """Test span end."""
        span = tracer.start_span("test_operation")
        tracer.end_span(span, "OK")
        assert span.end_time > 0

    def test_context_manager(self, tracer):
        """Test span context manager."""
        with tracer.span("test_operation") as span:
            assert span.name == "test_operation"
            assert span.end_time == 0
        assert span.end_time > 0

    def test_nested_spans(self, tracer):
        """Test nested spans with parent."""
        with tracer.span("parent") as parent:
            with tracer.span("child", parent_id=parent.span_id) as child:
                assert child.parent_id == parent.span_id

    def test_error_handling(self, tracer):
        """Test span error handling."""
        with pytest.raises(ValueError):
            with tracer.span("test_operation") as span:
                raise ValueError("test error")
        assert span.status == "OK"
        assert span.attributes.get("error") == "test error"

    def test_get_recent_spans(self, tracer):
        """Test getting recent spans."""
        tracer.start_span("span1")
        tracer.start_span("span2")
        tracer.start_span("span3")
        recent = tracer.get_recent_spans(2)
        assert len(recent) == 2

    def test_get_spans_by_name(self, tracer):
        """Test getting spans by name."""
        tracer.start_span("test")
        tracer.start_span("other")
        tracer.start_span("test")
        results = tracer.get_spans_by_name("test")
        assert len(results) == 2

    def test_get_stats(self, tracer):
        """Test tracing statistics."""
        tracer.start_span("test1")
        tracer.start_span("test2")
        stats = tracer.get_stats()
        assert stats["total_spans"] == 2

    def test_reset(self, tracer):
        """Test tracer reset."""
        tracer.start_span("test")
        tracer.reset()
        assert len(tracer._spans) == 0
