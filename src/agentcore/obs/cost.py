"""Cost tracking with a per-model price table (USD per 1M tokens).

Prices change often - treat the defaults as examples and pass your own table to
:class:`CostTracker` (or edit ``PRICE_TABLE``). Local models (Ollama, vLLM, mock) cost $0.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# model name prefix -> (input $/1M tokens, output $/1M tokens)
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
    "llama-3.1-8b-instant": (0.05, 0.08),  # e.g. Groq
    "llama-3.3-70b-versatile": (0.59, 0.79),
}

LOCAL_PREFIXES = ("ollama:", "mock", "scripted", "replay", "vllm:")


def price_for(
    model: str, table: dict[str, tuple[float, float]] | None = None
) -> tuple[float, float]:
    """Look up a price by exact name, then longest matching prefix. Unknown -> free."""
    table = table if table is not None else PRICE_TABLE
    if model.startswith(LOCAL_PREFIXES):
        return (0.0, 0.0)
    provider, sep, rest = model.partition(":")
    name = (
        rest if sep and provider in ("openai", "groq", "lmstudio", "openai-compatible") else model
    )
    if name in table:
        return table[name]
    for prefix in sorted(table, key=len, reverse=True):
        if name.startswith(prefix):
            return table[prefix]
    return (0.0, 0.0)


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    table: dict[str, tuple[float, float]] | None = None,
) -> float:
    inp, out = price_for(model, table)
    return (prompt_tokens * inp + completion_tokens * out) / 1_000_000


@dataclass
class CostEntry:
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    agent: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class CostTracker:
    def __init__(self, price_table: dict[str, tuple[float, float]] | None = None):
        self.price_table = price_table if price_table is not None else PRICE_TABLE
        self.entries: list[CostEntry] = []
        self._lock = threading.Lock()

    def record(
        self, model: str, prompt_tokens: int, completion_tokens: int, agent: str | None = None
    ) -> CostEntry:
        cost = estimate_cost(model, prompt_tokens, completion_tokens, self.price_table)
        entry = CostEntry(model, prompt_tokens, completion_tokens, cost, agent)
        with self._lock:
            self.entries.append(entry)
        return entry

    @property
    def total_usd(self) -> float:
        return sum(e.cost_usd for e in self.entries)

    @property
    def total_tokens(self) -> int:
        return sum(e.prompt_tokens + e.completion_tokens for e in self.entries)

    def by_model(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for e in self.entries:
            out[e.model] = out.get(e.model, 0.0) + e.cost_usd
        return out

    def by_agent(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for e in self.entries:
            key = e.agent or "unknown"
            out[key] = out.get(key, 0.0) + e.cost_usd
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "total_usd": round(self.total_usd, 6),
            "total_tokens": self.total_tokens,
            "calls": len(self.entries),
            "by_model": {k: round(v, 6) for k, v in self.by_model().items()},
            "by_agent": {k: round(v, 6) for k, v in self.by_agent().items()},
        }
