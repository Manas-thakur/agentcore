"""Hierarchical Navigable Small World graph index, implemented from scratch.

Follows Malkov & Yashunin (2016): exponentially-decaying random levels, greedy descent
through upper layers, beam search (``ef``) on each layer, and the neighbour-selection
heuristic (Algorithm 4) that keeps the graph navigable. Deletes are tombstones.
"""

from __future__ import annotations

import heapq
import json
import math
from typing import Any

import numpy as np

from agentcore.index.base import Filter, Metric, SearchResult, VectorIndex, as_matrix


class HNSWIndex(VectorIndex):
    kind = "hnsw"

    def __init__(
        self,
        dimension: int,
        metric: Metric | str = Metric.COSINE,
        *,
        M: int = 16,
        ef_construction: int = 200,
        ef_search: int = 64,
        seed: int = 42,
    ):
        super().__init__(dimension, metric)
        if M < 2:
            raise ValueError("M must be >= 2")
        self.M = M
        self.M0 = 2 * M
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.seed = seed
        self._ml = 1.0 / math.log(M)
        self._rng = np.random.default_rng(seed)
        self._data = np.zeros((16, self.dimension), dtype=np.float32)
        self._count = 0
        self._ids: list[str] = []
        self._pos: dict[str, int] = {}
        self._levels: list[int] = []
        self._links: list[list[list[int]]] = []  # node -> level -> neighbour ids
        self._deleted: set[int] = set()
        self._entry = -1
        self._max_level = -1

    def __len__(self) -> int:
        return self._count - len(self._deleted)

    # distances (lower = closer) ---------------------------------------------------
    def _dist(self, q: np.ndarray, idxs: list[int]) -> np.ndarray:
        x = self._data[idxs]
        if self.metric in (Metric.COSINE, Metric.DOT):
            return -(x @ q)
        diff = x - q
        return np.einsum("ij,ij->i", diff, diff)

    def _random_level(self) -> int:
        return int(-math.log(1.0 - self._rng.random()) * self._ml)

    def _search_layer(
        self, q: np.ndarray, entry_points: list[int], ef: int, level: int
    ) -> list[tuple[float, int]]:
        visited = set(entry_points)
        dists = self._dist(q, entry_points)
        candidates = [(float(d), e) for d, e in zip(dists, entry_points)]
        heapq.heapify(candidates)
        results = [(-d, e) for d, e in candidates]  # max-heap of the best ``ef``
        heapq.heapify(results)
        while len(results) > ef:
            heapq.heappop(results)
        while candidates:
            dc, c = heapq.heappop(candidates)
            if dc > -results[0][0] and len(results) >= ef:
                break
            links = self._links[c][level] if level < len(self._links[c]) else []
            fresh = [n for n in links if n not in visited]
            if not fresh:
                continue
            visited.update(fresh)
            for d, n in zip(self._dist(q, fresh), fresh):
                d = float(d)
                if len(results) < ef or d < -results[0][0]:
                    heapq.heappush(candidates, (d, n))
                    heapq.heappush(results, (-d, n))
                    if len(results) > ef:
                        heapq.heappop(results)
        return sorted((-nd, n) for nd, n in results)

    def _select_neighbors(self, candidates: list[tuple[float, int]], m: int) -> list[int]:
        """Heuristic selection: prefer candidates that are not 'covered' by closer picks."""
        selected: list[int] = []
        pruned: list[int] = []
        for d, c in candidates:
            if len(selected) >= m:
                break
            if not selected or bool(np.all(d < self._dist(self._data[c], selected))):
                selected.append(c)
            else:
                pruned.append(c)
        for c in pruned:  # keepPrunedConnections
            if len(selected) >= m:
                break
            selected.append(c)
        return selected

    def _ensure_capacity(self, extra: int) -> None:
        needed = self._count + extra
        if needed > len(self._data):
            cap = max(needed, 2 * len(self._data))
            grown = np.zeros((cap, self.dimension), dtype=np.float32)
            grown[: self._count] = self._data[: self._count]
            self._data = grown

    def _insert(self, vec: np.ndarray, id_: str) -> None:
        if id_ in self._pos:  # upsert: tombstone the old node
            self._deleted.add(self._pos[id_])
        node = self._count
        self._data[node] = vec
        self._count += 1
        self._ids.append(id_)
        self._pos[id_] = node
        level = self._random_level()
        self._levels.append(level)
        self._links.append([[] for _ in range(level + 1)])

        if self._entry < 0:
            self._entry, self._max_level = node, level
            return

        ep = [self._entry]
        for lc in range(self._max_level, level, -1):
            ep = [self._search_layer(vec, ep, 1, lc)[0][1]]
        for lc in range(min(level, self._max_level), -1, -1):
            w = self._search_layer(vec, ep, self.ef_construction, lc)
            m_max = self.M0 if lc == 0 else self.M
            neighbors = self._select_neighbors(w, self.M)
            self._links[node][lc] = neighbors
            for n in neighbors:
                links = self._links[n][lc]
                links.append(node)
                if len(links) > m_max:
                    d = self._dist(self._data[n], links)
                    ranked = sorted(zip(d.tolist(), links))
                    self._links[n][lc] = self._select_neighbors(ranked, m_max)
            ep = [n for _, n in w]
        if level > self._max_level:
            self._entry, self._max_level = node, level

    def add(
        self, vectors: Any, ids: list[str], metadata: list[dict[str, Any]] | None = None
    ) -> None:
        vecs = self._prep(as_matrix(vectors, self.dimension))
        if len(ids) != len(vecs):
            raise ValueError("number of ids must match number of vectors")
        self._ensure_capacity(len(vecs))
        for vec, id_ in zip(vecs, ids):
            self._insert(vec, id_)
        self._store_metadata(ids, metadata)

    def search(
        self, query: Any, k: int = 10, filter: Filter | None = None, ef: int | None = None
    ) -> list[SearchResult]:
        if len(self) == 0:
            return []
        q = self._prep(as_matrix(query, self.dimension))[0]
        ep = [self._entry]
        for lc in range(self._max_level, 0, -1):
            ep = [self._search_layer(q, ep, 1, lc)[0][1]]
        ef = max(ef or self.ef_search, k)
        if filter is not None or self._deleted:
            ef = max(ef, 4 * k)
        found = self._search_layer(q, ep, ef, 0)
        out = []
        for d, n in found:
            if n in self._deleted:
                continue
            id_ = self._ids[n]
            if not self._passes(id_, filter):
                continue
            out.append(SearchResult(id_, -d, self.metadata.get(id_)))
            if len(out) >= k:
                break
        return out

    def delete(self, ids: list[str]) -> None:
        for i in ids:
            if i in self._pos:
                self._deleted.add(self._pos.pop(i))
                self.metadata.pop(i, None)

    def stats(self) -> dict[str, Any]:
        degrees = [len(lv[0]) for lv in self._links] if self._links else [0]
        return {
            "size": len(self),
            "max_level": self._max_level,
            "avg_degree_l0": float(np.mean(degrees)),
            "deleted": len(self._deleted),
        }

    def _state(self) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        return (
            {"data": self._data[: self._count]},
            {
                "ids": self._ids,
                "levels": self._levels,
                "links": json.dumps(self._links),
                "deleted": sorted(self._deleted),
                "entry": self._entry,
                "max_level": self._max_level,
                "params": {
                    "M": self.M,
                    "ef_construction": self.ef_construction,
                    "ef_search": self.ef_search,
                    "seed": self.seed,
                },
            },
        )

    @classmethod
    def _from_state(cls, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> HNSWIndex:
        idx = cls(meta["dimension"], meta["metric"], **meta["params"])
        data = arrays["data"].astype(np.float32)
        idx._data = data.copy() if len(data) else idx._data
        idx._count = len(data)
        idx._ids = list(meta["ids"])
        idx._levels = list(meta["levels"])
        idx._links = json.loads(meta["links"])
        idx._deleted = set(meta["deleted"])
        idx._pos = {id_: n for n, id_ in enumerate(idx._ids) if n not in idx._deleted}
        idx._entry = meta["entry"]
        idx._max_level = meta["max_level"]
        return idx
