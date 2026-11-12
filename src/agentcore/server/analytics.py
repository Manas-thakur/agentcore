"""Aggregations over stored traces for the Traces list and the Overview page."""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any

from agentcore.obs.storage import JSONLTraceStore, TraceSummary


def parse_time(value: str | float | None) -> float | None:
    """Accept epoch seconds or an ISO date/datetime string."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise ValueError(f"invalid time {value!r}; use epoch seconds or ISO 8601") from exc


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def filter_traces(
    store: JSONLTraceStore,
    *,
    q: str | None = None,
    status: str | None = None,
    model: str | None = None,
    kind: str | None = None,
    since: float | None = None,
    until: float | None = None,
) -> list[TraceSummary]:
    items = store.list(None)
    needle = (q or "").strip().lower()
    out = []
    for s in items:
        if status and s.status != status:
            continue
        if model and s.model != model:
            continue
        if kind == "agent" and not s.name.startswith("agent.run"):
            continue
        if kind == "eval" and not s.name.startswith("agent.run:eval:"):
            continue
        if since is not None and s.start_time < since:
            continue
        if until is not None and s.start_time > until:
            continue
        if needle:
            hay = " ".join([s.trace_id, s.name, s.model, s.input, s.output, s.error or ""]).lower()
            if needle not in hay:
                continue
        out.append(s)
    return out


def overview(
    store: JSONLTraceStore, *, days: float = 7, now: float | None = None, tz_offset_min: int = 0
) -> dict[str, Any]:
    """Aggregate agent runs. ``tz_offset_min`` is JS ``Date.getTimezoneOffset()`` so that
    daily buckets start at the viewer's local midnight."""
    now = now or time.time()
    since = now - days * 86400
    all_items = [s for s in store.list(None) if s.start_time >= since]
    runs = [s for s in all_items if s.name.startswith("agent.run")]
    durations = [s.duration_ms for s in runs]
    errors = sum(1 for s in runs if s.status != "ok")
    bucket = 3600 if days <= 2 else 86400
    shift = -tz_offset_min * 60
    start_bucket = math.floor((since + shift) / bucket) * bucket - shift
    n_buckets = int(math.ceil((now - start_bucket) / bucket)) or 1
    series: list[dict[str, Any]] = []
    grouped: dict[int, list[TraceSummary]] = {}
    for s in runs:
        idx = int((s.start_time - start_bucket) // bucket)
        grouped.setdefault(idx, []).append(s)
    for i in range(n_buckets):
        group = grouped.get(i, [])
        lat = [g.duration_ms for g in group]
        series.append(
            {
                "t": start_bucket + i * bucket,
                "runs": len(group),
                "errors": sum(1 for g in group if g.status != "ok"),
                "tokens": sum(g.total_tokens for g in group),
                "cost_usd": round(sum(g.cost_usd for g in group), 6),
                "p50_ms": round(percentile(lat, 0.5), 2),
                "p95_ms": round(percentile(lat, 0.95), 2),
            }
        )
    tools: dict[str, dict[str, float]] = {}
    for s in all_items:
        for name, t in s.tools.items():
            agg = tools.setdefault(name, {"calls": 0, "errors": 0, "total_ms": 0.0})
            for k in agg:
                agg[k] += t.get(k, 0)
    top_tools = sorted(
        (
            {
                "name": name,
                "calls": int(t["calls"]),
                "errors": int(t["errors"]),
                "avg_ms": round(t["total_ms"] / t["calls"], 2) if t["calls"] else 0.0,
            }
            for name, t in tools.items()
        ),
        key=lambda t: (-t["calls"], t["name"]),
    )
    models: dict[str, dict[str, float]] = {}
    for s in runs:
        m = models.setdefault(s.model or "unknown", {"runs": 0, "tokens": 0, "cost_usd": 0.0})
        m["runs"] += 1
        m["tokens"] += s.total_tokens
        m["cost_usd"] = round(m["cost_usd"] + s.cost_usd, 6)
    return {
        "range": {"days": days, "since": since, "until": now, "bucket_seconds": bucket},
        "kpis": {
            "runs": len(runs),
            "errors": errors,
            "success_rate": round((len(runs) - errors) / len(runs), 4) if runs else None,
            "p50_ms": round(percentile(durations, 0.5), 2),
            "p95_ms": round(percentile(durations, 0.95), 2),
            "tokens": sum(s.total_tokens for s in runs),
            "cost_usd": round(sum(s.cost_usd for s in runs), 6),
            "tool_calls": int(sum(t["calls"] for t in tools.values())),
        },
        "series": series,
        "top_tools": top_tools[:10],
        "models": [
            {"model": k, **v} for k, v in sorted(models.items(), key=lambda kv: -kv[1]["runs"])
        ],
        "recent_errors": [
            {"trace_id": s.trace_id, "name": s.name, "error": s.error, "start_time": s.start_time}
            for s in runs
            if s.status != "ok"
        ][:5],
    }
