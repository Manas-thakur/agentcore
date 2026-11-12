"""k-means with k-means++ initialisation (used by IVF and product quantization)."""

from __future__ import annotations

import numpy as np


def _sq_dists(x: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    # ||x - c||^2 = ||x||^2 - 2 x.c + ||c||^2, computed for all pairs at once
    return (
        np.einsum("ij,ij->i", x, x)[:, None]
        - 2.0 * x @ centroids.T
        + np.einsum("ij,ij->i", centroids, centroids)[None, :]
    )


def kmeans_plus_plus(x: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    n = len(x)
    centroids = [x[rng.integers(n)]]
    closest = _sq_dists(x, np.asarray(centroids))[:, 0]
    for _ in range(1, k):
        probs = np.maximum(closest, 0)
        total = probs.sum()
        idx = rng.integers(n) if total <= 0 else rng.choice(n, p=probs / total)
        centroids.append(x[idx])
        closest = np.minimum(closest, _sq_dists(x, x[idx][None, :])[:, 0])
    return np.asarray(centroids, dtype=np.float32)


def kmeans(
    x: np.ndarray, k: int, *, iterations: int = 25, seed: int = 0, tol: float = 1e-4
) -> tuple[np.ndarray, np.ndarray]:
    """Lloyd's algorithm. Returns ``(centroids [k, d], assignments [n])``."""
    x = np.asarray(x, dtype=np.float32)
    if len(x) == 0:
        raise ValueError("cannot run k-means on an empty array")
    k = min(k, len(x))
    rng = np.random.default_rng(seed)
    centroids = kmeans_plus_plus(x, k, rng)
    assign = np.zeros(len(x), dtype=np.int64)
    for _ in range(iterations):
        assign = np.argmin(_sq_dists(x, centroids), axis=1)
        new = np.zeros_like(centroids)
        counts = np.bincount(assign, minlength=k)
        np.add.at(new, assign, x)
        empty = counts == 0
        new[~empty] /= counts[~empty, None]
        if empty.any():  # re-seed empty clusters with random points
            new[empty] = x[rng.integers(len(x), size=int(empty.sum()))]
        shift = float(np.max(np.linalg.norm(new - centroids, axis=1)))
        centroids = new
        if shift < tol:
            break
    assign = np.argmin(_sq_dists(x, centroids), axis=1)
    return centroids, assign
