"""Aggregations over stored traces for the Traces list and the Overview page."""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any

from agentcore.obs.storage import JSONLTraceStore, TraceSummary
from agentcore.server.query import TraceQuery, field_values, kind_of, parse_query

FACET_FIELDS = ("status", "kind", "model", "tool", "name")
SORT_KEYS = {
    "time": lambda s: s.start_time,
    "latency": lambda s: s.duration_ms,
    "tokens": lambda s: s.total_tokens,
    "cost": lambda s: s.cost_usd,
    "name": lambda s: s.name.lower(),
    "status": lambda s: s.status,
    "model": lambda s: s.model.lower(),
}


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
    query: TraceQuery | str | None = None,
    sort: str = "time",
    order: str = "desc",
) -> list[TraceSummary]:
    """Filter stored traces. ``query`` is the explorer's query language (see ``query.py``);
    the older ``q``/``status``/``model``/``kind`` parameters still work and combine with it."""
    tq = parse_query(query) if isinstance(query, str) or query is None else query
    items = store.list(None)
    needle = (q or "").strip().lower()
    out = []
    for s in items:
        if not tq.matches(s):
            continue
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
    if sort not in SORT_KEYS:
        raise ValueError(f"sort must be one of {', '.join(SORT_KEYS)}")
    if order not in ("asc", "desc"):
        raise ValueError("order must be asc or desc")
    if sort != "time" or order != "desc":
        out.sort(key=SORT_KEYS[sort], reverse=order == "desc")
    else:
        out.sort(key=lambda s: s.start_time, reverse=True)
    return out


def in_window(items: list[TraceSummary], since: float | None, until: float | None) -> list:
    return [
        s
        for s in items
        if (since is None or s.start_time >= since) and (until is None or s.start_time <= until)
    ]


def facet_counts(
    items: list[TraceSummary], query: TraceQuery, limit: int = 12
) -> dict[str, list[dict[str, Any]]]:
    """Per-value counts for each facet field.

    Counts for a field ignore the query's own clauses on that field (disjunctive faceting),
    so picking ``status:error`` still shows how many ``ok`` traces there are to switch to.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for name in FACET_FIELDS:
        sub = query.without(name)
        counts: dict[str, int] = {}
        for s in items:
            if not sub.matches(s):
                continue
            for v in set(field_values(name, s)):
                counts[v] = counts.get(v, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        out[name] = [{"value": v, "count": c} for v, c in ranked[:limit]]
        if len(ranked) > limit:
            out[name].append({"value": None, "count": sum(c for _, c in ranked[limit:])})
    return out


def histogram(
    items: list[TraceSummary],
    *,
    since: float | None = None,
    until: float | None = None,
    buckets: int = 48,
    now: float | None = None,
) -> dict[str, Any]:
    """Trace counts (and errors) over time in ``buckets`` equal slices of the window.

    Without an explicit window the range spans the matching traces (padded a little)."""
    times = [s.start_time for s in items]
    now = now or time.time()
    start = since if since is not None else (min(times) if times else now - 3600)
    end = until if until is not None else max(now, max(times) if times else now)
    if end <= start:
        end = start + 60
    if since is None and times:
        start -= (end - start) * 0.02
    width = (end - start) / buckets
    rows = [{"t": start + i * width, "count": 0, "errors": 0} for i in range(buckets)]
    for s in items:
        idx = int((s.start_time - start) // width)
        if 0 <= idx < buckets or (idx == buckets and s.start_time <= end):
            row = rows[min(idx, buckets - 1)]
            row["count"] += 1
            row["errors"] += int(s.status != "ok")
    return {"start": start, "end": end, "bucket_seconds": width, "buckets": rows}


def trace_stats(items: list[TraceSummary]) -> dict[str, Any]:
    lat = [s.duration_ms for s in items]
    cost = [s.cost_usd for s in items]
    tok = [float(s.total_tokens) for s in items]
    return {
        "count": len(items),
        "errors": sum(1 for s in items if s.status != "ok"),
        "p50_ms": round(percentile(lat, 0.5), 2),
        "p95_ms": round(percentile(lat, 0.95), 2),
        "p90_cost_usd": round(percentile(cost, 0.9), 6),
        "p90_tokens": round(percentile(tok, 0.9), 1),
    }


def explore(
    store: JSONLTraceStore,
    *,
    query: str | None = None,
    since: float | None = None,
    until: float | None = None,
    sort: str = "time",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    buckets: int = 48,
) -> dict[str, Any]:
    """Everything the trace explorer needs in one pass: a page of rows, the total, facet
    counts, a volume histogram and latency/cost percentiles for the quick filters."""
    tq = parse_query(query)
    everything = store.list(None)
    windowed = in_window(everything, since, until)
    matched = filter_traces(store, query=tq, since=since, until=until, sort=sort, order=order)
    hist_items = [s for s in windowed if tq.matches(s)]
    return {
        "query": tq.to_dict(),
        "total": len(matched),
        "items": [dict(s.to_dict(), kind=kind_of(s)) for s in matched[offset : offset + limit]],
        "facets": facet_counts(windowed, tq),
        "histogram": histogram(hist_items, since=since, until=until, buckets=buckets),
        "window": {"since": since, "until": until},
        "stats": trace_stats(windowed),
    }


def overview(
    store: JSONLTraceStore, *, days: float = 7, now: float | None = None, tz_offset_min: int = 0
) -> dict[str, Any]:
    """Aggregate agent runs. ``tz_offset_min`` is JS ``Date.getTimezoneOffset()`` so that
    daily buckets start at the viewer's local midnight."""
    now = now or time.time()
    since = now - days * 86400
    stored = store.list(None)
    all_items = [s for s in stored if s.start_time >= since]
    runs = [s for s in all_items if s.name.startswith("agent.run")]
    prev_items = [s for s in stored if since - days * 86400 <= s.start_time < since]
    prev_runs = [s for s in prev_items if s.name.startswith("agent.run")]
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
    tools = _tool_totals(all_items)
    top_tools = sorted(
        (
            {
                "name": name,
                "calls": int(t["calls"]),
                "errors": int(t["errors"]),
                "avg_ms": round(t["total_ms"] / t["calls"], 2) if t["calls"] else 0.0,
                "error_rate": round(t["errors"] / t["calls"], 4) if t["calls"] else 0.0,
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
        "kpis": _kpis(runs, tools),
        # The same KPIs for the window just before this one, for "vs previous period" deltas.
        "previous": _kpis(prev_runs, _tool_totals(prev_items)) if prev_items else None,
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


def _tool_totals(items: list[TraceSummary]) -> dict[str, dict[str, float]]:
    tools: dict[str, dict[str, float]] = {}
    for s in items:
        for name, t in s.tools.items():
            agg = tools.setdefault(name, {"calls": 0, "errors": 0, "total_ms": 0.0})
            for k in agg:
                agg[k] += t.get(k, 0)
    return tools


def _kpis(runs: list[TraceSummary], tools: dict[str, dict[str, float]]) -> dict[str, Any]:
    durations = [s.duration_ms for s in runs]
    errors = sum(1 for s in runs if s.status != "ok")
    return {
        "runs": len(runs),
        "errors": errors,
        "success_rate": round((len(runs) - errors) / len(runs), 4) if runs else None,
        "p50_ms": round(percentile(durations, 0.5), 2),
        "p95_ms": round(percentile(durations, 0.95), 2),
        "tokens": sum(s.total_tokens for s in runs),
        "cost_usd": round(sum(s.cost_usd for s in runs), 6),
        "tool_calls": int(sum(t["calls"] for t in tools.values())),
    }
