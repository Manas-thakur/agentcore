"""Chunking strategies: fixed-size, recursive, sentence-aware and markdown-aware."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from agentcore.rag.documents import Chunk, Document


class Chunker(ABC):
    @abstractmethod
    def split_text(self, text: str) -> list[tuple[int, int]]:
        """Return ``(start, end)`` character spans."""

    def chunk(self, document: Document) -> list[Chunk]:
        chunks = []
        for start, end in self.split_text(document.content):
            content = document.content[start:end].strip()
            if not content:
                continue
            meta = {**document.metadata, "source": document.source, "title": document.title}
            chunks.append(Chunk(content, document.id, len(chunks), start, end, meta))
        return chunks

    def chunk_many(self, documents: list[Document]) -> list[Chunk]:
        return [c for d in documents for c in self.chunk(d)]


class FixedSizeChunker(Chunker):
    """Fixed character windows with overlap. Simple and predictable."""

    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split_text(self, text: str) -> list[tuple[int, int]]:
        spans, start, step = [], 0, self.chunk_size - self.overlap
        while start < len(text):
            spans.append((start, min(start + self.chunk_size, len(text))))
            if start + self.chunk_size >= len(text):
                break
            start += step
        return spans


class RecursiveChunker(Chunker):
    """Split on the coarsest separator that yields pieces under ``chunk_size``, then merge.

    Separators are tried in order: blank lines, newlines, sentence ends, spaces, chars.
    """

    def __init__(
        self,
        chunk_size: int = 800,
        overlap: int = 100,
        separators: tuple[str, ...] = ("\n\n", "\n", ". ", " ", ""),
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.separators = separators

    def _split(self, text: str, offset: int, seps: tuple[str, ...]) -> list[tuple[int, int]]:
        if len(text) <= self.chunk_size:
            return [(offset, offset + len(text))]
        sep, rest = seps[0], seps[1:]
        if sep == "":
            return [
                (offset + i, offset + min(i + self.chunk_size, len(text)))
                for i in range(0, len(text), self.chunk_size)
            ]
        pieces: list[tuple[int, int]] = []
        pos = 0
        while pos < len(text):
            nxt = text.find(sep, pos)
            end = len(text) if nxt == -1 else nxt + len(sep)
            pieces.append((pos, end))
            pos = end
        out: list[tuple[int, int]] = []
        for s, e in pieces:
            if e - s > self.chunk_size:
                out.extend(self._split(text[s:e], offset + s, rest or ("",)))
            else:
                out.append((offset + s, offset + e))
        return out

    def split_text(self, text: str) -> list[tuple[int, int]]:
        atoms = self._split(text, 0, self.separators)
        merged: list[tuple[int, int]] = []
        window: list[tuple[int, int]] = []
        for atom in atoms:
            if window and atom[1] - window[0][0] > self.chunk_size:
                merged.append((window[0][0], window[-1][1]))
                # carry whole trailing atoms (up to ``overlap`` chars) into the next chunk
                tail: list[tuple[int, int]] = []
                for prev in reversed(window):
                    if window[-1][1] - prev[0] > self.overlap:
                        break
                    tail.insert(0, prev)
                window = tail
                while window and atom[1] - window[0][0] > self.chunk_size:
                    window.pop(0)
            window.append(atom)
        if window:
            merged.append((window[0][0], window[-1][1]))
        return merged


_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")


class SentenceChunker(Chunker):
    """Pack whole sentences into chunks of at most ``chunk_size`` characters.

    ``overlap_sentences`` repeats the last N sentences at the start of the next chunk.
    """

    def __init__(self, chunk_size: int = 600, overlap_sentences: int = 1):
        self.chunk_size = chunk_size
        self.overlap_sentences = overlap_sentences

    def split_text(self, text: str) -> list[tuple[int, int]]:
        sents = [(m.start(), m.end()) for m in _SENTENCE_RE.finditer(text) if m.group(0).strip()]
        spans: list[tuple[int, int]] = []
        i = 0
        while i < len(sents):
            j = i
            while j + 1 < len(sents) and sents[j + 1][1] - sents[i][0] <= self.chunk_size:
                j += 1
            spans.append((sents[i][0], sents[j][1]))
            if j + 1 >= len(sents):
                break
            i = max(j + 1 - self.overlap_sentences, i + 1)
        return spans


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)


class MarkdownChunker(Chunker):
    """Split on markdown headings; oversized sections are split recursively.

    Each chunk's metadata carries its heading path (``"Intro > Setup"``) and the heading
    path is prepended to the chunk text so retrieval sees the section context.
    """

    def __init__(self, chunk_size: int = 1000, overlap: int = 100, include_headings: bool = True):
        self.chunk_size = chunk_size
        self.include_headings = include_headings
        self._inner = RecursiveChunker(chunk_size, overlap)

    def sections(self, text: str) -> list[tuple[int, int, str]]:
        heads = list(_HEADING_RE.finditer(text))
        out: list[tuple[int, int, str]] = []
        path: list[tuple[int, str]] = []
        if not heads or heads[0].start() > 0:
            out.append((0, heads[0].start() if heads else len(text), ""))
        for k, h in enumerate(heads):
            level = len(h.group(1))
            path = [p for p in path if p[0] < level] + [(level, h.group(2).strip())]
            end = heads[k + 1].start() if k + 1 < len(heads) else len(text)
            out.append((h.start(), end, " > ".join(p[1] for p in path)))
        return out

    def split_text(self, text: str) -> list[tuple[int, int]]:
        return [span for span, _ in self._spans_with_headings(text)]

    def _spans_with_headings(self, text: str) -> list[tuple[tuple[int, int], str]]:
        out = []
        for s, e, heading in self.sections(text):
            for cs, ce in self._inner.split_text(text[s:e]):
                out.append(((s + cs, s + ce), heading))
        return out

    def chunk(self, document: Document) -> list[Chunk]:
        chunks = []
        for (start, end), heading in self._spans_with_headings(document.content):
            content = document.content[start:end].strip()
            if not content or _HEADING_RE.fullmatch(content):
                continue
            meta = {
                **document.metadata,
                "source": document.source,
                "title": document.title,
                "heading": heading,
            }
            if self.include_headings and heading:
                content = f"[{heading}]\n{content}"
            chunks.append(Chunk(content, document.id, len(chunks), start, end, meta))
        return chunks


def create_chunker(kind: str = "recursive", **kwargs: int) -> Chunker:
    table = {
        "fixed": FixedSizeChunker,
        "recursive": RecursiveChunker,
        "sentence": SentenceChunker,
        "markdown": MarkdownChunker,
    }
    return table[kind](**kwargs)
