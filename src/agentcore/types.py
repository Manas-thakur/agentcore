"""Core message and response types shared by every AgentCore subpackage.

These are deliberately plain dataclasses with explicit ``to_dict``/``from_dict`` so that
they can be serialized into traces, eval cassettes and checkpoints without any magic.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


def new_id(prefix: str = "") -> str:
    """Return a short random identifier, optionally prefixed (``call_ab12...``)."""
    return f"{prefix}{uuid.uuid4().hex[:16]}"


@dataclass
class ToolCall:
    """A model's request to call a tool."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("call_"))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCall:
        args = data.get("arguments") or {}
        if isinstance(args, str):
            args = parse_json_arguments(args)
        return cls(name=data["name"], arguments=args, id=data.get("id") or new_id("call_"))


def parse_json_arguments(raw: str) -> dict[str, Any]:
    """Parse tool-call arguments that a provider returned as a JSON string."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"__raw__": raw}
    return value if isinstance(value, dict) else {"value": value}


@dataclass
class Message:
    """A single chat message in provider-neutral form."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None  # tool name for role == "tool"

    # Convenience constructors -------------------------------------------------
    @classmethod
    def system(cls, content: str) -> Message:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: list[ToolCall] | None = None) -> Message:
        return cls(role="assistant", content=content, tool_calls=list(tool_calls or []))

    @classmethod
    def tool(cls, content: str, tool_call_id: str | None, name: str | None = None) -> Message:
        return cls(role="tool", content=content, tool_call_id=tool_call_id, name=name)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.name:
            data["name"] = self.name
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            role=data["role"],
            content=data.get("content") or "",
            tool_calls=[ToolCall.from_dict(tc) for tc in data.get("tool_calls") or []],
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Usage:
        data = data or {}
        return cls(int(data.get("prompt_tokens", 0)), int(data.get("completion_tokens", 0)))


@dataclass
class ChatResponse:
    """The result of a single (non-streaming or buffered) model call."""

    message: Message
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    latency_ms: float = 0.0
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def content(self) -> str:
        return self.message.content

    @property
    def tool_calls(self) -> list[ToolCall]:
        return self.message.tool_calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message.to_dict(),
            "usage": self.usage.to_dict(),
            "model": self.model,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatResponse:
        return cls(
            message=Message.from_dict(data["message"]),
            usage=Usage.from_dict(data.get("usage")),
            model=data.get("model", ""),
            latency_ms=float(data.get("latency_ms", 0.0)),
            finish_reason=data.get("finish_reason"),
        )


# --- Streaming events ----------------------------------------------------------


@dataclass
class TokenEvent:
    content: str
    type: Literal["token"] = "token"


@dataclass
class ToolCallEvent:
    tool_call: ToolCall
    type: Literal["tool_call"] = "tool_call"


@dataclass
class DoneEvent:
    response: ChatResponse
    type: Literal["done"] = "done"


StreamEvent = TokenEvent | ToolCallEvent | DoneEvent
