"""Server-side chat sessions: per-session memory plus a renderable transcript, persisted as JSON."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentcore.runtime.memory import SlidingWindowMemory

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def valid_session_id(session_id: str) -> bool:
    return bool(_ID_RE.match(session_id))


@dataclass
class Session:
    id: str
    title: str = "New chat"
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    turns: list[dict[str, Any]] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    memory: SlidingWindowMemory = field(default_factory=lambda: SlidingWindowMemory(10))
    task: asyncio.Task[Any] | None = field(default=None, repr=False)

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created": self.created,
            "updated": self.updated,
            "turns": len(self.turns),
            "busy": self.busy,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "settings": self.settings,
            "messages": self.turns,
            "memory": self.memory.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        s = cls(
            id=d["id"],
            title=d.get("title") or "New chat",
            created=float(d.get("created", time.time())),
            updated=float(d.get("updated", time.time())),
            turns=list(d.get("messages") or []),
            settings=dict(d.get("settings") or {}),
        )
        if d.get("memory"):
            s.memory.load_dict(d["memory"])
        return s


class SessionStore:
    """Holds sessions in memory and mirrors them to ``<root>/<id>.json``."""

    def __init__(self, root: str | Path | None = None, max_sessions: int = 500):
        self.root = Path(root) if root else None
        self.max_sessions = max_sessions
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._loaded = False

    def _load_all(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self.root is None or not self.root.exists():
            return
        for path in self.root.glob("*.json"):
            try:
                s = Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError):
                continue
            self._sessions.setdefault(s.id, s)

    def list(self) -> list[Session]:
        self._load_all()
        return sorted(self._sessions.values(), key=lambda s: s.updated, reverse=True)

    def get(self, session_id: str) -> Session | None:
        self._load_all()
        return self._sessions.get(session_id)

    def create(self, session_id: str | None = None, title: str | None = None) -> Session:
        self._load_all()
        sid = session_id or f"s_{uuid.uuid4().hex[:12]}"
        if not valid_session_id(sid):
            raise ValueError("session ids may only contain letters, digits, '-' and '_'")
        with self._lock:
            if sid in self._sessions:
                return self._sessions[sid]
            s = Session(sid, title=title or "New chat")
            self._sessions[sid] = s
            self._evict()
        return s

    def get_or_create(self, session_id: str | None) -> Session:
        if session_id:
            existing = self.get(session_id)
            if existing is not None:
                return existing
        return self.create(session_id)

    def delete(self, session_id: str) -> bool:
        self._load_all()
        with self._lock:
            s = self._sessions.pop(session_id, None)
        if s is None:
            return False
        if s.task is not None and not s.task.done():
            s.task.cancel()
        if self.root is not None:
            (self.root / f"{session_id}.json").unlink(missing_ok=True)
        return True

    def save(self, session: Session) -> None:
        session.updated = time.time()
        if self.root is None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f"{session.id}.json.tmp"
        tmp.write_text(json.dumps(session.to_dict(), ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.root / f"{session.id}.json")

    def _evict(self) -> None:
        if len(self._sessions) <= self.max_sessions:
            return
        idle = sorted((s for s in self._sessions.values() if not s.busy), key=lambda s: s.updated)
        for s in idle[: len(self._sessions) - self.max_sessions]:
            self._sessions.pop(s.id, None)
