"""Local-first trace storage: one JSONL file per trace, one span per line."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
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

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class JSONLTraceStore:
    """Span exporter + reader. Files live at ``<root>/<trace_id>.jsonl``."""

    def __init__(self, root: str | os.PathLike[str] = ".agentcore/traces"):
        self.root = Path(root)
        self._lock = threading.Lock()

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
        return TraceSummary(
            trace_id=trace_id,
            name=root.name,
            start_time=start,
            duration_ms=(end - start) * 1000,
            span_count=len(spans),
            status="error" if any(s.status == "error" for s in roots) else "ok",
            total_tokens=tokens,
            cost_usd=round(cost, 6),
            attributes=root.attributes,
        )

    def list(self, limit: int = 20) -> list[TraceSummary]:
        out = []
        for tid in self.trace_ids()[:limit]:
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
