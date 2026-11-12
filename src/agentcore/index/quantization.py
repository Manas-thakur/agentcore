"""Vector quantization: scalar (int8) and product quantization, plus indexes using them.

* ``ScalarQuantizer`` maps each dimension's [min, max] range onto 0..255 (4x smaller).
* ``ProductQuantizer`` splits vectors into ``m`` sub-vectors and replaces each with the id
  of its nearest k-means centroid (``m`` bytes per vector; e.g. 384-d float32 -> 48 bytes).
  Search uses asymmetric distance computation (ADC) with per-query lookup tables.
"""

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
from agentcore.index.kmeans import kmeans


class ScalarQuantizer:
    def __init__(self) -> None:
        self.vmin: np.ndarray | None = None
        self.scale: np.ndarray | None = None

    def train(self, vectors: np.ndarray) -> None:
        x = np.asarray(vectors, dtype=np.float32)
        self.vmin = x.min(axis=0)
        span = x.max(axis=0) - self.vmin
        self.scale = np.where(span > 0, span / 255.0, 1.0).astype(np.float32)

    def encode(self, vectors: np.ndarray) -> np.ndarray:
        if self.vmin is None or self.scale is None:
            raise RuntimeError("ScalarQuantizer is not trained")
        q = np.round((np.asarray(vectors, dtype=np.float32) - self.vmin) / self.scale)
        return np.clip(q, 0, 255).astype(np.uint8)

    def decode(self, codes: np.ndarray) -> np.ndarray:
        if self.vmin is None or self.scale is None:
            raise RuntimeError("ScalarQuantizer is not trained")
        return codes.astype(np.float32) * self.scale + self.vmin


class ProductQuantizer:
    def __init__(self, m: int = 8, ksub: int = 256, seed: int = 0, iterations: int = 20):
        if ksub > 256:
            raise ValueError("ksub must be <= 256 so codes fit in uint8")
        self.m = m
        self.ksub = ksub
        self.seed = seed
        self.iterations = iterations
        self.codebooks: np.ndarray | None = None  # (m, ksub, dsub)
        self.dsub = 0

    def train(self, vectors: np.ndarray) -> None:
        x = np.asarray(vectors, dtype=np.float32)
        d = x.shape[1]
        if d % self.m:
            raise ValueError(f"dimension {d} is not divisible by m={self.m}")
        self.dsub = d // self.m
        k = min(self.ksub, len(x))
        books = np.zeros((self.m, k, self.dsub), dtype=np.float32)
        for j in range(self.m):
            sub = x[:, j * self.dsub : (j + 1) * self.dsub]
            centroids, _ = kmeans(sub, k, seed=self.seed + j, iterations=self.iterations)
            books[j, : len(centroids)] = centroids
        self.codebooks = books

    def encode(self, vectors: np.ndarray) -> np.ndarray:
        if self.codebooks is None:
            raise RuntimeError("ProductQuantizer is not trained")
        x = np.asarray(vectors, dtype=np.float32)
        codes = np.zeros((len(x), self.m), dtype=np.uint8)
        for j in range(self.m):
            sub = x[:, j * self.dsub : (j + 1) * self.dsub]
            book = self.codebooks[j]
            d = (sub**2).sum(1)[:, None] - 2 * sub @ book.T + (book**2).sum(1)[None, :]
            codes[:, j] = np.argmin(d, axis=1)
        return codes

    def decode(self, codes: np.ndarray) -> np.ndarray:
        if self.codebooks is None:
            raise RuntimeError("ProductQuantizer is not trained")
        return np.concatenate([self.codebooks[j][codes[:, j]] for j in range(self.m)], axis=1)

    def lookup_tables(self, query: np.ndarray, inner_product: bool = False) -> np.ndarray:
        """Per-subspace distance (or -inner-product) from the query to every centroid."""
        assert self.codebooks is not None
        q = query.reshape(self.m, 1, self.dsub)
        if inner_product:
            return -(self.codebooks * q).sum(-1)
        return ((self.codebooks - q) ** 2).sum(-1)

    def adc(self, query: np.ndarray, codes: np.ndarray, inner_product: bool = False) -> np.ndarray:
        """Approximate distances from ``query`` to every encoded vector (lower = closer)."""
        tables = self.lookup_tables(np.asarray(query, dtype=np.float32), inner_product)
        return tables[np.arange(self.m)[None, :], codes].sum(axis=1)


class _QuantizedIndex(VectorIndex):
    """Shared plumbing for indexes that store only compressed codes."""

    def __init__(self, dimension: int, metric: Metric | str = Metric.COSINE):
        super().__init__(dimension, metric)
        self._codes: np.ndarray | None = None
        self._ids: list[str] = []
        self._pos: dict[str, int] = {}
        self._deleted: set[int] = set()

    def __len__(self) -> int:
        return len(self._ids) - len(self._deleted)

    def delete(self, ids: list[str]) -> None:
        for i in ids:
            if i in self._pos:
                self._deleted.add(self._pos.pop(i))
                self.metadata.pop(i, None)

    def _append(
        self, codes: np.ndarray, ids: list[str], metadata: list[dict[str, Any]] | None
    ) -> None:
        self.delete([i for i in ids if i in self._pos])
        start = len(self._ids)
        self._codes = codes if self._codes is None else np.vstack([self._codes, codes])
        for offset, id_ in enumerate(ids):
            self._ids.append(id_)
            self._pos[id_] = start + offset
        self._store_metadata(ids, metadata)

    def _results(self, scores: np.ndarray, k: int, filter: Filter | None) -> list[SearchResult]:
        mask = np.ones(len(scores), dtype=bool)
        for r in self._deleted:
            mask[r] = False
        if filter is not None:
            mask &= np.array([self._passes(i, filter) for i in self._ids])
        scores = np.where(mask, scores, -np.inf)
        return [
            SearchResult(self._ids[i], float(scores[i]), self.metadata.get(self._ids[i]))
            for i in top_k(scores, k)
            if not np.isneginf(scores[i])
        ]


class SQIndex(_QuantizedIndex):
    """Flat index over int8 scalar-quantized vectors."""

    kind = "sq8"

    def __init__(self, dimension: int, metric: Metric | str = Metric.COSINE):
        super().__init__(dimension, metric)
        self.quantizer = ScalarQuantizer()

    def add(
        self, vectors: Any, ids: list[str], metadata: list[dict[str, Any]] | None = None
    ) -> None:
        x = self._prep(as_matrix(vectors, self.dimension))
        if self.quantizer.vmin is None:
            self.quantizer.train(x)
        self._append(self.quantizer.encode(x), ids, metadata)

    def search(self, query: Any, k: int = 10, filter: Filter | None = None) -> list[SearchResult]:
        if self._codes is None or len(self) == 0:
            return []
        q = self._prep(as_matrix(query, self.dimension))[0]
        return self._results(
            scores_for(self.metric, self.quantizer.decode(self._codes), q), k, filter
        )

    def _state(self) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        return (
            {
                "codes": self._codes
                if self._codes is not None
                else np.zeros((0, self.dimension), np.uint8),
                "vmin": self.quantizer.vmin if self.quantizer.vmin is not None else np.zeros(0),
                "scale": self.quantizer.scale if self.quantizer.scale is not None else np.zeros(0),
            },
            {"ids": self._ids, "deleted": sorted(self._deleted)},
        )

    @classmethod
    def _from_state(cls, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> SQIndex:
        idx = cls(meta["dimension"], meta["metric"])
        if len(arrays["vmin"]):
            idx.quantizer.vmin, idx.quantizer.scale = arrays["vmin"], arrays["scale"]
            idx._codes = arrays["codes"]
        idx._ids = list(meta["ids"])
        idx._deleted = set(meta["deleted"])
        idx._pos = {id_: r for r, id_ in enumerate(idx._ids) if r not in idx._deleted}
        return idx


class PQIndex(_QuantizedIndex):
    """Flat index over product-quantized codes with ADC search (+ optional exact re-rank)."""

    kind = "pq"

    def __init__(
        self,
        dimension: int,
        metric: Metric | str = Metric.COSINE,
        *,
        m: int = 8,
        ksub: int = 256,
        seed: int = 0,
    ):
        super().__init__(dimension, metric)
        self.quantizer = ProductQuantizer(m=m, ksub=ksub, seed=seed)

    def train(self, vectors: Any) -> None:
        self.quantizer.train(self._prep(as_matrix(vectors, self.dimension)))

    def add(
        self, vectors: Any, ids: list[str], metadata: list[dict[str, Any]] | None = None
    ) -> None:
        x = self._prep(as_matrix(vectors, self.dimension))
        if self.quantizer.codebooks is None:
            self.quantizer.train(x)
        self._append(self.quantizer.encode(x), ids, metadata)

    def search(self, query: Any, k: int = 10, filter: Filter | None = None) -> list[SearchResult]:
        if self._codes is None or len(self) == 0:
            return []
        q = self._prep(as_matrix(query, self.dimension))[0]
        ip = self.metric in (Metric.COSINE, Metric.DOT)
        dist = self.quantizer.adc(q, self._codes, inner_product=ip)
        return self._results(-dist, k, filter)

    def _state(self) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        pq = self.quantizer
        return (
            {
                "codes": self._codes if self._codes is not None else np.zeros((0, pq.m), np.uint8),
                "codebooks": pq.codebooks if pq.codebooks is not None else np.zeros(0),
            },
            {
                "ids": self._ids,
                "deleted": sorted(self._deleted),
                "params": {"m": pq.m, "ksub": pq.ksub, "seed": pq.seed},
                "dsub": pq.dsub,
            },
        )

    @classmethod
    def _from_state(cls, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> PQIndex:
        idx = cls(meta["dimension"], meta["metric"], **meta["params"])
        if arrays["codebooks"].size:
            idx.quantizer.codebooks = arrays["codebooks"]
            idx.quantizer.dsub = meta["dsub"]
            idx._codes = arrays["codes"]
        idx._ids = list(meta["ids"])
        idx._deleted = set(meta["deleted"])
        idx._pos = {id_: r for r, id_ in enumerate(idx._ids) if r not in idx._deleted}
        return idx
