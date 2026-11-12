"""Documents, chunks and loaders (text, markdown, HTML, JSONL, directories)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Document:
    content: str
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            digest = hashlib.sha1(f"{self.source}\n{self.content}".encode()).hexdigest()[:12]
            self.id = f"doc_{digest}"

    @property
    def title(self) -> str:
        return str(self.metadata.get("title") or Path(self.source).stem or self.id)


@dataclass
class Chunk:
    content: str
    doc_id: str
    index: int
    start: int = 0
    end: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.doc_id}#{self.index}"

    @property
    def source(self) -> str:
        return str(self.metadata.get("source", ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "doc_id": self.doc_id,
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Chunk:
        return cls(
            d["content"],
            d["doc_id"],
            d["index"],
            d.get("start", 0),
            d.get("end", 0),
            d.get("metadata", {}),
        )


TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".py", ".json", ".yaml", ".yml", ".csv"}
HTML_SUFFIXES = {".html", ".htm"}


def load_file(path: str | Path) -> list[Document]:
    """Load a single file. ``.jsonl`` files yield one document per line (``text``/``content`` key)."""
    p = Path(path)
    if p.suffix == ".jsonl":
        docs = []
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                rec = json.loads(line)
                text = rec.pop("text", None) or rec.pop("content", "")
                docs.append(
                    Document(
                        text,
                        source=f"{p}:{i}",
                        metadata={"title": rec.get("title", f"{p.stem}:{i}"), **rec},
                    )
                )
        return docs
    raw = p.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, Any] = {"source": str(p), "format": p.suffix.lstrip(".") or "txt"}
    if p.suffix in HTML_SUFFIXES:
        from agentcore.tools.builtins.web import html_to_text

        title, raw = html_to_text(raw)
        meta["title"] = title or p.stem
    elif p.suffix in (".md", ".markdown"):
        for line in raw.splitlines():
            if line.startswith("# "):
                meta["title"] = line[2:].strip()
                break
    meta.setdefault("title", p.stem)
    return [Document(raw, source=str(p), metadata=meta)]


def load_directory(
    path: str | Path, pattern: str = "**/*", suffixes: set[str] | None = None
) -> list[Document]:
    """Recursively load every supported file under ``path``."""
    allowed = suffixes or (TEXT_SUFFIXES | HTML_SUFFIXES | {".jsonl"})
    docs: list[Document] = []
    for p in sorted(Path(path).glob(pattern)):
        if p.is_file() and p.suffix.lower() in allowed:
            docs.extend(load_file(p))
    return docs


def load_path(path: str | Path) -> list[Document]:
    p = Path(path)
    return load_directory(p) if p.is_dir() else load_file(p)
