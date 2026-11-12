"""Inverted-file index: k-means coarse quantizer + per-cluster posting lists."""

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
)
from agentcore.index.kmeans import _sq_dists, kmeans


class IVFIndex(VectorIndex):
    """Search visits only the ``nprobe`` clusters closest to the query.

    Call :meth:`train` with a representative sample, or let the first :meth:`add`
    train on the vectors it receives.
    """

    kind = "ivf"

    def __init__(
        self,
        dimension: int,
        metric: Metric | str = Metric.COSINE,
        *,
        nlist: int = 64,
        nprobe: int = 8,
        seed: int = 0,
    ):
        super().__init__(dimension, metric)
        self.nlist = nlist
        self.nprobe = nprobe
        self.seed = seed
        self.centroids: np.ndarray | None = None
        self._lists: list[list[int]] = []
        self._data = np.zeros((0, self.dimension), dtype=np.float32)
        self._ids: list[str] = []
        self._pos: dict[str, int] = {}
        self._deleted: set[int] = set()

    @property
    def is_trained(self) -> bool:
        return self.centroids is not None

    def __len__(self) -> int:
        return len(self._ids) - len(self._deleted)

    def train(self, vectors: Any) -> None:
        x = self._prep(as_matrix(vectors, self.dimension))
        self.centroids, _ = kmeans(x, self.nlist, seed=self.seed)
        self.nlist = len(self.centroids)
        self._lists = [[] for _ in range(self.nlist)]

    def _assign(self, x: np.ndarray) -> np.ndarray:
        assert self.centroids is not None
        if self.metric == Metric.L2:
            return np.argmin(_sq_dists(x, self.centroids), axis=1)
        return np.argmax(x @ self.centroids.T, axis=1)

    def add(
        self, vectors: Any, ids: list[str], metadata: list[dict[str, Any]] | None = None
    ) -> None:
        raw = as_matrix(vectors, self.dimension)
        if len(ids) != len(raw):
            raise ValueError("number of ids must match number of vectors")
        if not self.is_trained:
            self.train(raw)
        x = self._prep(raw)
        self.delete([i for i in ids if i in self._pos])  # upsert
        start = len(self._ids)
        self._data = np.vstack([self._data, x])
        for offset, (id_, cluster) in enumerate(zip(ids, self._assign(x))):
            row = start + offset
            self._ids.append(id_)
            self._pos[id_] = row
            self._lists[int(cluster)].append(row)
        self._store_metadata(ids, metadata)

    def search(
        self, query: Any, k: int = 10, filter: Filter | None = None, nprobe: int | None = None
    ) -> list[SearchResult]:
        if len(self) == 0 or self.centroids is None:
            return []
        q = self._prep(as_matrix(query, self.dimension))[0]
        probe = min(nprobe or self.nprobe, self.nlist)
        centroid_scores = scores_for(
            self.metric if self.metric == Metric.L2 else Metric.DOT, self.centroids, q
        )
        clusters = top_k(centroid_scores, probe)
        rows = [r for c in clusters for r in self._lists[int(c)] if r not in self._deleted]
        if filter is not None:
            rows = [r for r in rows if self._passes(self._ids[r], filter)]
        if not rows:
            return []
        rows_arr = np.asarray(rows)
        scores = scores_for(self.metric, self._data[rows_arr], q)
        return [
            SearchResult(
                self._ids[rows_arr[i]], float(scores[i]), self.metadata.get(self._ids[rows_arr[i]])
            )
            for i in top_k(scores, k)
        ]

    def delete(self, ids: list[str]) -> None:
        for i in ids:
            if i in self._pos:
                self._deleted.add(self._pos.pop(i))
                self.metadata.pop(i, None)

    def list_sizes(self) -> list[int]:
        return [len([r for r in lst if r not in self._deleted]) for lst in self._lists]

    def _state(self) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        arrays = {"data": self._data}
        if self.centroids is not None:
            arrays["centroids"] = self.centroids
        return arrays, {
            "ids": self._ids,
            "lists": self._lists,
            "deleted": sorted(self._deleted),
            "params": {"nlist": self.nlist, "nprobe": self.nprobe, "seed": self.seed},
        }

    @classmethod
    def _from_state(cls, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> IVFIndex:
        idx = cls(meta["dimension"], meta["metric"], **meta["params"])
        idx._data = arrays["data"].astype(np.float32)
        idx.centroids = arrays.get("centroids")
        idx._ids = list(meta["ids"])
        idx._lists = [list(x) for x in meta["lists"]]
        idx._deleted = set(meta["deleted"])
        idx._pos = {id_: r for r, id_ in enumerate(idx._ids) if r not in idx._deleted}
        return idx
