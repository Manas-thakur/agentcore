"""Checkpoint storage for graph runs (enables interrupt/resume, recovery and inspection)."""

from __future__ import annotations

import copy
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Checkpoint:
    thread_id: str
    graph: str
    state: dict[str, Any]
    next_nodes: list[str] = field(default_factory=list)
    join_progress: dict[str, list[str]] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)  # completed nodes, in order
    resume_values: dict[str, list[Any]] = field(default_factory=dict)
    step: int = 0
    status: str = "running"  # running | interrupted | completed | failed
    interrupts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Checkpoint:
        return cls(**d)


class Checkpointer(ABC):
    @abstractmethod
    def put(self, cp: Checkpoint) -> None: ...

    @abstractmethod
    def get(self, thread_id: str) -> Checkpoint | None: ...

    @abstractmethod
    def history(self, thread_id: str) -> list[Checkpoint]: ...

    def list_threads(self) -> list[str]:
        return []


class MemoryCheckpointer(Checkpointer):
    """Keeps every checkpoint (per super-step) in memory."""

    def __init__(self) -> None:
        self._data: dict[str, list[Checkpoint]] = {}

    def put(self, cp: Checkpoint) -> None:
        self._data.setdefault(cp.thread_id, []).append(copy.deepcopy(cp))

    def get(self, thread_id: str) -> Checkpoint | None:
        items = self._data.get(thread_id)
        return copy.deepcopy(items[-1]) if items else None

    def history(self, thread_id: str) -> list[Checkpoint]:
        return [copy.deepcopy(c) for c in self._data.get(thread_id, [])]

    def list_threads(self) -> list[str]:
        return list(self._data)


class FileCheckpointer(Checkpointer):
    """JSON-lines file per thread. State values must be JSON-serializable."""

    def __init__(self, directory: str | Path = ".agentcore/checkpoints"):
        self.directory = Path(directory)

    def _path(self, thread_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in thread_id)
        return self.directory / f"{safe}.jsonl"

    def put(self, cp: Checkpoint) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            line = json.dumps(cp.to_dict())
        except TypeError as exc:
            raise TypeError(
                f"graph state is not JSON-serializable for FileCheckpointer: {exc}"
            ) from exc
        with self._path(cp.thread_id).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def history(self, thread_id: str) -> list[Checkpoint]:
        path = self._path(thread_id)
        if not path.exists():
            return []
        return [
            Checkpoint.from_dict(json.loads(x))
            for x in path.read_text(encoding="utf-8").splitlines()
            if x
        ]

    def get(self, thread_id: str) -> Checkpoint | None:
        hist = self.history(thread_id)
        return hist[-1] if hist else None

    def list_threads(self) -> list[str]:
        return [p.stem for p in self.directory.glob("*.jsonl")] if self.directory.exists() else []
