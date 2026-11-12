"""In-process metrics: counters, gauges and histograms with Prometheus text export."""

from __future__ import annotations

import bisect
import threading
from typing import Any

DEFAULT_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000)


def _key(labels: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))


def _fmt_labels(key: tuple[tuple[str, str], ...], extra: dict[str, str] | None = None) -> str:
    items = list(key) + list((extra or {}).items())
    if not items:
        return ""
    body = ",".join(f'{k}="{v}"' for k, v in items)
    return "{" + body + "}"


class MetricsCollector:
    def __init__(self, buckets: tuple[float, ...] = DEFAULT_BUCKETS):
        self.buckets = tuple(sorted(buckets))
        self._counters: dict[str, dict[tuple, float]] = {}
        self._gauges: dict[str, dict[tuple, float]] = {}
        self._hist: dict[str, dict[tuple, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, value: float = 1.0, labels: dict[str, Any] | None = None) -> None:
        with self._lock:
            series = self._counters.setdefault(name, {})
            k = _key(labels)
            series[k] = series.get(k, 0.0) + value

    def gauge(self, name: str, value: float, labels: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._gauges.setdefault(name, {})[_key(labels)] = value

    def histogram(self, name: str, value: float, labels: dict[str, Any] | None = None) -> None:
        with self._lock:
            series = self._hist.setdefault(name, {})
            k = _key(labels)
            h = series.setdefault(
                k, {"counts": [0] * (len(self.buckets) + 1), "sum": 0.0, "count": 0}
            )
            h["counts"][bisect.bisect_left(self.buckets, value)] += 1
            h["sum"] += value
            h["count"] += 1

    def get_counter(self, name: str, labels: dict[str, Any] | None = None) -> float:
        return self._counters.get(name, {}).get(_key(labels), 0.0)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._hist.clear()

    def export_json(self) -> dict[str, Any]:
        def series(d: dict[tuple, Any]) -> list[dict[str, Any]]:
            return [{"labels": dict(k), "value": v} for k, v in d.items()]

        return {
            "counters": {n: series(s) for n, s in self._counters.items()},
            "gauges": {n: series(s) for n, s in self._gauges.items()},
            "histograms": {
                n: [
                    {
                        "labels": dict(k),
                        "count": h["count"],
                        "sum": h["sum"],
                        "buckets": dict(zip([*map(str, self.buckets), "+Inf"], h["counts"])),
                    }
                    for k, h in s.items()
                ]
                for n, s in self._hist.items()
            },
        }

    def export_prometheus(self) -> str:
        lines: list[str] = []
        for name, series in sorted(self._counters.items()):
            lines.append(f"# TYPE {name} counter")
            lines += [f"{name}{_fmt_labels(k)} {v}" for k, v in series.items()]
        for name, series in sorted(self._gauges.items()):
            lines.append(f"# TYPE {name} gauge")
            lines += [f"{name}{_fmt_labels(k)} {v}" for k, v in series.items()]
        for name, series in sorted(self._hist.items()):
            lines.append(f"# TYPE {name} histogram")
            for k, h in series.items():
                cumulative = 0
                for bound, count in zip([*self.buckets, "+Inf"], h["counts"]):
                    cumulative += count
                    lines.append(f"{name}_bucket{_fmt_labels(k, {'le': str(bound)})} {cumulative}")
                lines.append(f"{name}_sum{_fmt_labels(k)} {h['sum']}")
                lines.append(f"{name}_count{_fmt_labels(k)} {h['count']}")
        return "\n".join(lines) + "\n"


_metrics = MetricsCollector()


def get_metrics() -> MetricsCollector:
    return _metrics
