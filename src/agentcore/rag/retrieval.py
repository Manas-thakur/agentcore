"""Retrievers: dense (vector index), sparse (BM25), hybrid (reciprocal rank fusion)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from agentcore.embeddings import Embedder
from agentcore.index.base import VectorIndex
from agentcore.rag.bm25 import BM25
from agentcore.rag.documents import Chunk


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float
    retriever: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.chunk.id

    @property
    def content(self) -> str:
        return self.chunk.content


class ChunkStore:
    """In-memory id -> Chunk map shared by retrievers."""

    def __init__(self) -> None:
        self.chunks: dict[str, Chunk] = {}

    def add(self, chunks: list[Chunk]) -> None:
        for c in chunks:
            self.chunks[c.id] = c

    def get(self, chunk_id: str) -> Chunk:
        return self.chunks[chunk_id]

    def __len__(self) -> int:
        return len(self.chunks)


class Retriever(ABC):
    name = "retriever"

    @abstractmethod
    def retrieve(self, query: str, k: int = 5) -> list[ScoredChunk]: ...


class VectorRetriever(Retriever):
    name = "vector"

    def __init__(self, embedder: Embedder, index: VectorIndex, store: ChunkStore):
        self.embedder = embedder
        self.index = index
        self.store = store

    def add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        vecs = self.embedder.embed([c.content for c in chunks])
        self.index.add(vecs, [c.id for c in chunks])

    def retrieve(self, query: str, k: int = 5) -> list[ScoredChunk]:
        q = self.embedder.embed_one(query)
        return [
            ScoredChunk(self.store.get(r.id), r.score, self.name)
            for r in self.index.search(q, k)
            if r.id in self.store.chunks
        ]


class BM25Retriever(Retriever):
    name = "bm25"

    def __init__(self, store: ChunkStore, bm25: BM25 | None = None):
        self.store = store
        self.bm25 = bm25 or BM25()

    def add(self, chunks: list[Chunk]) -> None:
        self.bm25.add_many([(c.id, c.content) for c in chunks])

    def retrieve(self, query: str, k: int = 5) -> list[ScoredChunk]:
        return [ScoredChunk(self.store.get(i), s, self.name) for i, s in self.bm25.search(query, k)]


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = 60, weights: list[float] | None = None
) -> list[tuple[str, float]]:
    """RRF: ``score(d) = sum_i w_i / (k + rank_i(d))`` (ranks start at 1)."""
    weights = weights or [1.0] * len(rankings)
    scores: dict[str, float] = {}
    for ranking, w in zip(rankings, weights):
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


class HybridRetriever(Retriever):
    """Fuse several retrievers (typically BM25 + vector) with reciprocal rank fusion."""

    name = "hybrid"

    def __init__(
        self,
        retrievers: list[Retriever],
        *,
        weights: list[float] | None = None,
        rrf_k: int = 60,
        candidate_k: int = 20,
    ):
        self.retrievers = retrievers
        self.weights = weights
        self.rrf_k = rrf_k
        self.candidate_k = candidate_k

    def retrieve(self, query: str, k: int = 5) -> list[ScoredChunk]:
        per = [r.retrieve(query, max(k, self.candidate_k)) for r in self.retrievers]
        by_id = {sc.id: sc.chunk for results in per for sc in results}
        ranks = {
            r.name: {sc.id: i + 1 for i, sc in enumerate(results)}
            for r, results in zip(self.retrievers, per)
        }
        fused = reciprocal_rank_fusion(
            [[sc.id for sc in res] for res in per], self.rrf_k, self.weights
        )
        return [
            ScoredChunk(
                by_id[cid], score, self.name, {"ranks": {n: rk.get(cid) for n, rk in ranks.items()}}
            )
            for cid, score in fused[:k]
        ]
