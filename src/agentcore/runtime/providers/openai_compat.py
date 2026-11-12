"""OpenAI-compatible Chat Completions provider over raw HTTP (httpx).

Works with OpenAI and any server exposing ``/v1/chat/completions`` with tool calling:
vLLM, LM Studio, llama.cpp server, Groq, Together, OpenRouter, Ollama's ``/v1`` shim, ...
"""

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
    parse_json_arguments,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        d: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in m.tool_calls
            ]
            if not m.content:
                d["content"] = None
        if m.role == "tool":
            d["tool_call_id"] = m.tool_call_id or new_id("call_")
        out.append(d)
    return out


class OpenAICompatibleClient(ModelClient):
    provider = "openai"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        extra_body: dict[str, Any] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ):
        super().__init__(model, **kwargs)
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip(
            "/"
        )
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.extra_body = extra_body or {}
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.AsyncClient(
            base_url=self.base_url, headers=headers, timeout=self.timeout, transport=self._transport
        )

    def _payload(
        self,
        messages: list[Message],
        tools: ToolSpecs | None,
        temperature: float,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "temperature": temperature,
            **self.extra_body,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
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
                resp = await client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                return resp.json()

        data = await with_retries(call, self.max_retries)
        if not data.get("choices"):
            raise ModelError(f"no choices in response: {str(data)[:300]}")
        choice = data["choices"][0]
        msg = choice.get("message", {})
        calls = [
            ToolCall(
                name=tc["function"]["name"],
                arguments=parse_json_arguments(tc["function"].get("arguments") or ""),
                id=tc.get("id") or new_id("call_"),
            )
            for tc in msg.get("tool_calls") or []
        ]
        u = data.get("usage") or {}
        usage = Usage(int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0))
        return ChatResponse(
            message=Message.assistant(msg.get("content") or "", calls),
            usage=usage,
            model=data.get("model", self.model),
            latency_ms=(time.perf_counter() - start) * 1000,
            finish_reason=choice.get("finish_reason"),
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
        partial: dict[int, dict[str, Any]] = {}
        usage = Usage()
        finish = None
        try:
            async with (
                self._client() as client,
                client.stream("POST", "/chat/completions", json=payload) as resp,
            ):
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise ModelError(f"HTTP {resp.status_code}: {body[:500]!r}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if chunk.get("usage"):
                        u = chunk["usage"]
                        usage = Usage(
                            int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
                        )
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            content.append(delta["content"])
                            yield TokenEvent(delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = partial.setdefault(
                                tc.get("index", 0), {"id": None, "name": "", "args": ""}
                            )
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function") or {}
                            slot["name"] += fn.get("name") or ""
                            slot["args"] += fn.get("arguments") or ""
                        finish = choice.get("finish_reason") or finish
        except httpx.HTTPError as exc:
            raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        calls = [
            ToolCall(
                name=s["name"],
                arguments=parse_json_arguments(s["args"]),
                id=s["id"] or new_id("call_"),
            )
            for _, s in sorted(partial.items())
        ]
        for tc in calls:
            yield ToolCallEvent(tc)
        if not usage.total_tokens:
            usage = Usage(self.count_tokens(messages), self._counter.count("".join(content)))
        yield DoneEvent(
            ChatResponse(
                message=Message.assistant("".join(content), calls),
                usage=usage,
                model=self.model,
                latency_ms=(time.perf_counter() - start) * 1000,
                finish_reason=finish,
            )
        )
