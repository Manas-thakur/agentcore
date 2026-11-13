"""Documents, chunks and loaders (text, markdown/MDX, HTML, JSONL, directories)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


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
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdx"}
HTML_SUFFIXES = {".html", ".htm"}

_FRONT_MATTER = re.compile(
    r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S
)
_FENCE = re.compile(r"^\s*(```|~~~)")
_ALT_TAG = re.compile(r"<[A-Za-z][\w.:-]*\b[^<>]*?\balt=(?:\"([^\"]*)\"|'([^']*)')[^<>]*>")
_JSX_TAG = re.compile(r"</?[A-Za-z][\w.:-]*(?:\s(?:[^<>{}]|\{[^{}]*\})*)?/?>|<>|</>")
_JSX_COMMENT = re.compile(r"\{/\*.*?\*/\}", re.S)


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split leading YAML front matter (``---`` ... ``---``) from markdown text."""
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, text[m.end() :]


def mdx_to_markdown(text: str) -> str:
    """Strip MDX syntax: ``import``/``export`` lines, JSX comments and tags (keeping alt text
    and the text between tags). Code blocks are left untouched."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if re.match(r"^(import|export)\s", line):
            continue
        line = _JSX_COMMENT.sub("", line)
        line = _ALT_TAG.sub(lambda m: m.group(1) or m.group(2) or "", line)
        line = _JSX_TAG.sub("", line)
        out.append(line)
    cleaned = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"


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
                        source=f"{p.as_posix()}:{i}",
                        metadata={"title": rec.get("title", f"{p.stem}:{i}"), **rec},
                    )
                )
        return docs
    raw = p.read_text(encoding="utf-8", errors="replace")
    source = p.as_posix()  # forward slashes on every OS (stable ids, readable citations)
    suffix = p.suffix.lower()
    meta: dict[str, Any] = {"source": source, "format": suffix.lstrip(".") or "txt"}
    if suffix in HTML_SUFFIXES:
        from agentcore.tools.builtins.web import html_to_text

        title, raw = html_to_text(raw)
        meta["title"] = title or p.stem
    elif suffix in MARKDOWN_SUFFIXES:
        front, raw = split_front_matter(raw)
        if suffix == ".mdx":
            raw = mdx_to_markdown(raw)
        for key in ("title", "description"):
            if isinstance(front.get(key), (str, int, float)) and str(front[key]).strip():
                meta[key] = str(front[key]).strip()
        if "title" not in meta:
            for line in raw.splitlines():
                if line.startswith("# "):
                    meta["title"] = line[2:].strip()
                    break
    meta.setdefault("title", p.stem)
    return [Document(raw, source=source, metadata=meta)]


def load_directory(
    path: str | Path, pattern: str = "**/*", suffixes: set[str] | None = None
) -> list[Document]:
    """Recursively load every supported file under ``path``."""
    allowed = suffixes or (TEXT_SUFFIXES | MARKDOWN_SUFFIXES | HTML_SUFFIXES | {".jsonl"})
    docs: list[Document] = []
    for p in sorted(Path(path).glob(pattern)):
        if p.is_file() and p.suffix.lower() in allowed:
            docs.extend(load_file(p))
    return docs


def load_path(path: str | Path) -> list[Document]:
    p = Path(path)
    return load_directory(p) if p.is_dir() else load_file(p)
