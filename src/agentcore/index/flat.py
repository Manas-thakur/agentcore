"""Exact brute-force index - the ground truth that approximate indexes are measured against."""

from __future__ import annotations

from typing import Any

import numpy as np

from agentcore.index.base import (
    Filter,
    Metric,
    SearchResult,
    VectorIndex,
    as_matrix,
    scores_for,
    top_k,
    unique_batch,
)


class FlatIndex(VectorIndex):
    kind = "flat"

    def __init__(self, dimension: int, metric: Metric | str = Metric.COSINE):
        super().__init__(dimension, metric)
        self._data = np.zeros((0, self.dimension), dtype=np.float32)
        self._ids: list[str] = []
        self._pos: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._ids)

    @property
    def ids(self) -> list[str]:
        return list(self._ids)

    def add(
        self, vectors: Any, ids: list[str], metadata: list[dict[str, Any]] | None = None
    ) -> None:
        vecs, ids, metadata = unique_batch(
            self._prep(as_matrix(vectors, self.dimension)), ids, metadata
        )
        new_rows, new_ids = [], []
        for vec, id_ in zip(vecs, ids):
            if id_ in self._pos:  # upsert
                self._data[self._pos[id_]] = vec
            else:
                new_rows.append(vec)
                new_ids.append(id_)
        if new_rows:
            start = len(self._ids)
            self._data = np.vstack([self._data, np.asarray(new_rows, dtype=np.float32)])
            for offset, id_ in enumerate(new_ids):
                self._pos[id_] = start + offset
            self._ids.extend(new_ids)
        self._store_metadata(ids, metadata)

    def get_vector(self, id_: str) -> np.ndarray:
        return self._data[self._pos[id_]].copy()

    def search(self, query: Any, k: int = 10, filter: Filter | None = None) -> list[SearchResult]:
        if not self._ids:
            return []
        q = self._prep(as_matrix(query, self.dimension))[0]
        scores = scores_for(self.metric, self._data, q)
        if filter is not None:
            mask = np.array([self._passes(i, filter) for i in self._ids])
            scores = np.where(mask, scores, -np.inf)
        out = []
        for idx in top_k(scores, k):
            if np.isneginf(scores[idx]):
                break
            id_ = self._ids[idx]
            out.append(SearchResult(id_, float(scores[idx]), self.metadata.get(id_)))
        return out

    def delete(self, ids: list[str]) -> None:
        drop = {self._pos[i] for i in ids if i in self._pos}
        if not drop:
            return
        keep = [r for r in range(len(self._ids)) if r not in drop]
        self._data = self._data[keep]
        self._ids = [self._ids[r] for r in keep]
        self._pos = {id_: r for r, id_ in enumerate(self._ids)}
        for i in ids:
            self.metadata.pop(i, None)

    def _state(self) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        return {"data": self._data}, {"ids": self._ids}

    @classmethod
    def _from_state(cls, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> FlatIndex:
        idx = cls(meta["dimension"], meta["metric"])
        idx._data = arrays["data"].astype(np.float32)
        idx._ids = list(meta["ids"])
        idx._pos = {id_: r for r, id_ in enumerate(idx._ids)}
        return idx
