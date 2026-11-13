---
title: Vector indexes
description: Flat, HNSW, IVF, scalar and product quantization indexes implemented with numpy, with metadata filters, deletes and save/load.
---

`agentcore.index` implements approximate nearest-neighbour search from scratch with numpy. The
indexes share one interface (`add`, `search`, `delete`, `save`, `load_index`) and plug into
[RAG](/agentcore/docs/modules/rag/) and long-term memory.

```python
import numpy as np

from agentcore.index import FlatIndex, HNSWIndex, IVFIndex, PQIndex, load_index, recall_at_k

x = np.random.default_rng(0).normal(size=(2000, 64)).astype("float32")
ids = [f"v{i}" for i in range(len(x))]

flat = FlatIndex(64)  # exact search, the ground truth
hnsw = HNSWIndex(64, M=16, ef_construction=200, ef_search=64)
ivf = IVFIndex(64, nlist=32, nprobe=8)
pq = PQIndex(64, m=8)
for idx in (flat, hnsw, ivf, pq):
    idx.add(x, ids)

truth = [[r.id for r in flat.search(q, 10)] for q in x[:20]]
for name, idx in [("hnsw", hnsw), ("ivf", ivf), ("pq", pq)]:
    approx = [[r.id for r in idx.search(q, 10)] for q in x[:20]]
    print(name, round(recall_at_k(truth, approx, 10), 3))

hnsw.save("hnsw.npz")
same = load_index("hnsw.npz")
print(type(same).__name__, len(same))
```

On this random 64-dimensional data the script prints recall@10 of `1.0` for HNSW, `0.715` for IVF
and `0.475` for PQ, then `HNSWIndex 2000`. Random Gaussian vectors are a hard case for IVF and PQ;
on real embeddings, which cluster, their recall is typically much higher. Measure on your own data
with `recall_at_k`.

## Index types

| Class | How it works | Main parameters |
|---|---|---|
| `FlatIndex` | Exact brute-force search | `dimension`, `metric` |
| `HNSWIndex` | Hierarchical navigable small-world graph: greedy search from the top layer down, `ef_search` candidates per query | `M`, `ef_construction`, `ef_search`, `seed` |
| `IVFIndex` | Inverted file: k-means++ coarse clusters, search the `nprobe` closest lists | `nlist`, `nprobe` |
| `SQIndex` | Scalar quantization to int8 per dimension | `dimension`, `metric` |
| `PQIndex` | Product quantization: `m` sub-spaces with 256 centroids each, asymmetric distance computation (ADC) | `m`, `ksub` |

`metric` is `cosine` (default), `l2` or `dot`. Every index supports metadata filters at search
time (`search(query, k, filter=...)`), `search_batch`, deletes and `save()` / `load_index()`.
`create_index(kind, dimension, metric, **kwargs)` builds one by name (`flat`, `hnsw`, `ivf`, `sq8`,
`pq`); `kmeans` and the `ScalarQuantizer` / `ProductQuantizer` building
blocks are exported too.
