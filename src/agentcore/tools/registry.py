"""ToolRegistry: a named collection of tools with provider-format export."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

from agentcore.tools.decorator import Tool, as_tool
from agentcore.tools.errors import ToolNotFoundError


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool | Callable[..., Any]] | None = None):
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, t: Tool | Callable[..., Any], *, replace: bool = False) -> Tool:
        t = as_tool(t)
        if t.name in self._tools and not replace:
            raise ValueError(f"tool {t.name!r} is already registered")
        self._tools[t.name] = t
        return t

    def register_many(self, tools: Iterable[Tool | Callable[..., Any]]) -> None:
        for t in tools:
            self.register(t)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotFoundError(
                f"unknown tool {name!r}; available: {sorted(self._tools)}"
            ) from None

    def list(self, category: str | None = None) -> list[Tool]:
        return [t for t in self._tools.values() if category is None or t.category == category]

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def subset(self, names: Iterable[str]) -> ToolRegistry:
        return ToolRegistry([self.get(n) for n in names])

    def to_openai(self) -> list[dict[str, Any]]:
        return [t.to_openai() for t in self._tools.values()]

    # Ollama and vLLM accept the OpenAI tool format.
    to_ollama = to_openai

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({self.names})"


def ensure_registry(tools: ToolRegistry | Iterable[Any] | None) -> ToolRegistry:
    if isinstance(tools, ToolRegistry):
        return tools
    return ToolRegistry(tools or [])
