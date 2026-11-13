"""ExecutionEngine: validate -> rate-limit -> run (with timeout) -> retry -> ToolResult."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agentcore.tools.errors import (
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRateLimitError,
    ToolTimeoutError,
    ToolValidationError,
)
from agentcore.tools.registry import ToolRegistry


@dataclass
class ToolResult:
    tool_name: str
    arguments: dict[str, Any]
    success: bool
    output: Any = None
    error: str | None = None
    error_type: str | None = None
    latency_ms: float = 0.0
    attempts: int = 1
    call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_text(self, max_chars: int = 8000) -> str:
        """Render the result as text for the model's tool message."""
        if not self.success:
            return f"ERROR ({self.error_type}): {self.error}"
        out = self.output
        if isinstance(out, str):
            text = out
        else:
            try:
                text = json.dumps(out, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                text = str(out)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[truncated {len(text) - max_chars} chars]"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "success": self.success,
            "output": self.output if _jsonable(self.output) else str(self.output),
            "error": self.error,
            "error_type": self.error_type,
            "latency_ms": round(self.latency_ms, 3),
            "attempts": self.attempts,
            "call_id": self.call_id,
        }


def _jsonable(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


@dataclass
class RetryPolicy:
    max_retries: int = 2
    base_delay_s: float = 0.2
    max_delay_s: float = 5.0
    jitter: bool = True
    retry_on: tuple[type[BaseException], ...] = (ToolTimeoutError, ToolRateLimitError)

    def delay(self, attempt: int) -> float:
        d = min(self.max_delay_s, self.base_delay_s * (2**attempt))
        return d * (0.5 + random.random() / 2) if self.jitter else d

    def should_retry(self, exc: BaseException) -> bool:
        return isinstance(exc, self.retry_on) or bool(getattr(exc, "retryable", False))


class TokenBucket:
    """Classic token-bucket rate limiter (``rate`` tokens per ``per`` seconds)."""

    def __init__(self, rate: int, per: float = 1.0):
        self.capacity = float(rate)
        self.tokens = float(rate)
        self.fill_rate = rate / per
        self.updated = time.monotonic()

    def try_acquire(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.fill_rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


BeforeHook = Callable[[str, dict[str, Any]], Any]
AfterHook = Callable[["ToolResult"], Any]
Middleware = BeforeHook


def _hooks(value: Any, name: str) -> list[Any]:
    """Accept one callable, a list/tuple of callables, or None."""
    if value is None:
        return []
    if callable(value):
        return [value]
    hooks = list(value)
    for h in hooks:
        if not callable(h):
            raise TypeError(f"{name} hooks must be callables, got {h!r}")
    return hooks


class ExecutionEngine:
    """Runs tool calls safely. Never raises for tool failures; returns ``ToolResult``."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        default_timeout: float | None = 30.0,
        retry_policy: RetryPolicy | None = None,
        max_concurrency: int = 8,
        rate_limits: dict[str, TokenBucket] | None = None,
        before: BeforeHook | list[BeforeHook] | None = None,
        after: AfterHook | list[AfterHook] | None = None,
    ):
        """``before(name, kwargs)`` runs after validation, ``after(result)`` on every result.

        Each may be a single callable or a list; sync or async.
        """
        self.registry = registry
        self.default_timeout = default_timeout
        self.retry_policy = retry_policy or RetryPolicy()
        self.max_concurrency = max_concurrency
        self._semaphores: dict[int, asyncio.Semaphore] = {}
        self.rate_limits = rate_limits or {}
        self.before: list[BeforeHook] = _hooks(before, "before")
        self.after: list[AfterHook] = _hooks(after, "after")

    async def execute(
        self, name: str, arguments: dict[str, Any] | None = None, call_id: str | None = None
    ) -> ToolResult:
        arguments = dict(arguments or {})
        start = time.perf_counter()
        attempts = 0
        try:
            t = self.registry.get(name)
            kwargs = t.validate(arguments)
            for hook in self.before:
                await _maybe_await(hook(name, kwargs))
            max_retries = self.retry_policy.max_retries if t.retries is None else max(t.retries, 0)
            timeout = t.timeout if t.timeout is not None else self.default_timeout
            while True:
                attempts += 1
                try:
                    bucket = self.rate_limits.get(name)
                    if bucket and not bucket.try_acquire():
                        raise ToolRateLimitError(f"rate limit exceeded for {name}")
                    async with self._semaphore():
                        output = await self._run(t.acall(**kwargs), timeout, name)
                    result = ToolResult(name, arguments, True, output=output)
                    break
                except Exception as exc:  # noqa: BLE001 - we classify below
                    if attempts <= max_retries and self.retry_policy.should_retry(exc):
                        await asyncio.sleep(self.retry_policy.delay(attempts - 1))
                        continue
                    raise
        except ToolError as exc:
            result = ToolResult(
                name, arguments, False, error=str(exc), error_type=type(exc).__name__
            )
        except Exception as exc:  # noqa: BLE001 - tool code can raise anything
            err = ToolExecutionError(f"{type(exc).__name__}: {exc}")
            result = ToolResult(
                name, arguments, False, error=str(err), error_type=type(err).__name__
            )
        result.latency_ms = (time.perf_counter() - start) * 1000
        result.attempts = max(attempts, 1)
        result.call_id = call_id
        for hook in self.after:
            await _maybe_await(hook(result))
        return result

    async def execute_many(
        self, calls: list[tuple[str, dict[str, Any], str | None]]
    ) -> list[ToolResult]:
        """Execute several calls concurrently, preserving order."""
        return list(await asyncio.gather(*(self.execute(n, a, c) for n, a, c in calls)))

    def _semaphore(self) -> asyncio.Semaphore:
        # One semaphore per event loop: engines may be reused across asyncio.run() calls.
        key = id(asyncio.get_running_loop())
        if key not in self._semaphores:
            self._semaphores = {key: asyncio.Semaphore(self.max_concurrency)}
        return self._semaphores[key]

    @staticmethod
    async def _run(coro: Awaitable[Any], timeout: float | None, name: str) -> Any:
        if timeout is None:
            return await coro
        try:
            return await asyncio.wait_for(coro, timeout)
        except asyncio.TimeoutError:
            raise ToolTimeoutError(f"tool {name!r} timed out after {timeout}s") from None


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value


__all__ = [
    "ExecutionEngine",
    "RetryPolicy",
    "TokenBucket",
    "ToolResult",
    "ToolNotFoundError",
    "ToolValidationError",
]
