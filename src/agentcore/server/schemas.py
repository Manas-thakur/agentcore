"""Request bodies for the HTTP API (imported lazily: needs the ``server`` extra)."""
# NOTE: no "from __future__ import annotations" - pydantic/FastAPI resolve these at runtime.

from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class AgentRequest(BaseModel):
    input: str | None = None
    messages: list[ChatMessage] | None = None
    model: str | None = None
    tools: list[str] | None = Field(default=None, description="subset of the enabled tools")
    system_prompt: str | None = None
    max_steps: int = Field(default=8, ge=1, le=50)
    session_id: str | None = Field(default=None, description="continue a server-side session")


class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    session_id: str | None = None
    model: str | None = None
    tools: list[str] | None = None
    system_prompt: str | None = None
    max_steps: int = Field(default=8, ge=1, le=50)


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ToolInvokeRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class EvalRunRequest(BaseModel):
    suite: str
    model: str | None = None
    tags: list[str] | None = None


class OAIMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: Union[str, list[dict[str, Any]], None] = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class StreamOptions(BaseModel):
    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = "agentcore"
    messages: list[OAIMessage] = Field(min_length=1)
    stream: bool = False
    stream_options: StreamOptions | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    user: str | None = None
    # Accepted for compatibility. Only n=1 is supported. ``tools``/``tool_choice`` are
    # ignored: the agent uses the tools enabled on the server and returns the final answer.
    n: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Union[str, dict[str, Any], None] = None
