"""Rerankers that refine a candidate list after retrieval."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

import numpy as np

from agentcore.embeddings import Embedder
from agentcore.rag.bm25 import tokenize
from agentcore.rag.retrieval import ScoredChunk


class Reranker(ABC):
    @abstractmethod
    def rerank(
        self, query: str, candidates: list[ScoredChunk], k: int = 5
    ) -> list[ScoredChunk]: ...


class LexicalReranker(Reranker):
    """Scores candidates by query-term coverage and proximity, blended with the prior rank.

    * coverage: fraction of distinct query terms present in the chunk
    * proximity: 1 / (1 + smallest token window that contains all matched terms)
    * prior: reciprocal of the candidate's original rank
    """

    def __init__(self, w_coverage: float = 0.6, w_proximity: float = 0.2, w_prior: float = 0.2):
        self.w = (w_coverage, w_proximity, w_prior)

    @staticmethod
    def _min_window(tokens: list[str], terms: set[str]) -> int:
        if not terms:
            return len(tokens)
        need, have, best, left = len(terms), {}, len(tokens), 0
        for right, tok in enumerate(tokens):
            if tok in terms:
                have[tok] = have.get(tok, 0) + 1
            while len(have) == need:
                best = min(best, right - left + 1)
                lt = tokens[left]
                if lt in have:
                    have[lt] -= 1
                    if not have[lt]:
                        del have[lt]
                left += 1
        return best

    def score(self, query: str, text: str) -> tuple[float, float]:
        q = set(tokenize(query))
        toks = tokenize(text)
        matched = q & set(toks)
        coverage = len(matched) / len(q) if q else 0.0
        proximity = 1.0 / (1.0 + self._min_window(toks, matched)) if matched else 0.0
        return coverage, proximity

    def rerank(self, query: str, candidates: list[ScoredChunk], k: int = 5) -> list[ScoredChunk]:
        wc, wp, wr = self.w
        rescored = []
        for rank, sc in enumerate(candidates, start=1):
            cov, prox = self.score(query, sc.content)
            s = wc * cov + wp * min(1.0, prox * 5) + wr / rank
            rescored.append(
                ScoredChunk(
                    sc.chunk, s, "rerank", {**sc.details, "coverage": cov, "prior_rank": rank}
                )
            )
        rescored.sort(key=lambda x: -x.score)
        return rescored[:k]


class MMRReranker(Reranker):
    """Maximal Marginal Relevance: trade relevance against redundancy (lambda=1: pure relevance)."""

    def __init__(self, embedder: Embedder, lambda_: float = 0.7):
        self.embedder = embedder
        self.lambda_ = lambda_

    def rerank(self, query: str, candidates: list[ScoredChunk], k: int = 5) -> list[ScoredChunk]:
        if not candidates:
            return []
        q = self.embedder.embed_one(query)
        docs = self.embedder.embed([c.content for c in candidates])
        rel = docs @ q
        chosen: list[int] = []
        remaining = list(range(len(candidates)))
        while remaining and len(chosen) < k:
            if chosen:
                redundancy = np.max(docs[remaining] @ docs[chosen].T, axis=1)
            else:
                redundancy = np.zeros(len(remaining))
            mmr = self.lambda_ * rel[remaining] - (1 - self.lambda_) * redundancy
            pick = remaining[int(np.argmax(mmr))]
            chosen.append(pick)
            remaining.remove(pick)
        return [
            ScoredChunk(candidates[i].chunk, float(rel[i]), "mmr", candidates[i].details)
            for i in chosen
        ]


class CallableReranker(Reranker):
    """Wrap any ``(query, text) -> score`` function, e.g. a cross-encoder model."""

    def __init__(self, fn: Callable[[str, str], float]):
        self.fn = fn

    def rerank(self, query: str, candidates: list[ScoredChunk], k: int = 5) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(c.chunk, float(self.fn(query, c.content)), "rerank", c.details)
            for c in candidates
        ]
        return sorted(scored, key=lambda x: -x.score)[:k]
