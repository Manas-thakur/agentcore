"""Pure-ASGI middleware: optional API-key auth and request body size limits."""

from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

PUBLIC_PATHS = frozenset({"/", "/health", "/favicon.ico", "/favicon.svg"})
PUBLIC_PREFIXES = ("/static/",)


async def _send_json(send: Send, status: int, payload: dict[str, Any], headers=()) -> None:
    body = json.dumps(payload).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def extract_key(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        lname = name.lower()
        if lname == b"authorization":
            text = value.decode("latin-1").strip()
            if text.lower().startswith("bearer "):
                return text[7:].strip()
        elif lname == b"x-api-key":
            return value.decode("latin-1").strip()
    return None


class APIKeyMiddleware:
    """Require ``Authorization: Bearer <key>`` or ``X-API-Key: <key>`` outside public paths.

    The web UI shell (``/`` and ``/static/*``) and ``/health`` stay public so the browser can
    load the app and prompt for the key; every API route is protected.
    """

    def __init__(self, app: ASGIApp, api_key: str):
        self.app = app
        self.api_key = api_key.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return
        key = extract_key(scope.get("headers") or [])
        if key is None or not hmac.compare_digest(key.encode(), self.api_key):
            await _send_json(
                send,
                401,
                {
                    "error": {
                        "message": "missing or invalid API key; send 'Authorization: Bearer <key>'",
                        "type": "invalid_api_key",
                    }
                },
                headers=[(b"www-authenticate", b"Bearer")],
            )
            return
        await self.app(scope, receive, send)


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject request bodies larger than ``max_bytes`` with 413 (checks headers and streams)."""

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.max_bytes <= 0:
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers") or []:
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await self._reject(send)
                    return
        seen = 0
        started = False
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    exceeded = True
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                # the framework turned our exception into its own error response: replace it
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await self._reject(send)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        await _send_json(
            send,
            413,
            {
                "error": {
                    "message": f"request body exceeds the {self.max_bytes}-byte limit",
                    "type": "request_too_large",
                }
            },
        )
