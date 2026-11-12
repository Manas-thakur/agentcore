from __future__ import annotations

import numpy as np
import pytest

from agentcore.index import (
    FlatIndex,
    HNSWIndex,
    IVFIndex,
    Metric,
    PQIndex,
    ProductQuantizer,
    ScalarQuantizer,
    SQIndex,
    create_index,
    kmeans,
    load_index,
    recall_at_k,
)


@pytest.fixture(scope="module")
def data():
    rng = np.random.default_rng(7)
    # clustered data looks more like real embeddings than pure noise
    centers = rng.normal(size=(20, 24))
    x = (centers[rng.integers(20, size=800)] + 0.35 * rng.normal(size=(800, 24))).astype(np.float32)
    q = (centers[rng.integers(20, size=40)] + 0.35 * rng.normal(size=(40, 24))).astype(np.float32)
    return x, q, [f"v{i}" for i in range(len(x))]


def truth(x, q, ids, k=10, metric=Metric.COSINE):
    flat = FlatIndex(x.shape[1], metric)
    flat.add(x, ids)
    return [[r.id for r in flat.search(v, k)] for v in q]


def ids_of(index, q, k=10):
    return [[r.id for r in index.search(v, k)] for v in q]


def test_flat_is_exact_for_all_metrics():
    x = np.array([[1, 0], [0, 1], [0.9, 0.1], [-1, 0]], dtype=np.float32)
    for metric, expected in [
        (Metric.COSINE, ["a", "c"]),
        (Metric.DOT, ["a", "c"]),
        (Metric.L2, ["a", "c"]),
    ]:
        idx = FlatIndex(2, metric)
        idx.add(x, ["a", "b", "c", "d"])
        assert [r.id for r in idx.search([1, 0], 2)] == expected
    idx = FlatIndex(2)
    idx.add(x, ["a", "b", "c", "d"], metadata=[{"lang": "en"}, {}, {"lang": "fr"}, {}])
    filtered = idx.search([1, 0], 5, filter=lambda i, m: m.get("lang") == "fr")
    assert [r.id for r in filtered] == ["c"] and filtered[0].metadata == {"lang": "fr"}
    idx.delete(["a"])
    assert len(idx) == 3 and idx.search([1, 0], 1)[0].id == "c"
    idx.add([[0, -1]], ["b"])  # upsert
    assert len(idx) == 3 and idx.search([0, -1], 1)[0].id == "b"


def test_hnsw_recall_vs_flat(data):
    x, q, ids = data
    gt = truth(x, q, ids)
    hnsw = HNSWIndex(x.shape[1], M=12, ef_construction=80, ef_search=60, seed=1)
    hnsw.add(x, ids)
    assert len(hnsw) == len(x)
    r = recall_at_k(gt, ids_of(hnsw, q), 10)
    assert r >= 0.9, r
    assert hnsw.stats()["max_level"] >= 1


def test_hnsw_delete_filter_and_l2(data):
    x, q, ids = data
    hnsw = HNSWIndex(x.shape[1], Metric.L2, M=8, ef_construction=60, seed=3)
    hnsw.add(x[:300], ids[:300])
    top = hnsw.search(x[5], 1)[0]
    assert top.id == "v5" and top.score == pytest.approx(0.0, abs=1e-4)
    hnsw.delete(["v5"])
    assert all(r.id != "v5" for r in hnsw.search(x[5], 5))
    even = hnsw.search(x[6], 5, filter=lambda i, m: int(i[1:]) % 2 == 0)
    assert even and all(int(r.id[1:]) % 2 == 0 for r in even)


def test_ivf_recall_improves_with_nprobe(data):
    x, q, ids = data
    gt = truth(x, q, ids)
    ivf = IVFIndex(x.shape[1], nlist=16, nprobe=1, seed=0)
    ivf.add(x, ids)
    low = recall_at_k(gt, [[r.id for r in ivf.search(v, 10, nprobe=1)] for v in q], 10)
    high = recall_at_k(gt, [[r.id for r in ivf.search(v, 10, nprobe=8)] for v in q], 10)
    assert high >= low and high >= 0.9, (low, high)
    assert sum(ivf.list_sizes()) == len(x)


def test_quantizers(data):
    x, q, ids = data
    sq = ScalarQuantizer()
    sq.train(x)
    codes = sq.encode(x)
    assert codes.dtype == np.uint8
    assert np.abs(sq.decode(codes) - x).max() < (x.max() - x.min()) / 255 + 1e-5

    pq = ProductQuantizer(m=6, ksub=32, seed=0)
    pq.train(x)
    pcodes = pq.encode(x)
    assert pcodes.shape == (len(x), 6)
    err = np.mean(np.linalg.norm(pq.decode(pcodes) - x, axis=1)) / np.mean(
        np.linalg.norm(x, axis=1)
    )
    assert err < 0.5
    # ADC distances approximate exact squared distances
    exact = ((pq.decode(pcodes) - q[0]) ** 2).sum(1)
    assert np.allclose(pq.adc(q[0], pcodes), exact, rtol=1e-3, atol=1e-3)

    gt = truth(x, q, ids)
    sqi = SQIndex(x.shape[1])
    sqi.add(x, ids)
    assert recall_at_k(gt, ids_of(sqi, q), 10) >= 0.9
    pqi = PQIndex(x.shape[1], m=6, ksub=32)
    pqi.add(x, ids)
    assert recall_at_k(gt, ids_of(pqi, q), 10) >= 0.4


def test_kmeans_finds_clusters():
    rng = np.random.default_rng(0)
    a = rng.normal(loc=-5, size=(50, 2))
    b = rng.normal(loc=5, size=(50, 2))
    centroids, assign = kmeans(np.vstack([a, b]), 2, seed=0)
    assert len(set(assign[:50])) == 1 and len(set(assign[50:])) == 1 and assign[0] != assign[-1]
    assert sorted(np.round(centroids[:, 0]).tolist()) == pytest.approx([-5, 5], abs=1)


@pytest.mark.parametrize("kind", ["flat", "hnsw", "ivf", "sq8", "pq"])
def test_save_load_roundtrip(kind, data, tmp_path):
    x, q, ids = data
    kwargs = {
        "pq": {"m": 4, "ksub": 16},
        "ivf": {"nlist": 8},
        "hnsw": {"M": 8, "ef_construction": 40},
    }.get(kind, {})
    idx = create_index(kind, x.shape[1], **kwargs)
    idx.add(x[:200], ids[:200], metadata=[{"n": i} for i in range(200)])
    idx.delete(["v3"])
    before = ids_of(idx, q[:5], 5)
    path = idx.save(tmp_path / f"{kind}.npz")
    loaded = load_index(path)
    assert type(loaded) is type(idx) and len(loaded) == len(idx) == 199
    assert ids_of(loaded, q[:5], 5) == before
    assert loaded.metadata["v7"] == {"n": 7}


def test_dimension_mismatch_raises():
    idx = FlatIndex(4)
    with pytest.raises(ValueError):
        idx.add(np.zeros((2, 3)), ["a", "b"])
    with pytest.raises(ValueError):
        create_index("nope", 4)
