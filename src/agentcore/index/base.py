"""The ``VectorIndex`` interface shared by Flat, HNSW, IVF and quantized indexes."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np


class Metric(str, Enum):
    COSINE = "cosine"
    L2 = "l2"
    DOT = "dot"


@dataclass
class SearchResult:
    id: str
    score: float  # higher is better (cosine/dot similarity, or negative squared L2)
    metadata: dict[str, Any] | None = None


# A search filter is either a callable ``filter(id, metadata) -> bool`` or a dict of
# metadata conditions that must all hold: ``{"lang": "en"}`` (equality) or
# ``{"lang": ["en", "de"]}`` (one of). Items without metadata never match a dict filter.
Filter = Callable[[str, dict[str, Any]], bool] | Mapping[str, Any]


def matches_filter(filter: Filter | None, id_: str, metadata: dict[str, Any]) -> bool:
    """Apply a callable or dict :data:`Filter` to one item."""
    if filter is None:
        return True
    if isinstance(filter, Mapping):
        for key, want in filter.items():
            if key not in metadata:
                return False
            have = metadata[key]
            if isinstance(want, (list, tuple, set, frozenset)):
                if have not in want:
                    return False
            elif have != want:
                return False
        return True
    if callable(filter):
        return bool(filter(id_, metadata))
    raise TypeError(
        f"filter must be a callable(id, metadata) or a dict, got {type(filter).__name__}"
    )


def unique_batch(
    vectors: np.ndarray, ids: list[str], metadata: list[dict[str, Any]] | None
) -> tuple[np.ndarray, list[str], list[dict[str, Any]] | None]:
    """Upsert semantics inside one ``add()``: for repeated ids the last occurrence wins."""
    ids = [str(i) for i in ids]
    if len(ids) != len(vectors):
        raise ValueError("number of ids must match number of vectors")
    if metadata is not None and len(metadata) != len(ids):
        raise ValueError("metadata length must match ids")
    if len(set(ids)) == len(ids):
        return vectors, ids, metadata
    last = {id_: i for i, id_ in enumerate(ids)}
    keep = sorted(last.values())
    return (
        vectors[keep],
        [ids[i] for i in keep],
        None if metadata is None else [metadata[i] for i in keep],
    )


def normalize(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return x / norms


def as_matrix(vectors: Any, dimension: int | None = None) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.ndim != 2:
        raise ValueError(f"expected a 2-D array of vectors, got shape {arr.shape}")
    if dimension is not None and arr.shape[1] != dimension:
        raise ValueError(f"dimension mismatch: index has {dimension}, got {arr.shape[1]}")
    return arr


def scores_for(metric: Metric, data: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Similarity scores (higher = closer). Assumes cosine data is pre-normalised."""
    if metric in (Metric.COSINE, Metric.DOT):
        return data @ query
    diff = data - query
    return -np.einsum("ij,ij->i", diff, diff)


def top_k(scores: np.ndarray, k: int) -> np.ndarray:
    if len(scores) == 0:
        return np.array([], dtype=np.int64)
    k = min(k, len(scores))
    idx = np.argpartition(-scores, k - 1)[:k]
    return idx[np.argsort(-scores[idx], kind="stable")]


class VectorIndex(ABC):
    """Abstract vector index. Ids are strings; optional per-id metadata dicts."""

    kind: str = "base"

    def __init__(self, dimension: int, metric: Metric | str = Metric.COSINE):
        self.dimension = int(dimension)
        self.metric = Metric(metric)
        self.metadata: dict[str, dict[str, Any]] = {}

    @abstractmethod
    def add(
        self,
        vectors: Any,
        ids: list[str],
        metadata: list[dict[str, Any]] | None = None,
    ) -> None: ...

    @abstractmethod
    def search(
        self, query: Any, k: int = 10, filter: Filter | None = None
    ) -> list[SearchResult]: ...

    @abstractmethod
    def delete(self, ids: list[str]) -> None: ...

    @abstractmethod
    def __len__(self) -> int: ...

    def add_item(self, vector: Any, id: str, metadata: dict[str, Any] | None = None) -> None:
        self.add(as_matrix(vector), [id], [metadata] if metadata else None)

    def search_batch(self, queries: Any, k: int = 10) -> list[list[SearchResult]]:
        return [self.search(q, k) for q in as_matrix(queries, self.dimension)]

    def _prep(self, vectors: np.ndarray) -> np.ndarray:
        return normalize(vectors) if self.metric == Metric.COSINE else vectors

    def _store_metadata(self, ids: list[str], metadata: list[dict[str, Any]] | None) -> None:
        if metadata is not None:
            if len(metadata) != len(ids):
                raise ValueError("metadata length must match ids")
            for i, m in zip(ids, metadata):
                if m:
                    self.metadata[i] = dict(m)

    def _passes(self, id_: str, filter: Filter | None) -> bool:
        return matches_filter(filter, id_, self.metadata.get(id_, {}))

    # persistence -------------------------------------------------------------
    def _state(self) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        raise NotImplementedError

    @classmethod
    def _from_state(cls, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> VectorIndex:
        raise NotImplementedError

    def save(self, path: str | Path) -> Path:
        arrays, meta = self._state()
        meta = {
            "kind": self.kind,
            "dimension": self.dimension,
            "metric": self.metric.value,
            "metadata": self.metadata,
            **meta,
        }
        path = Path(path)
        if path.suffix != ".npz":
            path = path.with_suffix(".npz")
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, __meta__=np.array(json.dumps(meta)), **arrays)
        return path

    @classmethod
    def load(cls, path: str | Path) -> VectorIndex:
        return load_index(path)


def load_index(path: str | Path) -> VectorIndex:
    """Load any index saved with :meth:`VectorIndex.save`."""
    from agentcore.index.flat import FlatIndex
    from agentcore.index.hnsw import HNSWIndex
    from agentcore.index.ivf import IVFIndex
    from agentcore.index.quantization import PQIndex, SQIndex

    path = Path(path)
    if not path.exists() and path.with_suffix(".npz").exists():
        path = path.with_suffix(".npz")
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["__meta__"]))
        arrays = {k: data[k] for k in data.files if k != "__meta__"}
    registry: dict[str, type[VectorIndex]] = {
        c.kind: c for c in (FlatIndex, HNSWIndex, IVFIndex, PQIndex, SQIndex)
    }
    cls = registry[meta["kind"]]
    index = cls._from_state(arrays, meta)
    index.metadata = meta.get("metadata", {})
    return index
