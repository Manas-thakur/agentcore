"""Context-window management: token counting, budgets and truncation strategies."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from agentcore.types import Message

PER_MESSAGE_OVERHEAD = 4


class TokenCounter:
    """Counts tokens with ``tiktoken`` when installed, else a calibrated heuristic.

    The heuristic (~4 chars/token for English, words count as at least one token) is
    within ~10-15% of BPE tokenizers for typical prose, which is enough for budgeting.
    """

    def __init__(self, encoding: str = "cl100k_base"):
        self._enc: Any = None
        try:  # optional dependency
            import tiktoken

            self._enc = tiktoken.get_encoding(encoding)
        except Exception:
            self._enc = None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._enc is not None:
            return len(self._enc.encode(text))
        words = len(text.split())
        return max(words, math.ceil(len(text) / 4))

    def count_message(self, m: Message) -> int:
        n = PER_MESSAGE_OVERHEAD + self.count(m.content)
        for tc in m.tool_calls:
            n += self.count(tc.name) + self.count(json.dumps(tc.arguments))
        return n

    def count_messages(self, messages: list[Message]) -> int:
        return sum(self.count_message(m) for m in messages) + 2

    def count_tools(self, tools: list[dict[str, Any]] | None) -> int:
        return self.count(json.dumps(tools)) if tools else 0


@dataclass
class TokenBudget:
    """How the context window is split. ``history`` gets whatever is left."""

    context_window: int = 8192
    reserve_output: int = 1024
    max_tool_output: int = 2000  # per tool message, in tokens

    def available_for_input(self) -> int:
        return max(self.context_window - self.reserve_output, 64)


def _group_messages(messages: list[Message]) -> list[list[Message]]:
    """Group an assistant tool-call message with its tool results so they stay together."""
    groups: list[list[Message]] = []
    for m in messages:
        if (
            m.role == "tool"
            and groups
            and groups[-1][0].role == "assistant"
            and groups[-1][0].tool_calls
        ):
            groups[-1].append(m)
        else:
            groups.append([m])
    return groups


class ContextManager:
    """Fit a message list into a :class:`TokenBudget`.

    Strategy: (1) compress oversized tool outputs, (2) drop the oldest non-system turns,
    keeping tool-call/tool-result pairs intact and always keeping the latest user message.
    """

    def __init__(self, budget: TokenBudget | None = None, counter: TokenCounter | None = None):
        self.budget = budget or TokenBudget()
        self.counter = counter or TokenCounter()
        self.dropped_messages = 0

    def compress_tool_output(self, m: Message) -> Message:
        limit = self.budget.max_tool_output
        if m.role != "tool" or self.counter.count(m.content) <= limit:
            return m
        keep_chars = limit * 4
        head, tail = m.content[: keep_chars * 3 // 4], m.content[-keep_chars // 4 :]
        omitted = len(m.content) - len(head) - len(tail)
        content = f"{head}\n...[{omitted} chars omitted]...\n{tail}"
        return Message(role="tool", content=content, tool_call_id=m.tool_call_id, name=m.name)

    def fit(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> list[Message]:
        messages = [self.compress_tool_output(m) for m in messages]
        limit = self.budget.available_for_input() - self.counter.count_tools(tools)
        if self.counter.count_messages(messages) <= limit:
            return messages

        system = [m for m in messages if m.role == "system"]
        rest = [m for m in messages if m.role != "system"]
        groups = _group_messages(rest)
        # Never drop the latest user message (the task) or the final group (latest observation).
        user_groups = [g for g in groups if g[0].role == "user"]
        pinned = user_groups[-1] if user_groups else None

        def total() -> int:
            return self.counter.count_messages(system + [m for g in groups for m in g])

        while total() > limit:
            candidates = [i for i, g in enumerate(groups[:-1]) if g is not pinned]
            if not candidates:
                break
            self.dropped_messages += len(groups.pop(candidates[0]))
        # Leading orphan tool results are invalid for most providers.
        while groups and groups[0][0].role == "tool":
            self.dropped_messages += len(groups.pop(0))
        return system + [m for g in groups for m in g]
