"""Okapi BM25 from scratch, with an inverted index for sparse scoring."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


def _stem(token: str) -> str:
    """A tiny suffix stripper (plural/-ing/-ed). Good enough for lexical matching."""
    for suffix, min_len in (("ies", 5), ("ing", 6), ("ed", 5), ("es", 5), ("s", 4)):
        if token.endswith(suffix) and len(token) >= min_len and not token.endswith("ss"):
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


def tokenize(text: str, stem: bool = True) -> list[str]:
    tokens = [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]
    return [_stem(t) for t in tokens] if stem else tokens


class BM25:
    """``score(q, d) = sum_t idf(t) * tf(t,d) * (k1 + 1) / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))``."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.doc_len: list[int] = []
        self.postings: dict[str, dict[int, int]] = defaultdict(dict)  # term -> {doc_idx: tf}
        self._pos: dict[str, int] = {}
        self._deleted: set[int] = set()

    def __len__(self) -> int:
        return len(self.doc_ids) - len(self._deleted)

    @property
    def avgdl(self) -> float:
        live = [n for i, n in enumerate(self.doc_len) if i not in self._deleted]
        return sum(live) / len(live) if live else 0.0

    def add(self, doc_id: str, text: str) -> None:
        if doc_id in self._pos:
            self.remove(doc_id)
        idx = len(self.doc_ids)
        tokens = tokenize(text)
        self.doc_ids.append(doc_id)
        self.doc_len.append(len(tokens))
        self._pos[doc_id] = idx
        for term, tf in Counter(tokens).items():
            self.postings[term][idx] = tf

    def add_many(self, items: list[tuple[str, str]]) -> None:
        for doc_id, text in items:
            self.add(doc_id, text)

    def remove(self, doc_id: str) -> None:
        idx = self._pos.pop(doc_id, None)
        if idx is None:
            return
        self._deleted.add(idx)
        for plist in self.postings.values():
            plist.pop(idx, None)

    def idf(self, term: str) -> float:
        n = len(self)
        df = len(self.postings.get(term, {}))
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> dict[str, float]:
        avgdl = self.avgdl or 1.0
        acc: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = self.idf(term)
            for idx, tf in plist.items():
                norm = tf + self.k1 * (1 - self.b + self.b * self.doc_len[idx] / avgdl)
                acc[idx] += idf * tf * (self.k1 + 1) / norm
        return {self.doc_ids[i]: s for i, s in acc.items()}

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        scored = sorted(self.scores(query).items(), key=lambda kv: (-kv[1], kv[0]))
        return scored[:k]

    def to_dict(self) -> dict[str, Any]:
        return {
            "k1": self.k1,
            "b": self.b,
            "doc_ids": self.doc_ids,
            "doc_len": self.doc_len,
            "postings": {
                t: {str(i): tf for i, tf in p.items()} for t, p in self.postings.items() if p
            },
            "deleted": sorted(self._deleted),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BM25:
        bm = cls(d["k1"], d["b"])
        bm.doc_ids = list(d["doc_ids"])
        bm.doc_len = list(d["doc_len"])
        bm._deleted = set(d.get("deleted", []))
        bm._pos = {doc: i for i, doc in enumerate(bm.doc_ids) if i not in bm._deleted}
        for term, plist in d["postings"].items():
            bm.postings[term] = {int(i): tf for i, tf in plist.items()}
        return bm
