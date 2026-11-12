"""Vector indexes from scratch: Flat (exact), HNSW, IVF, scalar/product quantization."""

from typing import Any

from agentcore.index.base import Metric, SearchResult, VectorIndex, load_index
from agentcore.index.flat import FlatIndex
from agentcore.index.hnsw import HNSWIndex
from agentcore.index.ivf import IVFIndex
from agentcore.index.kmeans import kmeans
from agentcore.index.quantization import PQIndex, ProductQuantizer, ScalarQuantizer, SQIndex


def create_index(
    kind: str, dimension: int, metric: Metric | str = Metric.COSINE, **kwargs: Any
) -> VectorIndex:
    """Factory: ``flat``, ``hnsw``, ``ivf``, ``sq8`` or ``pq``."""
    table = {"flat": FlatIndex, "hnsw": HNSWIndex, "ivf": IVFIndex, "sq8": SQIndex, "pq": PQIndex}
    try:
        cls = table[kind]
    except KeyError:
        raise ValueError(f"unknown index kind {kind!r}; choose from {sorted(table)}") from None
    return cls(dimension, metric, **kwargs)


def recall_at_k(truth: list[list[str]], approx: list[list[str]], k: int) -> float:
    """Average fraction of the true top-k ids that the approximate search returned."""
    if not truth:
        return 0.0
    hits = sum(len(set(t[:k]) & set(a[:k])) for t, a in zip(truth, approx))
    return hits / (k * len(truth))


__all__ = [
    "FlatIndex",
    "HNSWIndex",
    "IVFIndex",
    "Metric",
    "PQIndex",
    "ProductQuantizer",
    "SQIndex",
    "ScalarQuantizer",
    "SearchResult",
    "VectorIndex",
    "create_index",
    "kmeans",
    "load_index",
    "recall_at_k",
]
