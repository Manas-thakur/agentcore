"""A small query language for the trace explorer.

Examples::

    status:error -model:mock latency:>1.5s
    tool:calculator tokens:>=500 "division by zero"
    name:agent.run:eval:* cost:>0.01 -refund

Grammar (whitespace separated terms, ``"..."`` quotes a value or a phrase):

* ``field:value`` - a filter clause; prefix with ``-`` to negate it.
* numeric fields take a comparison: ``latency:>2s``, ``tokens:<=800``, ``cost:>0.01``
  (``=`` or no operator means equality). Latency accepts ``ms`` (default), ``s`` and ``m``.
* text fields match case-insensitively; ``*`` is a wildcard (``name:agent.run:*``) and a
  comma means "any of" (``model:mock,ollama:*``).
* anything else is free text, matched against id, name, model, input, output and error.

The parser is shared by the HTTP API and the tests; the web app has a mirror of the
tokenizer for highlighting but the server is the source of truth.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any

from agentcore.obs.storage import TraceSummary

TEXT_FIELDS = ("status", "model", "tool", "name", "id", "session", "kind")
NUMERIC_FIELDS = ("latency", "tokens", "cost", "steps", "spans", "tools")
ALIASES = {
    "duration": "latency",
    "lat": "latency",
    "level": "status",
    "trace": "id",
    "trace_id": "id",
    "session_id": "session",
    "token": "tokens",
    "usd": "cost",
    "type": "kind",
}
STATUS_VALUES = ("ok", "error")
KIND_VALUES = ("chat", "api", "openai", "eval", "tool", "other")
_OPS = (">=", "<=", "!=", ">", "<", "=")
_NUM_RE = re.compile(r"^(-?\d+(?:\.\d+)?|-?\.\d+)\s*([a-z]*)$", re.I)
_TOKEN_RE = re.compile(r'(-?)(?:([A-Za-z_][\w.]*):)?("(?:[^"\\]|\\.)*"?|\S+)')


class QueryError(ValueError):
    """Raised for a query that cannot be parsed. ``position`` is a character offset."""

    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.position = position


@dataclass
class Clause:
    field: str  # "" for free text
    value: Any
    op: str = "="
    negate: bool = False
    raw: str = ""
    options: list[str] = field(default_factory=list)  # text fields: any of these values

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field or "text",
            "op": self.op,
            "value": self.value,
            "negate": self.negate,
            "raw": self.raw,
        }


@dataclass
class TraceQuery:
    clauses: list[Clause] = field(default_factory=list)
    source: str = ""

    def without(self, field_name: str) -> TraceQuery:
        """The same query minus every clause on ``field_name`` (for facet counts)."""
        return TraceQuery([c for c in self.clauses if c.field != field_name], self.source)

    def matches(self, s: TraceSummary) -> bool:
        return all(_match(c, s) for c in self.clauses)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "clauses": [c.to_dict() for c in self.clauses]}


def _unquote(value: str) -> str:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    if value.startswith('"'):
        raise QueryError("unterminated quote")
    return value


def parse_number(field_name: str, text: str) -> float:
    m = _NUM_RE.match(text.strip())
    if not m:
        raise QueryError(f"{field_name}: expected a number, got {text!r}")
    num, unit = float(m.group(1)), m.group(2).lower()
    if field_name == "latency":
        scale = {"": 1.0, "ms": 1.0, "s": 1000.0, "sec": 1000.0, "m": 60000.0, "min": 60000.0}
        if unit not in scale:
            raise QueryError(f"latency: unknown unit {unit!r} (use ms, s or m)")
        return num * scale[unit]
    if field_name == "cost":
        if unit not in ("", "usd"):
            raise QueryError(f"cost: unknown unit {unit!r}")
        return num
    if unit in ("k",):
        return num * 1000
    if unit:
        raise QueryError(f"{field_name}: unexpected unit {unit!r}")
    return num


def parse_query(text: str | None) -> TraceQuery:
    """Parse a query string into clauses. Raises :class:`QueryError` on bad input."""
    source = (text or "").strip()
    clauses: list[Clause] = []
    for m in _TOKEN_RE.finditer(source):
        neg, key, value = m.group(1) == "-", m.group(2), m.group(3)
        raw = m.group(0)
        if key is None:
            dangling = re.fullmatch(r"([A-Za-z_][\w.]*):", value)
            if dangling:
                fname = ALIASES.get(dangling.group(1).lower(), dangling.group(1).lower())
                if fname in TEXT_FIELDS or fname in NUMERIC_FIELDS:
                    raise QueryError(f"{fname}: missing a value", m.start())
            try:
                phrase = _unquote(value)
            except QueryError as exc:
                raise QueryError(str(exc), m.start()) from None
            if not phrase or phrase == "-":
                continue
            clauses.append(Clause("", phrase.lower(), "contains", neg, raw))
            continue
        name = ALIASES.get(key.lower(), key.lower())
        if name not in TEXT_FIELDS and name not in NUMERIC_FIELDS:
            known = ", ".join(sorted({*TEXT_FIELDS, *NUMERIC_FIELDS}))
            raise QueryError(
                f"unknown field {key!r}; use one of: {known} (quote text that contains ':')",
                m.start(),
            )
        if name in NUMERIC_FIELDS:
            op = next((o for o in _OPS if value.startswith(o)), "=")
            rest = value[len(op) :] if value.startswith(op) else value
            if not rest:
                raise QueryError(f"{name}: missing a number after {op!r}", m.start())
            try:
                number = parse_number(name, _unquote(rest))
            except QueryError as exc:
                raise QueryError(str(exc), m.start()) from None
            clauses.append(Clause(name, number, op, neg, raw))
            continue
        try:
            val = _unquote(value)
        except QueryError as exc:
            raise QueryError(str(exc), m.start()) from None
        if not val:
            raise QueryError(f"{name}: missing a value", m.start())
        options = [val] if value.startswith('"') else [v for v in val.split(",") if v]
        if name == "status":
            options = [_status_value(v, m.start()) for v in options]
        if name == "kind" and any(v.lower() not in KIND_VALUES for v in options):
            raise QueryError(f"kind: use one of {', '.join(KIND_VALUES)}", m.start())
        clauses.append(Clause(name, ",".join(options), "=", neg, raw, options))
    return TraceQuery(clauses, source)


def _status_value(v: str, pos: int) -> str:
    v = {"err": "error", "errors": "error", "failed": "error", "success": "ok"}.get(
        v.lower(), v.lower()
    )
    if v not in STATUS_VALUES:
        raise QueryError("status: use ok or error", pos)
    return v


def kind_of(s: TraceSummary) -> str:
    """Where a trace came from, derived from its root span name."""
    name = s.name
    if name.startswith("agent.run:eval:"):
        return "eval"
    if name == "tool.invoke":
        return "tool"
    if name.startswith("agent.run:"):
        sub = name.split(":", 1)[1]
        return sub if sub in ("chat", "api", "openai") else "other"
    return "other"


def field_values(name: str, s: TraceSummary) -> list[str]:
    """String values a trace has for a text field (several for ``tool``)."""
    if name == "status":
        return [s.status]
    if name == "model":
        return [s.model] if s.model else []
    if name == "tool":
        return list(s.tools)
    if name == "name":
        return [s.name]
    if name == "id":
        return [s.trace_id]
    if name == "session":
        sid = s.attributes.get("session.id")
        return [str(sid)] if sid else []
    if name == "kind":
        return [kind_of(s)]
    return []


def numeric_value(name: str, s: TraceSummary) -> float:
    if name == "latency":
        return s.duration_ms
    if name == "tokens":
        return float(s.total_tokens)
    if name == "cost":
        return s.cost_usd
    if name == "steps":
        return float(s.attributes.get("steps") or 0)
    if name == "spans":
        return float(s.span_count)
    if name == "tools":
        return float(s.tool_calls)
    return 0.0


def _text_match(pattern: str, value: str, field_name: str) -> bool:
    p, v = pattern.lower(), value.lower()
    if "*" in p or "?" in p:
        return fnmatch.fnmatchcase(v, p)
    if field_name == "id":
        return v.startswith(p)
    return v == p


def _compare(a: float, op: str, b: float) -> bool:
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == "!=":
        return abs(a - b) > 1e-9
    return abs(a - b) <= 1e-9


def _match(c: Clause, s: TraceSummary) -> bool:
    if not c.field:
        hay = " ".join([s.trace_id, s.name, s.model, s.input, s.output, s.error or ""]).lower()
        hit = c.value in hay
    elif c.field in NUMERIC_FIELDS:
        hit = _compare(numeric_value(c.field, s), c.op, float(c.value))
    else:
        values = field_values(c.field, s)
        hit = any(_text_match(p, v, c.field) for p in c.options or [str(c.value)] for v in values)
    return hit != c.negate
