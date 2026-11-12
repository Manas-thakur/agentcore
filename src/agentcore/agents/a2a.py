"""A small in-process agent-to-agent (A2A) message protocol.

Messages are routed by recipient: a direct agent name, ``"broadcast"`` (everyone except
the sender) or ``"topic:<name>"`` (subscribers). ``request()`` sends a REQUEST and awaits
the RESPONSE/ERROR with the same ``correlation_id``.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agentcore.obs.tracing import get_tracer


class A2AMessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    STATUS_UPDATE = "status_update"
    DELEGATE = "delegate"
    QUERY = "query"
    EVENT = "event"


@dataclass
class A2AMessage:
    sender: str
    recipient: str
    type: A2AMessageType
    payload: dict[str, Any]
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_id: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    ttl_seconds: float = 300.0

    @property
    def expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl_seconds

    def reply(
        self, payload: dict[str, Any], type: A2AMessageType = A2AMessageType.RESPONSE
    ) -> A2AMessage:
        return A2AMessage(
            sender=self.recipient
            if not self.recipient.startswith(("topic:", "broadcast"))
            else "bus",
            recipient=self.sender,
            type=type,
            payload=payload,
            correlation_id=self.correlation_id,
            parent_id=self.id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "type": self.type.value,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "parent_id": self.parent_id,
            "timestamp": self.timestamp,
        }


Handler = Callable[[A2AMessage], "Awaitable[dict[str, Any] | None] | dict[str, Any] | None"]

_REPLYING = {A2AMessageType.REQUEST, A2AMessageType.DELEGATE, A2AMessageType.QUERY}


class MessageBus:
    """Routes messages between registered agents/handlers and correlates request/response."""

    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.topics: dict[str, set[str]] = {}
        self.history: list[A2AMessage] = []
        self.inboxes: dict[str, list[A2AMessage]] = {}
        self._pending: dict[str, asyncio.Future[A2AMessage]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self.listeners: list[Callable[[A2AMessage], Any]] = []

    def register(self, name: str, handler: Handler | Any, topics: list[str] | None = None) -> None:
        """Register a handler function or a ``SpecializedAgent`` under ``name``."""
        if hasattr(handler, "run") and not (
            inspect.isfunction(handler) or inspect.ismethod(handler)
        ):
            handler = agent_handler(handler)
        self.handlers[name] = handler
        self.inboxes.setdefault(name, [])
        for t in topics or []:
            self.subscribe(name, t)

    def subscribe(self, name: str, topic: str) -> None:
        self.topics.setdefault(topic, set()).add(name)

    def _recipients(self, msg: A2AMessage) -> list[str]:
        if msg.recipient == "broadcast":
            return [n for n in self.handlers if n != msg.sender]
        if msg.recipient.startswith("topic:"):
            return sorted(self.topics.get(msg.recipient[6:], set()) - {msg.sender})
        return [msg.recipient]

    async def send(self, msg: A2AMessage) -> None:
        self.history.append(msg)
        for listener in self.listeners:
            listener(msg)
        # responses resolve pending requests
        if msg.type in (A2AMessageType.RESPONSE, A2AMessageType.ERROR):
            fut = self._pending.pop(msg.correlation_id, None)
            if fut is not None and not fut.done():
                fut.set_result(msg)
            self.inboxes.setdefault(msg.recipient, []).append(msg)
            return
        if msg.expired:
            return
        for name in self._recipients(msg):
            if name not in self.handlers:
                if msg.type in _REPLYING:
                    await self.send(
                        msg.reply({"error": f"unknown recipient {name!r}"}, A2AMessageType.ERROR)
                    )
                continue
            self.inboxes.setdefault(name, []).append(msg)
            task = asyncio.create_task(self._deliver(name, msg))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _deliver(self, name: str, msg: A2AMessage) -> None:
        handler = self.handlers[name]
        with get_tracer().span(
            "a2a.deliver", {"from": msg.sender, "to": name, "type": msg.type.value}
        ):
            try:
                res = handler(msg)
                if inspect.isawaitable(res):
                    res = await res
                if msg.type in _REPLYING:
                    reply = msg.reply(res or {})
                    reply.sender = name
                    await self.send(reply)
            except Exception as exc:
                if msg.type in _REPLYING:
                    reply = msg.reply(
                        {"error": f"{type(exc).__name__}: {exc}"}, A2AMessageType.ERROR
                    )
                    reply.sender = name
                    await self.send(reply)

    async def request(
        self,
        sender: str,
        recipient: str,
        payload: dict[str, Any],
        *,
        timeout: float = 300.0,
        type: A2AMessageType = A2AMessageType.REQUEST,
        parent_id: str | None = None,
    ) -> A2AMessage:
        msg = A2AMessage(sender, recipient, type, payload, parent_id=parent_id)
        fut: asyncio.Future[A2AMessage] = asyncio.get_running_loop().create_future()
        self._pending[msg.correlation_id] = fut
        await self.send(msg)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(msg.correlation_id, None)

    async def drain(self) -> None:
        """Wait for all in-flight deliveries (useful after broadcasts)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def transcript(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.history]


def agent_handler(agent: Any) -> Handler:
    """Adapt a ``SpecializedAgent`` to a bus handler: payload ``{task, context}`` -> output dict."""

    async def handle(msg: A2AMessage) -> dict[str, Any]:
        if msg.type not in _REPLYING:
            return {}
        out = await agent.run(msg.payload.get("task", ""), msg.payload.get("context"))
        return out.to_dict()

    return handle
