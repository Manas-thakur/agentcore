"""The provider-neutral LLM interface."""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

import httpx

from agentcore.runtime.context import TokenCounter
from agentcore.types import ChatResponse, DoneEvent, Message, StreamEvent, TokenEvent, ToolCallEvent

T = TypeVar("T")

ToolSpecs = list[dict[str, Any]]  # OpenAI-style function tool definitions


class ModelError(RuntimeError):
    """Raised when a provider call fails permanently."""


class ModelClient(ABC):
    """Abstract chat model. Implementations normalize everything into ``ChatResponse``."""

    provider: str = "base"

    def __init__(self, model: str, *, max_retries: int = 2, timeout: float = 120.0):
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self._counter = TokenCounter()

    @property
    def model_id(self) -> str:
        """``provider:model`` identifier used for traces and cost lookup."""
        return f"{self.provider}:{self.model}"

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: ToolSpecs | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse: ...

    async def stream(
        self,
        messages: list[Message],
        tools: ToolSpecs | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream tokens. Default implementation buffers :meth:`generate`."""
        resp = await self.generate(messages, tools, temperature=temperature, max_tokens=max_tokens)
        if resp.content:
            yield TokenEvent(resp.content)
        for tc in resp.tool_calls:
            yield ToolCallEvent(tc)
        yield DoneEvent(resp)

    def count_tokens(self, messages: list[Message]) -> int:
        return self._counter.count_messages(messages)

    async def aclose(self) -> None:  # pragma: no cover - overridden by HTTP clients
        return None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.model!r})"


RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


async def with_retries(
    fn: Callable[[], Awaitable[T]], max_retries: int, base_delay: float = 0.5
) -> T:
    """Retry ``fn`` on transient HTTP errors with exponential backoff and jitter."""
    attempt = 0
    while True:
        try:
            return await fn()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in RETRYABLE_STATUS or attempt >= max_retries:
                body = exc.response.text[:500]
                raise ModelError(f"HTTP {exc.response.status_code}: {body}") from exc
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            if attempt >= max_retries:
                raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        delay = base_delay * (2**attempt) * (0.5 + random.random())
        attempt += 1
        await asyncio.sleep(delay)
