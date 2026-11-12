"""Memory tiers: buffer, sliding window, summarizing, long-term (vector) and hybrid.

Memory holds conversation *across* agent runs (multi-turn chat). Within a single run the
agent keeps its own scratchpad of tool calls; only the user task and final answer are
written back to memory, which keeps memory compact and provider-valid.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentcore.runtime.context import TokenCounter
from agentcore.types import Message

if TYPE_CHECKING:
    from agentcore.embeddings import Embedder
    from agentcore.index.base import VectorIndex
    from agentcore.runtime.model_client import ModelClient


class Memory(ABC):
    kind = "base"

    @abstractmethod
    def add(self, message: Message) -> None: ...

    @abstractmethod
    def get_messages(self, query: str | None = None) -> list[Message]: ...

    @abstractmethod
    def clear(self) -> None: ...

    async def compact(self) -> None:
        """Called by the agent after each run; summarizing memories do their work here."""
        return None

    def add_many(self, messages: list[Message]) -> None:
        for m in messages:
            self.add(m)

    # serialization ---------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "messages": [m.to_dict() for m in self.get_messages()]}

    def load_dict(self, data: dict[str, Any]) -> None:
        self.clear()
        self.add_many([Message.from_dict(m) for m in data.get("messages", [])])

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def load(self, path: str | Path) -> None:
        self.load_dict(json.loads(Path(path).read_text(encoding="utf-8")))


class BufferMemory(Memory):
    """Short-term memory: the most recent messages within a message and/or token budget."""

    kind = "buffer"

    def __init__(self, max_messages: int | None = 50, max_tokens: int | None = None):
        self.max_messages = max_messages
        self.max_tokens = max_tokens
        self._messages: deque[Message] = deque()
        self._counter = TokenCounter()

    def add(self, message: Message) -> None:
        self._messages.append(message)
        while self.max_messages and len(self._messages) > self.max_messages:
            self._messages.popleft()
        while (
            self.max_tokens
            and len(self._messages) > 1
            and self._counter.count_messages(list(self._messages)) > self.max_tokens
        ):
            self._messages.popleft()

    def get_messages(self, query: str | None = None) -> list[Message]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def token_count(self) -> int:
        return self._counter.count_messages(list(self._messages))


class SlidingWindowMemory(Memory):
    """Keep the last ``max_turns`` turns (a turn starts at each user message)."""

    kind = "sliding_window"

    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self._turns: deque[list[Message]] = deque()

    def add(self, message: Message) -> None:
        if message.role == "user" or not self._turns:
            self._turns.append([])
        self._turns[-1].append(message)
        while len(self._turns) > self.max_turns:
            self._turns.popleft()

    def get_messages(self, query: str | None = None) -> list[Message]:
        return [m for turn in self._turns for m in turn]

    def clear(self) -> None:
        self._turns.clear()


SUMMARY_PROMPT = (
    "Summarize the conversation below for your own future reference. Preserve: (a) the "
    "user's core objective, (b) constraints and preferences, (c) facts and partial results "
    "obtained, (d) open questions or pending sub-tasks. Use terse bullet points.\n\n"
)


class SummarizingMemory(Memory):
    """When the transcript exceeds ``max_tokens``, older messages are folded into a summary.

    The most recent ``keep_recent`` messages are always kept verbatim.
    """

    kind = "summarizing"

    def __init__(self, model: ModelClient, max_tokens: int = 2000, keep_recent: int = 4):
        self.model = model
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent
        self.summary: str = ""
        self.summarized_count = 0
        self._messages: list[Message] = []
        self._counter = TokenCounter()

    def add(self, message: Message) -> None:
        self._messages.append(message)

    def get_messages(self, query: str | None = None) -> list[Message]:
        prefix = (
            [Message.system(f"Summary of the earlier conversation:\n{self.summary}")]
            if self.summary
            else []
        )
        return prefix + list(self._messages)

    def clear(self) -> None:
        self._messages.clear()
        self.summary = ""
        self.summarized_count = 0

    def needs_compaction(self) -> bool:
        return (
            len(self._messages) > self.keep_recent
            and self._counter.count_messages(self.get_messages()) > self.max_tokens
        )

    async def compact(self) -> None:
        if not self.needs_compaction():
            return
        old, recent = self._messages[: -self.keep_recent], self._messages[-self.keep_recent :]
        transcript = "\n".join(f"{m.role}: {m.content}" for m in old if m.content)
        if self.summary:
            transcript = f"Previous summary:\n{self.summary}\n\nNew messages:\n{transcript}"
        resp = await self.model.generate([Message.user(SUMMARY_PROMPT + transcript)])
        self.summary = resp.content.strip()
        self.summarized_count += len(old)
        self._messages = recent

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "summarized_count": self.summarized_count,
            "messages": [m.to_dict() for m in self._messages],
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        self.summary = data.get("summary", "")
        self.summarized_count = data.get("summarized_count", 0)
        self._messages = [Message.from_dict(m) for m in data.get("messages", [])]


@dataclass
class MemoryRecord:
    content: str
    importance: float = 5.0
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    score: float = 0.0


_IMPORTANT = re.compile(
    r"\b(remember|my name|i am|i'm|prefer|always|never|important|deadline|password|allergic|favorite|favourite)\b",
    re.I,
)


def heuristic_importance(text: str) -> float:
    """Cheap 1-10 importance score: explicit cues and specific facts score higher."""
    score = 3.0 + min(len(text) / 200, 2.0)
    if _IMPORTANT.search(text):
        score += 4.0
    if re.search(r"\d", text):
        score += 1.0
    return min(score, 10.0)


class LongTermMemory(Memory):
    """Vector-backed memory: store facts, retrieve the most relevant ones per query.

    Retrieved memories are injected as a single system message.
    """

    kind = "long_term"

    def __init__(
        self,
        embedder: Embedder | None = None,
        index: VectorIndex | None = None,
        *,
        k: int = 3,
        min_score: float = 0.2,
        min_importance: float = 0.0,
        importance_fn: Any = heuristic_importance,
    ):
        from agentcore.embeddings import HashingEmbedder
        from agentcore.index.flat import FlatIndex

        self.embedder = embedder or HashingEmbedder()
        self.index = index or FlatIndex(self.embedder.dimension or 384)
        self.k = k
        self.min_score = min_score
        self.min_importance = min_importance
        self.importance_fn = importance_fn
        self.records: dict[str, MemoryRecord] = {}

    def remember(
        self, content: str, importance: float | None = None, **metadata: Any
    ) -> MemoryRecord:
        rec = MemoryRecord(
            content, importance if importance is not None else self.importance_fn(content), metadata
        )
        if rec.importance < self.min_importance:
            return rec
        self.records[rec.id] = rec
        self.index.add(self.embedder.embed([content]), [rec.id])
        return rec

    def recall(self, query: str, k: int | None = None) -> list[MemoryRecord]:
        if not self.records:
            return []
        hits = self.index.search(self.embedder.embed_one(query), (k or self.k) * 2)
        out = []
        for h in hits:
            rec = self.records.get(h.id)
            if rec is None or h.score < self.min_score:
                continue
            rec.score = h.score
            out.append(rec)
        # importance breaks near-ties: rank by similarity weighted slightly by importance
        out.sort(key=lambda r: -(r.score * (0.9 + r.importance / 100)))
        return out[: k or self.k]

    def forget(self, record_id: str) -> None:
        self.records.pop(record_id, None)
        self.index.delete([record_id])

    # Memory protocol
    def add(self, message: Message) -> None:
        if message.role in ("user", "assistant") and message.content.strip():
            self.remember(f"{message.role}: {message.content}", role=message.role)

    def get_messages(self, query: str | None = None) -> list[Message]:
        if not query:
            return []
        recalled = self.recall(query)
        if not recalled:
            return []
        body = "\n".join(f"- {r.content}" for r in recalled)
        return [Message.system(f"Relevant information from long-term memory:\n{body}")]

    def clear(self) -> None:
        self.index.delete(list(self.records))
        self.records.clear()

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "records": [r.__dict__ for r in self.records.values()]}

    def load_dict(self, data: dict[str, Any]) -> None:
        self.clear()
        for r in data.get("records", []):
            rec = MemoryRecord(**{k: v for k, v in r.items() if k != "score"})
            self.records[rec.id] = rec
            self.index.add(self.embedder.embed([rec.content]), [rec.id])


class HybridMemory(Memory):
    """Short-term window + long-term recall."""

    kind = "hybrid"

    def __init__(self, short_term: Memory | None = None, long_term: LongTermMemory | None = None):
        self.short_term = short_term or SlidingWindowMemory(5)
        self.long_term = long_term or LongTermMemory()

    def add(self, message: Message) -> None:
        self.short_term.add(message)
        self.long_term.add(message)

    def get_messages(self, query: str | None = None) -> list[Message]:
        recent = self.short_term.get_messages(query)
        recalled = self.long_term.get_messages(query)
        return recalled + recent

    def clear(self) -> None:
        self.short_term.clear()
        self.long_term.clear()

    async def compact(self) -> None:
        await self.short_term.compact()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "short_term": self.short_term.to_dict(),
            "long_term": self.long_term.to_dict(),
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        self.short_term.load_dict(data.get("short_term", {}))
        self.long_term.load_dict(data.get("long_term", {}))


# Plan-compatible alias
ShortTermMemory = BufferMemory
