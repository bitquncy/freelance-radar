"""Metrics collection for monitoring and alerting.

Supports Prometheus-compatible export and in-memory collection.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from collections import defaultdict
import time
from datetime import datetime

from services.logger_config import get_logger

logger = get_logger(__name__)


@dataclass
class Counter:
    """Simple counter metric."""
    name: str
    description: str
    value: int = 0
    labels: Dict[str, str] = field(default_factory=dict)

    def inc(self, amount: int = 1) -> None:
        self.value += amount

    def reset(self) -> None:
        self.value = 0


@dataclass
class Gauge:
    """Simple gauge metric."""
    name: str
    description: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)

    def set(self, value: float) -> None:
        self.value = value

    def inc(self, amount: float = 1) -> None:
        self.value += amount

    def dec(self, amount: float = 1) -> None:
        self.value -= amount

    def reset(self) -> None:
        self.value = 0


@dataclass
class Histogram:
    """Simple histogram metric."""
    name: str
    description: str
    buckets: List[float] = field(default_factory=lambda: [0.1, 0.5, 1.0, 2.0, 5.0, 10.0])
    counts: Dict[float, int] = field(default_factory=lambda: defaultdict(int))
    sum_val: float = 0.0
    count: int = 0

    def observe(self, value: float) -> None:
        self.sum_val += value
        self.count += 1
        for bucket in self.buckets:
            if value <= bucket:
                self.counts[bucket] += 1

    def reset(self) -> None:
        self.counts = defaultdict(int)
        self.sum_val = 0.0
        self.count = 0


@dataclass
class Timer:
    """Timer metric for tracking durations."""
    name: str
    description: str
    start_time: float = 0.0
    durations: List[float] = field(default_factory=list)
    max_durations: int = 1000

    def start(self) -> None:
        self.start_time = time.time()

    def stop(self) -> float:
        duration = time.time() - self.start_time
        self.durations.append(duration)
        if len(self.durations) > self.max_durations:
            self.durations.pop(0)
        return duration

    def get_avg(self) -> float:
        if not self.durations:
            return 0.0
        return sum(self.durations) / len(self.durations)

    def get_p95(self) -> float:
        if not self.durations:
            return 0.0
        sorted_d = sorted(self.durations)
        idx = int(len(sorted_d) * 0.95)
        return sorted_d[min(idx, len(sorted_d) - 1)]

    def reset(self) -> None:
        self.durations.clear()
        self.start_time = 0.0


class MetricsCollector:
    """Collects and exposes metrics with Prometheus-compatible export."""

    def __init__(self):
        self.counters: Dict[str, Counter] = {}
        self.gauges: Dict[str, Gauge] = {}
        self.histograms: Dict[str, Histogram] = {}
        self.timers: Dict[str, Timer] = {}
        self._start_time = time.time()
        self._created_at = datetime.now().isoformat()

    def counter(self, name: str, description: str = "") -> Counter:
        """Get or create a counter."""
        if name not in self.counters:
            self.counters[name] = Counter(name=name, description=description)
        return self.counters[name]

    def gauge(self, name: str, description: str = "") -> Gauge:
        """Get or create a gauge."""
        if name not in self.gauges:
            self.gauges[name] = Gauge(name=name, description=description)
        return self.gauges[name]

    def histogram(self, name: str, description: str = "") -> Histogram:
        """Get or create a histogram."""
        if name not in self.histograms:
            self.histograms[name] = Histogram(name=name, description=description)
        return self.histograms[name]

    def timer(self, name: str, description: str = "") -> Timer:
        """Get or create a timer."""
        if name not in self.timers:
            self.timers[name] = Timer(name=name, description=description)
        return self.timers[name]

    def time(self, name: str) -> None:
        """Start a timer."""
        if name not in self.timers:
            self.timers[name] = Timer(name=name, description="")
        self.timers[name].start()

    def time_end(self, name: str) -> float:
        """End a timer and return duration."""
        if name not in self.timers:
            return 0.0
        return self.timers[name].stop()

    def get_all(self) -> Dict[str, Any]:
        """Get all metrics."""
        uptime = time.time() - self._start_time
        return {
            "uptime_seconds": uptime,
            "created_at": self._created_at,
            "counters": {
                k: {"value": v.value, "description": v.description}
                for k, v in self.counters.items()
            },
            "gauges": {
                k: {"value": v.value, "description": v.description}
                for k, v in self.gauges.items()
            },
            "histograms": {
                k: {
                    "count": v.count,
                    "sum": v.sum_val,
                    "avg": v.sum_val / v.count if v.count > 0 else 0,
                    "buckets": dict(v.counts),
                }
                for k, v in self.histograms.items()
            },
            "timers": {
                k: {
                    "count": len(v.durations),
                    "avg": v.get_avg(),
                    "p95": v.get_p95(),
                    "description": v.description,
                }
                for k, v in self.timers.items()
            },
        }

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        lines.append(f"# FreelanceRadar metrics (generated at {datetime.now().isoformat()})")

        # Uptime
        uptime = time.time() - self._start_time
        lines.append("# TYPE freelanceradar_uptime_seconds gauge")
        lines.append("# HELP freelanceradar_uptime_seconds Application uptime in seconds")
        lines.append(f"freelanceradar_uptime_seconds {uptime:.2f}")

        # Counters
        for name, counter in self.counters.items():
            safe_name = name.replace(".", "_")
            lines.append(f"# TYPE freelanceradar_{safe_name} counter")
            if counter.description:
                lines.append(f"# HELP freelanceradar_{safe_name} {counter.description}")
            labels = ""
            if counter.labels:
                label_str = ", ".join(f'{k}="{v}"' for k, v in counter.labels.items())
                labels = "{" + label_str + "}"
            lines.append(f"freelanceradar_{safe_name}{labels} {counter.value}")

        # Gauges
        for name, gauge in self.gauges.items():
            safe_name = name.replace(".", "_")
            lines.append(f"# TYPE freelanceradar_{safe_name} gauge")
            if gauge.description:
                lines.append(f"# HELP freelanceradar_{safe_name} {gauge.description}")
            lines.append(f"freelanceradar_{safe_name} {gauge.value}")

        # Histograms
        for name, hist in self.histograms.items():
            safe_name = name.replace(".", "_")
            lines.append(f"# TYPE freelanceradar_{safe_name} histogram")
            if hist.description:
                lines.append(f"# HELP freelanceradar_{safe_name} {hist.description}")
            for bucket, count in sorted(hist.counts.items()):
                lines.append(f"freelanceradar_{safe_name}_bucket{{le=\"{bucket}\"}} {count}")
            lines.append(f"freelanceradar_{safe_name}_bucket{{le=\"+Inf\"}} {hist.count}")
            lines.append(f"freelanceradar_{safe_name}_sum {hist.sum_val:.2f}")
            lines.append(f"freelanceradar_{safe_name}_count {hist.count}")

        # Timers (as histograms)
        for name, timer in self.timers.items():
            safe_name = name.replace(".", "_")
            if timer.durations:
                lines.append(f"# TYPE freelanceradar_{safe_name}_duration_seconds histogram")
                if timer.description:
                    lines.append(f"# HELP freelanceradar_{safe_name}_duration_seconds {timer.description}")
                lines.append(f"freelanceradar_{safe_name}_duration_seconds_count {len(timer.durations)}")
                lines.append(f"freelanceradar_{safe_name}_duration_seconds_sum {sum(timer.durations):.2f}")
                lines.append(f"freelanceradar_{safe_name}_duration_seconds_avg {timer.get_avg():.4f}")
                lines.append(f"freelanceradar_{safe_name}_duration_seconds_p95 {timer.get_p95():.4f}")

        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all metrics."""
        for c in self.counters.values():
            c.reset()
        for g in self.gauges.values():
            g.reset()
        for h in self.histograms.values():
            h.reset()
        for t in self.timers.values():
            t.reset()


# Global metrics collector
_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get or create global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics
