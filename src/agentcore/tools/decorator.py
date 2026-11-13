"""The ``@tool`` decorator: turn a typed Python function into an LLM-callable tool."""

from __future__ import annotations

import asyncio
import functools
import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, overload

from agentcore.tools.schema import function_to_schema
from agentcore.tools.validation import convert_to_python, validate_arguments


@dataclass
class Tool:
    """A tool definition: name, description, JSON Schema parameters and the callable."""

    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]
    category: str = "general"
    timeout: float | None = 30.0
    retries: int | None = None  # None: the ExecutionEngine's RetryPolicy decides; 0: never retry
    strict: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_async(self) -> bool:
        return inspect.iscoroutinefunction(self.fn)

    @property
    def required(self) -> list[str]:
        return list(self.parameters.get("required", []))

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Validate/coerce JSON arguments and convert them into Python values."""
        cleaned = validate_arguments(arguments, self.parameters, strict=self.strict)
        try:
            hints = typing.get_type_hints(self.fn, include_extras=True)
        except Exception:
            hints = {}
        return {k: convert_to_python(v, hints.get(k, Any)) for k, v in cleaned.items()}

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.fn(*args, **kwargs)

    async def acall(self, **kwargs: Any) -> Any:
        """Call the tool (sync or async) and await the result."""
        if self.is_async:
            return await self.fn(**kwargs)
        return await asyncio.to_thread(functools.partial(self.fn, **kwargs))

    def to_openai(self) -> dict[str, Any]:
        """OpenAI / vLLM / Ollama tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "category": self.category,
            "timeout": self.timeout,
        }


@overload
def tool(fn: Callable[..., Any]) -> Tool: ...


@overload
def tool(
    fn: None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    category: str = "general",
    timeout: float | None = 30.0,
    retries: int | None = None,
    strict: bool = False,
    **metadata: Any,
) -> Callable[[Callable[..., Any]], Tool]: ...


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    category: str = "general",
    timeout: float | None = 30.0,
    retries: int | None = None,
    strict: bool = False,
    **metadata: Any,
) -> Tool | Callable[[Callable[..., Any]], Tool]:
    """Create a :class:`Tool` from a function. Usable as ``@tool`` or ``@tool(...)``.

    ``retries``: how often a retryable failure (timeout, rate limit, ``ToolTransientError``)
    is retried. ``None`` (default) uses the engine's ``RetryPolicy.max_retries`` (2); ``0``
    disables retries for this tool.

    The JSON Schema is generated from type hints; parameter descriptions come from the
    docstring (Google, NumPy or Sphinx style).
    """

    def wrap(f: Callable[..., Any]) -> Tool:
        summary, params = function_to_schema(f)
        return Tool(
            name=name or f.__name__,
            description=description or summary or f.__name__.replace("_", " "),
            parameters=params,
            fn=f,
            category=category,
            timeout=timeout,
            retries=retries,
            strict=strict,
            metadata=metadata,
        )

    if fn is not None:
        return wrap(fn)
    return wrap


def as_tool(obj: Tool | Callable[..., Any]) -> Tool:
    """Coerce a plain function into a Tool (no-op for Tool instances)."""
    return obj if isinstance(obj, Tool) else tool(obj)
