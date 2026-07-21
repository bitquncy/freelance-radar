"""Unit tests for metrics collection."""
import pytest
from services.metrics import MetricsCollector


class TestMetricsCollector:
    @pytest.fixture
    def collector(self):
        return MetricsCollector()

    def test_counter_inc(self, collector):
        """Test counter increment."""
        c = collector.counter("test_counter", "Test counter")
        c.inc()
        c.inc(5)
        assert c.value == 6

    def test_counter_reset(self, collector):
        """Test counter reset."""
        c = collector.counter("test_counter", "Test counter")
        c.inc(10)
        c.reset()
        assert c.value == 0

    def test_gauge_set(self, collector):
        """Test gauge set."""
        g = collector.gauge("test_gauge", "Test gauge")
        g.set(42)
        assert g.value == 42
        g.inc(8)
        assert g.value == 50
        g.dec(20)
        assert g.value == 30

    def test_histogram_observe(self, collector):
        """Test histogram observation."""
        h = collector.histogram("test_histogram", "Test histogram")
        h.observe(0.5)
        h.observe(2.0)
        h.observe(5.5)
        assert h.count == 3
        assert h.sum_val == 8.0
        assert h.counts[1.0] == 1
        assert h.counts[5.0] == 2
        assert h.counts[10.0] == 3

    def test_timer(self, collector):
        """Test timer."""
        t = collector.timer("test_timer", "Test timer")
        t.start()
        import time
        time.sleep(0.01)
        duration = t.stop()
        assert duration > 0
        assert len(t.durations) == 1

    def test_to_prometheus(self, collector):
        """Test Prometheus export."""
        collector.counter("test_counter", "Test counter").inc(5)
        collector.gauge("test_gauge", "Test gauge").set(10)
        output = collector.to_prometheus()
        assert "freelanceradar_test_counter" in output
        assert "freelanceradar_test_gauge" in output
        assert "5" in output
        assert "10" in output

    def test_get_all(self, collector):
        """Test get_all metrics."""
        collector.counter("c1").inc(1)
        collector.gauge("g1").set(42)
        result = collector.get_all()
        assert "counters" in result
        assert "gauges" in result
        assert "uptime_seconds" in result
        assert result["counters"]["c1"]["value"] == 1
        assert result["gauges"]["g1"]["value"] == 42

    def test_reset(self, collector):
        """Test reset all metrics."""
        collector.counter("c1").inc(5)
        collector.gauge("g1").set(42)
        collector.histogram("h1").observe(1.0)
        collector.reset()
        assert collector.get_all()["counters"]["c1"]["value"] == 0
        assert collector.get_all()["gauges"]["g1"]["value"] == 0
