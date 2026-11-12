"""Local-first trace storage: one JSONL file per trace, one span per line."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentcore.obs.tracing import Span


@dataclass
class TraceSummary:
    trace_id: str
    name: str
    start_time: float
    duration_ms: float
    span_count: int
    status: str
    total_tokens: int
    cost_usd: float
    attributes: dict[str, Any]
    model: str = ""
    input: str = ""
    output: str = ""
    tool_calls: int = 0
    tool_errors: int = 0
    error: str | None = None
    tools: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class JSONLTraceStore:
    """Span exporter + reader. Files live at ``<root>/<trace_id>.jsonl``."""

    def __init__(self, root: str | os.PathLike[str] = ".agentcore/traces"):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, int, TraceSummary]] = {}

    # exporter protocol
    def export(self, span: Span) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(span.to_dict(), ensure_ascii=False)
        with self._lock, open(self.root / f"{span.trace_id}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    # reading
    def trace_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        files = sorted(self.root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.stem for p in files]

    def resolve(self, trace_id_or_prefix: str) -> str | None:
        ids = self.trace_ids()
        if trace_id_or_prefix in ids:
            return trace_id_or_prefix
        matches = [i for i in ids if i.startswith(trace_id_or_prefix)]
        return matches[0] if len(matches) == 1 else None

    def load(self, trace_id: str) -> list[Span]:
        path = self.root / f"{trace_id}.jsonl"
        if not path.exists():
            return []
        spans = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    spans.append(Span.from_dict(json.loads(line)))
        spans.sort(key=lambda s: s.start_time)
        return spans

    def summarize(self, trace_id: str) -> TraceSummary | None:
        """Summarize one trace (cached by file mtime/size, so listing stays cheap)."""
        path = self.root / f"{trace_id}.jsonl"
        try:
            st = path.stat()
        except OSError:
            return None
        cached = self._cache.get(trace_id)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            return cached[2]
        summary = self._summarize(trace_id)
        if summary is not None:
            self._cache[trace_id] = (st.st_mtime, st.st_size, summary)
        return summary

    def _summarize(self, trace_id: str) -> TraceSummary | None:
        spans = self.load(trace_id)
        if not spans:
            return None
        roots = [s for s in spans if s.parent_id is None] or spans
        root = roots[0]
        start = min(s.start_time for s in spans)
        end = max((s.end_time or s.start_time) for s in spans)
        tokens = sum(
            int(s.attributes.get("tokens.total", 0)) for s in spans if s.name == "model.generate"
        )
        cost = sum(
            float(s.attributes.get("cost.usd", 0.0)) for s in spans if s.name == "model.generate"
        )
        model = str(root.attributes.get("model") or "")
        if not model:
            model = next(
                (str(s.attributes["model"]) for s in spans if s.attributes.get("model")), ""
            )
        tools: dict[str, dict[str, float]] = {}
        for s in spans:
            if s.name != "tool.execute":
                continue
            name = str(s.attributes.get("tool.name", "?"))
            t = tools.setdefault(name, {"calls": 0, "errors": 0, "total_ms": 0.0})
            t["calls"] += 1
            t["errors"] += 0 if s.status == "ok" else 1
            t["total_ms"] += s.duration_ms
        error_span = next((s for s in roots if s.status == "error"), None)
        return TraceSummary(
            trace_id=trace_id,
            name=root.name,
            start_time=start,
            duration_ms=(end - start) * 1000,
            span_count=len(spans),
            status="error" if error_span is not None else "ok",
            total_tokens=tokens,
            cost_usd=round(cost, 6),
            attributes=root.attributes,
            model=model,
            input=str(root.attributes.get("task", ""))[:500],
            output=str(root.attributes.get("output", ""))[:500],
            tool_calls=int(sum(t["calls"] for t in tools.values())),
            tool_errors=int(sum(t["errors"] for t in tools.values())),
            error=error_span.error if error_span is not None else None,
            tools=tools,
        )

    def list(self, limit: int | None = 20) -> list[TraceSummary]:
        out = []
        ids = self.trace_ids()
        for tid in ids if limit is None else ids[:limit]:
            s = self.summarize(tid)
            if s:
                out.append(s)
        return out


def build_tree(spans: list[Span]) -> list[dict[str, Any]]:
    """Nest spans into a tree of ``{"span": Span, "children": [...]}``."""
    nodes = {s.span_id: {"span": s, "children": []} for s in spans}
    roots = []
    for s in spans:
        node = nodes[s.span_id]
        if s.parent_id and s.parent_id in nodes:
            nodes[s.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


def render_tree(spans: list[Span]) -> str:
    """Render a trace as an indented text tree."""
    lines: list[str] = []

    def walk(node: dict[str, Any], depth: int) -> None:
        s: Span = node["span"]
        attrs = {
            k: v
            for k, v in s.attributes.items()
            if k in ("model", "tool.name", "tokens.total", "cost.usd", "agent.name", "node", "step")
        }
        flag = "" if s.status == "ok" else f"  !! {s.error}"
        extra = " ".join(f"{k}={v}" for k, v in attrs.items())
        lines.append(f"{'  ' * depth}- {s.name} [{s.duration_ms:.1f} ms] {extra}{flag}".rstrip())
        for child in sorted(node["children"], key=lambda n: n["span"].start_time):
            walk(child, depth + 1)

    for root in build_tree(spans):
        walk(root, 0)
    return "\n".join(lines)
