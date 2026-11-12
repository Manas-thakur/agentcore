"""Ollama provider using the native ``/api/chat`` endpoint (with tool calling)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from agentcore.runtime.model_client import ModelClient, ModelError, ToolSpecs, with_retries
from agentcore.types import (
    ChatResponse,
    DoneEvent,
    Message,
    StreamEvent,
    TokenEvent,
    ToolCall,
    ToolCallEvent,
    Usage,
    new_id,
)

DEFAULT_OLLAMA_HOST = "http://localhost:11434"


def ollama_host() -> str:
    host = os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    if host.count(":") == 1:  # "http://somehost" without a port
        host += ":11434"
    return host.replace("0.0.0.0", "localhost")


def to_ollama_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        d: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            d["tool_calls"] = [
                {"function": {"name": tc.name, "arguments": tc.arguments}} for tc in m.tool_calls
            ]
        if m.role == "tool" and m.name:
            d["tool_name"] = m.name
        out.append(d)
    return out


def parse_ollama_tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
    calls = []
    for tc in raw or []:
        fn = tc.get("function", {})
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"__raw__": args}
        calls.append(
            ToolCall(name=fn.get("name", ""), arguments=args, id=tc.get("id") or new_id("call_"))
        )
    return calls


class OllamaClient(ModelClient):
    provider = "ollama"

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        *,
        host: str | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ):
        super().__init__(model, **kwargs)
        self.host = (host or ollama_host()).rstrip("/")
        self.options = options or {}
        self.keep_alive = keep_alive
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.host, timeout=self.timeout, transport=self._transport
        )

    def _payload(
        self,
        messages: list[Message],
        tools: ToolSpecs | None,
        temperature: float,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        options = {"temperature": temperature, **self.options}
        if max_tokens:
            options["num_predict"] = max_tokens
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": to_ollama_messages(messages),
            "stream": stream,
            "options": options,
        }
        if tools:
            payload["tools"] = tools
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        return payload

    async def generate(
        self,
        messages: list[Message],
        tools: ToolSpecs | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        payload = self._payload(messages, tools, temperature, max_tokens, stream=False)
        start = time.perf_counter()

        async def call() -> dict[str, Any]:
            async with self._client() as client:
                resp = await client.post("/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()

        data = await with_retries(call, self.max_retries)
        if "error" in data:
            raise ModelError(f"ollama error: {data['error']}")
        msg = data.get("message", {})
        message = Message.assistant(
            msg.get("content") or "", parse_ollama_tool_calls(msg.get("tool_calls"))
        )
        usage = Usage(int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0))
        if not usage.total_tokens:
            usage = Usage(self.count_tokens(messages), self._counter.count(message.content))
        return ChatResponse(
            message=message,
            usage=usage,
            model=self.model,
            latency_ms=(time.perf_counter() - start) * 1000,
            finish_reason=data.get("done_reason"),
            raw=data,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: ToolSpecs | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        payload = self._payload(messages, tools, temperature, max_tokens, stream=True)
        start = time.perf_counter()
        content: list[str] = []
        calls: list[ToolCall] = []
        usage = Usage()
        finish = None
        try:
            async with (
                self._client() as client,
                client.stream("POST", "/api/chat", json=payload) as resp,
            ):
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise ModelError(f"HTTP {resp.status_code}: {body[:500]!r}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise ModelError(f"ollama error: {chunk['error']}")
                    msg = chunk.get("message", {})
                    if msg.get("content"):
                        content.append(msg["content"])
                        yield TokenEvent(msg["content"])
                    for tc in parse_ollama_tool_calls(msg.get("tool_calls")):
                        calls.append(tc)
                        yield ToolCallEvent(tc)
                    if chunk.get("done"):
                        usage = Usage(
                            int(chunk.get("prompt_eval_count") or 0),
                            int(chunk.get("eval_count") or 0),
                        )
                        finish = chunk.get("done_reason")
        except httpx.HTTPError as exc:
            raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        yield DoneEvent(
            ChatResponse(
                message=Message.assistant("".join(content), calls),
                usage=usage,
                model=self.model,
                latency_ms=(time.perf_counter() - start) * 1000,
                finish_reason=finish,
            )
        )

    async def list_models(self) -> list[str]:
        async with self._client() as client:
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]


def ollama_available(
    host: str | None = None, model: str | None = None, timeout: float = 0.5
) -> bool:
    """Quick synchronous probe: is Ollama reachable (and is ``model`` pulled)?"""
    try:
        resp = httpx.get(f"{(host or ollama_host()).rstrip('/')}/api/tags", timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return False
    if model is None:
        return True
    names = {m.get("name", "") for m in resp.json().get("models", [])}
    return model in names or f"{model}:latest" in names
