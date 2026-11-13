"""Tracing: a dependency-free span recorder with an optional OpenTelemetry bridge.

Spans nest automatically via ``contextvars`` (works across ``await`` and
``asyncio.gather``). Finished spans are handed to exporters - by default none, so
tracing is a no-op until you call :func:`configure_tracing`.

If ``opentelemetry-api`` is installed and ``use_otel=True``, every span is mirrored as
an OpenTelemetry span so you can ship traces to any OTLP backend (Jaeger, Tempo, ...).
When an OpenTelemetry SDK tracer provider is configured, a root span takes the OTel trace
id as its AgentCore ``trace_id`` (same 32-hex format), so both systems share one id; every
mirrored span also carries ``agentcore.trace_id`` and ``agentcore.span_id`` attributes.
"""

from __future__ import annotations

import contextvars
import json
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

# Wall-clock anchor + monotonic high-resolution offset: time.time() has ~16 ms resolution
# on Windows, which would make sibling spans indistinguishable.
_WALL0 = time.time()
_PERF0 = time.perf_counter()


def now() -> float:
    """High-resolution wall-clock timestamp in seconds."""
    return _WALL0 + (time.perf_counter() - _PERF0)


_current_span: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "agentcore_current_span", default=None
)


@dataclass
class SpanEvent:
    name: str
    timestamp: float
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_id: str | None = None
    start_time: float = field(default_factory=now)
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None
    _otel: Any = field(default=None, repr=False)

    @property
    def duration_ms(self) -> float:
        end = self.end_time if self.end_time is not None else now()
        return (end - self.start_time) * 1000

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value
        if self._otel is not None:
            self._otel.set_attribute(key, _otel_value(value))

    def set_attributes(self, attrs: dict[str, Any]) -> None:
        for k, v in attrs.items():
            self.set_attribute(k, v)

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append(SpanEvent(name, now(), dict(attributes or {})))
        if self._otel is not None:
            self._otel.add_event(name, {k: _otel_value(v) for k, v in (attributes or {}).items()})

    def record_error(self, exc: BaseException | str) -> None:
        self.status = "error"
        self.error = (
            str(exc) if not isinstance(exc, BaseException) else f"{type(exc).__name__}: {exc}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 3),
            "attributes": _jsonable(self.attributes),
            "events": [
                {"name": e.name, "timestamp": e.timestamp, "attributes": _jsonable(e.attributes)}
                for e in self.events
            ],
            "status": self.status,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Span:
        return cls(
            name=d["name"],
            trace_id=d["trace_id"],
            span_id=d["span_id"],
            parent_id=d.get("parent_id"),
            start_time=d.get("start_time", 0.0),
            end_time=d.get("end_time"),
            attributes=d.get("attributes", {}),
            events=[
                SpanEvent(e["name"], e["timestamp"], e.get("attributes", {}))
                for e in d.get("events", [])
            ],
            status=d.get("status", "ok"),
            error=d.get("error"),
        )


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(k): _jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(v) for v in value]
        return str(value)


def _otel_value(value: Any) -> Any:
    if isinstance(value, (str, bool, int, float)):
        return value
    return json.dumps(_jsonable(value))


class SpanExporter(Protocol):
    def export(self, span: Span) -> None: ...


class InMemoryExporter:
    """Collects finished spans in a list (handy in tests and the server)."""

    def __init__(self) -> None:
        self.spans: list[Span] = []

    def export(self, span: Span) -> None:
        self.spans.append(span)

    def clear(self) -> None:
        self.spans.clear()


class ConsoleExporter:
    """Prints one line per finished span to stderr."""

    def export(self, span: Span) -> None:
        indent = "  " if span.parent_id else ""
        flag = "" if span.status == "ok" else f" ERROR {span.error}"
        print(f"[trace] {indent}{span.name} {span.duration_ms:.1f}ms{flag}", file=sys.stderr)


class Tracer:
    def __init__(
        self,
        exporters: list[SpanExporter] | None = None,
        *,
        enabled: bool = True,
        use_otel: bool = False,
        service_name: str = "agentcore",
    ):
        self.exporters: list[SpanExporter] = list(exporters or [])
        self.enabled = enabled
        self._otel_tracer = None
        if use_otel:
            try:
                from opentelemetry import trace as otel_trace

                self._otel_tracer = otel_trace.get_tracer(service_name)
            except ImportError:  # optional extra not installed
                self._otel_tracer = None

    @property
    def otel_enabled(self) -> bool:
        return self._otel_tracer is not None

    def add_exporter(self, exporter: SpanExporter) -> None:
        self.exporters.append(exporter)

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[Span]:
        parent = _current_span.get()
        span = Span(
            name=name,
            trace_id=parent.trace_id if parent else uuid.uuid4().hex,
            span_id=uuid.uuid4().hex[:16],
            parent_id=parent.span_id if parent else None,
            attributes=dict(attributes or {}),
        )
        otel_cm = None
        if self.enabled and self._otel_tracer is not None:
            otel_cm = self._otel_tracer.start_as_current_span(
                name, attributes={k: _otel_value(v) for k, v in span.attributes.items()}
            )
            span._otel = otel_cm.__enter__()
            _correlate_otel(span, is_root=parent is None)
        token = _current_span.set(span)
        try:
            yield span
        except BaseException as exc:
            span.record_error(exc)
            raise
        finally:
            _current_span.reset(token)
            span.end_time = now()
            if otel_cm is not None:
                if span.status == "error" and span._otel is not None:
                    try:
                        from opentelemetry.trace import Status, StatusCode

                        span._otel.set_status(Status(StatusCode.ERROR, span.error or ""))
                    except Exception:
                        pass
                otel_cm.__exit__(None, None, None)
            if self.enabled:
                for exp in self.exporters:
                    try:
                        exp.export(span)
                    except Exception as e:  # exporters must never break the app
                        print(f"[agentcore] span export failed: {e}", file=sys.stderr)


def _correlate_otel(span: Span, *, is_root: bool) -> None:
    """Share one trace id between AgentCore and OpenTelemetry."""
    try:
        ctx = span._otel.get_span_context()
        if is_root and getattr(ctx, "is_valid", False) and ctx.trace_id:
            span.trace_id = format(ctx.trace_id, "032x")  # API-only (no SDK) ids are invalid
        span._otel.set_attribute("agentcore.trace_id", span.trace_id)
        span._otel.set_attribute("agentcore.span_id", span.span_id)
    except Exception:  # never let the bridge break tracing
        pass


def current_span() -> Span | None:
    return _current_span.get()


def current_trace_id() -> str | None:
    s = _current_span.get()
    return s.trace_id if s else None


_global_tracer = Tracer(enabled=True)


def get_tracer() -> Tracer:
    return _global_tracer


def set_tracer(tracer: Tracer) -> Tracer:
    global _global_tracer
    _global_tracer = tracer
    return tracer


def configure_tracing(
    trace_dir: str | None = ".agentcore/traces",
    *,
    console: bool = False,
    use_otel: bool = False,
    extra_exporters: list[SpanExporter] | None = None,
) -> Tracer:
    """Configure the global tracer. Spans are written as JSONL into ``trace_dir``."""
    from agentcore.obs.storage import JSONLTraceStore

    exporters: list[SpanExporter] = []
    if trace_dir:
        exporters.append(JSONLTraceStore(trace_dir))
    if console:
        exporters.append(ConsoleExporter())
    exporters.extend(extra_exporters or [])
    return set_tracer(Tracer(exporters, use_otel=use_otel))
