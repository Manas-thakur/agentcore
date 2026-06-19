# Part 5: `agentcore-index` — Vector Index Abstraction

## Purpose

Vector indexes are the backbone of semantic search and long-term memory in agentic AI systems. This package provides a clean abstraction layer over different vector index algorithms and backends, allowing you to swap between HNSW, IVF, Flat, and third-party stores (LanceDB, Chroma, pgvector) without changing your application code.

The key insight: **a vector index is just a data structure that supports `add(embedding, id)` and `search(query_embedding, k) → list of (id, score)`**. Everything else (quantization, filtering, persistence) is an optimization or convenience layer.

## Architecture

```
VectorIndex (ABC)
├── FlatIndex          # Brute force, exact. O(n*d) search. Good for <10K vectors.
├── HNSWIndex          # Hierarchical Navigable Small World. O(log n). Good for 10K-1M+.
│   ├── Custom HNSW    # Full implementation from scratch
│   └── HNSWLib        # Wrapper around hnswlib (C++ backend, Python bindings)
├── IVFIndex           # Inverted File. O(n/probes). Good for 100K-10M.
│   ├── IVF-Flat       # IVF with flat (no compression) storage
│   └── IVF-PQ         # IVF with Product Quantization
└── BackendAdapter     # Abstraction over external stores
    ├── LanceDBIndex   # LanceDB (embedded, columnar, fast)
    ├── ChromaIndex    # ChromaDB
    ├── PGVectorIndex  # PostgreSQL + pgvector
    └── PineconeIndex  # Pinecone (cloud)
```

## Component Breakdown

### 1. `VectorIndex` Interface

**File:** `agentcore/index/base.py`

```python
class VectorIndex(ABC):
    """Abstract interface for vector similarity search indexes."""
    
    dimension: int
    metric: SimilarityMetric
    count: int
    
    @abstractmethod
    def add(self, vectors: np.ndarray, ids: list[str]) -> None: ...
    
    @abstractmethod
    def add_item(self, vector: np.ndarray, id: str) -> None: ...
    
    @abstractmethod
    def search(
        self, query: np.ndarray, k: int = 10,
        filters: dict | None = None,
    ) -> list[SearchResult]: ...
    
    @abstractmethod
    def delete(self, ids: list[str]) -> None: ...
    
    @abstractmethod
    def save(self, path: str) -> None: ...
    
    @classmethod
    def load(cls, path: str) -> VectorIndex: ...

@dataclass
class SearchResult:
    id: str
    score: float
    vector: np.ndarray | None = None
    metadata: dict | None = None

class SimilarityMetric(Enum):
    COSINE = "cosine"       # cosine_distance = 1 - cos_sim
    DOT_PRODUCT = "dot"     # inner_product
    EUCLIDEAN = "l2"        # squared_l2
```

**Key Design Decisions:**
- **NumPy arrays internally.** Vectors are stored as `np.ndarray` for performance. The interface accepts and returns NumPy arrays for zero-copy integration with embedding models.
- **String IDs.** All implementations use string IDs for maximum flexibility (UUIDs, document IDs, composite keys).
- **All search returns `list[SearchResult]` sorted by score descending.** Higher score = more similar.

---

### 2. Flat Index (Brute Force)

**File:** `agentcore/index/flat.py`

**Purpose:** The simplest possible vector index — store all vectors in a NumPy array, compute full similarity matrix on every query. Fast for small datasets (<10K vectors), and serves as the correctness reference for more complex indexes.

```python
class FlatIndex(VectorIndex):
    def __init__(self, dimension: int, metric: SimilarityMetric = SimilarityMetric.COSINE):
        self.vectors = np.empty((0, dimension), dtype=np.float32)
        self.ids: list[str] = []
        ...
    
    def search(self, query: np.ndarray, k: int = 10, filters: dict | None = None) -> list[SearchResult]:
        # Compute similarity with all vectors
        if self.metric == SimilarityMetric.COSINE:
            similarities = cosine_similarity(query.reshape(1, -1), self.vectors)[0]
        elif self.metric == SimilarityMetric.DOT_PRODUCT:
            similarities = self.vectors @ query
        elif self.metric == SimilarityMetric.EUCLIDEAN:
            similarities = -np.linalg.norm(self.vectors - query, axis=1)
        
        # Get top-k indices
        top_indices = np.argsort(similarities)[-k:][::-1]
        
        return [
            SearchResult(
                id=self.ids[i],
                score=float(similarities[i]),
            ) for i in top_indices
        ]
```

**Complexity:**
- Add: O(1) amortized (appending to array)
- Search: O(n*d) — compute similarity with all n vectors of dimension d
- Memory: O(n*d) — store all vectors as float32

---

### 3. HNSW Index (From Scratch)

**File:** `agentcore/index/hnsw.py`

**Purpose:** Implement the HNSW (Hierarchical Navigable Small World) algorithm from scratch. HNSW is the de facto standard for billion-scale vector search, and implementing it yourself demonstrates deep understanding of modern vector search algorithms.

**Algorithm Overview:**

HNSW builds a multi-layer graph:
- **Layer 0:** Contains all vectors, each connected to its nearest neighbors
- **Layer 1:** A random subset of vectors (~1/M), connected to their nearest neighbors
- **Layer L:** ~2 vectors, fully connected

Search starts at the top layer and descends: at each layer, greedy search finds the nearest vector, then uses that as entry point for the next layer. At layer 0, it performs beam search (ef_search) for the final result.

```
HNSW Structure:
    
    Layer 2:    ● ─── ●            (2 vectors)
                  │
    Layer 1:    ● ─── ● ─── ● ─── ●    (~n/M vectors)
                │     │     │     │
    Layer 0:    ● ─── ● ─── ● ─── ● ─── ● ─── ●    (all n vectors)
```

**Implementation Structure:**

```python
class HNSWIndex(VectorIndex):
    def __init__(
        self,
        dimension: int,
        metric: SimilarityMetric = SimilarityMetric.COSINE,
        M: int = 16,          # Number of connections per node per layer
        M_max: int = 32,      # Max connections per node (for layer 0)
        ef_construction: int = 200,  # Beam size during construction
        ef_search: int = 50,   # Beam size during search
        ml: float = 1.0 / math.log(M),  # Level normalization
        random_seed: int = 42,
    ):
        ...
    
    # Graph representation:
    # layers[layer][node_id] = list of neighbor_ids
    # level_distribution: random level for each node based on ml
```

**Key Components to Implement:**

- **Distance function:** vectorized cosine/dot/L2 using NumPy
- **Layer assignment:** for each new vector, assign a random level `l = floor(-ln(uniform(0,1)) * ml)`
- **Insert:** enter at top layer, greedy-search to nearest, then descend to level `l`, adding connections at each layer
- **Search:** start at top layer, greedy descent to layer 0, then beam search with `ef_search`
- **Select neighbors:** heuristics: M nearest neighbors, or heuristic to maintain connectivity (skip neighbors that are closer to each other than to query)

**Complexity:**
- Add: O(log n * M * d) — search + connect to M neighbors at each of log n layers
- Search: O(log n * ef_search * d) — beam search through log n layers
- Memory: O(n * M * d) — graph edges dominate

**Optimization (if needed):**
- If the from-scratch HNSW is too slow for your dataset size, provide an `HNSWLibIndex` that wraps the `hnswlib` C++ library via its Python bindings. The API is identical; only the backend differs.

---

### 4. IVF Index (Inverted File)

**File:** `agentcore/index/ivf.py`

**Purpose:** Implement the IVF (Inverted File) index, which partitions the vector space into Voronoi cells using k-means clustering. At search time, only the closest N_probe cells are searched.

```python
class IVFIndex(VectorIndex):
    def __init__(
        self,
        dimension: int,
        nlist: int = 100,        # Number of clusters/cells
        nprobe: int = 10,        # Number of cells to search
        metric: SimilarityMetric = SimilarityMetric.COSINE,
        quantizer: str = "flat",  # "flat" or "pq" (product quantization)
    ):
        ...
```

**Implementation:**

1. **Training:** run k-means on a sample of vectors to find `nlist` centroids
2. **Adding:** assign each vector to its nearest centroid, store in the corresponding inverted list
3. **Search:** compute distances from query to all centroids, search the top `nprobe` closest lists

**IVF with Product Quantization (IVF-PQ):**
- Compress vectors using product quantization (split vector into M sub-vectors, quantize each with 256 centroids = 1 byte each)
- Search uses asymmetric distance computation (ADC): pre-compute distances from query sub-vectors to PQ centroids, then approximate distance is sum of sub-vector distances
- Config: `M=8` (split into 8 sub-vectors, ~4x compression for 768-dim vectors)

**Complexity:**
- Training: O(nlist * n * d * iterations) — k-means
- Add: O(nlist * d) — find nearest centroid
- Search: O(nlist * d + nprobe * (n/nlist) * d) — compare to centroids + search clusters
- Memory: O(n * d) for IVF-Flat, O(n * d/M * 256) for IVF-PQ

---

### 5. Backend Adapters

**File:** `agentcore/index/adapters/`

**Purpose:** Provide a uniform interface over external vector stores, allowing the same application code to use LanceDB, Chroma, pgvector, or Pinecone by changing a config value.

```python
class LanceDBIndex(VectorIndex):
    def __init__(self, uri: str = "./.lancedb", table_name: str = "vectors"):
        import lancedb
        self.db = lancedb.connect(uri)
        self.table = self.db.create_table(table_name, schema, exist_ok=True)
        ...
    
    def search(self, query, k=10, filters=None):
        return self.table.search(query).limit(k).to_list()

class PGVectorIndex(VectorIndex):
    def __init__(self, connection_string: str, table_name: str = "vectors"):
        # Create pgvector extension, create table with vector column
        ...

class PineconeIndex(VectorIndex):
    def __init__(self, api_key: str, index_name: str, dimension: int):
        ...
```

---

### 6. Quantization

**File:** `agentcore/index/quantization.py`

**Purpose:** Compress vectors to reduce memory usage and speed up search at the cost of some accuracy.

**Quantization Types:**

| Type | Ratio | Accuracy | Speed |
|------|-------|----------|-------|
| None (float32) | 1x | Exact | Baseline |
| Scalar (int8) | 4x | ~99% | 2-3x faster |
| Scalar (int4) | 8x | ~97% | 3-4x faster |
| PQ (8 subvectors) | 4x | ~95% | 2x faster |
| PQ (16 subvectors) | 8x | ~90% | 3x faster |
| Binary | 32x | ~85% | 10x+ faster |

**Scalar Quantization:**
```python
class ScalarQuantizer:
    """Quantize float32 vectors to int8/int4 using min-max or percentile scaling."""
    
    def train(self, vectors: np.ndarray) -> None:
        self.lower = np.min(vectors, axis=0)
        self.upper = np.max(vectors, axis=0)
        # Or use percentile: lower = percentile(vectors, 1), upper = percentile(vectors, 99)
    
    def quantize(self, vectors: np.ndarray) -> np.ndarray:
        # Scale to [0, 255] and round to int8
        scaled = (vectors - self.lower) / (self.upper - self.lower) * 255
        return np.clip(scaled, 0, 255).astype(np.uint8)
    
    def dequantize(self, quantized: np.ndarray) -> np.ndarray:
        return quantized.astype(np.float32) / 255 * (self.upper - self.lower) + self.lower
```

**Product Quantization:**
```python
class ProductQuantizer:
    """Split vectors into M sub-vectors, quantize each sub-vector separately."""
    
    def __init__(self, M: int = 8, nbits: int = 8):
        self.M = M            # number of sub-vectors
        self.nbits = nbits    # bits per sub-vector (8 = 256 centroids)
        self.codebooks: list[np.ndarray] = []  # [M x 256 x dim_sub]
    
    def train(self, vectors: np.ndarray) -> None:
        dim_sub = vectors.shape[1] // self.M
        for m in range(self.M):
            sub_vectors = vectors[:, m * dim_sub : (m + 1) * dim_sub]
            # Run k-means to find 2^nbits centroids
            centroids = kmeans(sub_vectors, n_clusters=2**self.nbits)
            self.codebooks.append(centroids)
    
    def encode(self, vectors: np.ndarray) -> np.ndarray:
        """Encode vectors to compact codes: n x M int8 array."""
        codes = np.zeros((vectors.shape[0], self.M), dtype=np.uint8)
        for m in range(self.M):
            # Assign each sub-vector to nearest centroid
            ...
        return codes
```

---

### 7. Index Management

**File:** `agentcore/index/management.py`

**Purpose:** Manage multiple indexes: create, delete, merge, backup, and monitor.

```python
class IndexManager:
    def create(self, name: str, index_type: str, dimension: int, **kwargs) -> VectorIndex: ...
    def get(self, name: str) -> VectorIndex: ...
    def delete(self, name: str) -> None: ...
    def list(self) -> list[IndexInfo]: ...
    def merge(self, indices: list[str], new_name: str) -> VectorIndex: ...
    def stats(self, name: str) -> IndexStats: ...

@dataclass
class IndexStats:
    count: int
    dimension: int
    memory_bytes: int
    avg_recall: float  # Against exact search (FlatIndex)
    latency_p50_ms: float
    latency_p99_ms: float
```

---

### 8. Performance Benchmarks

```bash
agentcore index benchmark --index_types flat,hnsw,ivf --dimensions 384,768,1536 --sizes 1000,10000,100000
```

Benchmark metrics:
- **Recall@K**: fraction of true nearest neighbors (from FlatIndex) in top-K results
- **QPS**: queries per second
- **Memory**: RAM usage in MB
- **Index time**: time to build the index
- **Tradeoff curve**: recall vs QPS for different parameters

Expected results (approximate):

| Index | 10K vectors (768d) | 100K vectors (768d) |
|-------|--------------------|--------------------|
| Flat | 100% recall, 500 QPS | 100% recall, 50 QPS |
| HNSW (M=16, ef=50) | 99% recall, 5000 QPS | 99% recall, 2000 QPS |
| IVF (nlist=100, nprobe=10) | 97% recall, 3000 QPS | 95% recall, 1500 QPS |

## Testing Strategy

| Test | Description |
|------|-------------|
| `test_flat_exact` | FlatIndex returns exact results (verify with brute force) |
| `test_hnsw_recall` | HNSW recall >= 95% against FlatIndex for various datasets |
| `test_ivf_recall` | IVF recall >= 90% against FlatIndex |
| `test_quantization_error` | Quantization error within expected bounds |
| `test_backend_consistency` | All backend adapters return same results for same data |
| `test_persistence` | Save → load → verify same search results |
| `test_batch_operations` | Batch add, delete, search correctness |

## Blog Content Angles

- "Building a Vector Index Abstraction Layer: Why and How"
- "HNSW from Scratch: Implementation and Optimization Guide"
- "IVF and Product Quantization: Memory-Efficient Vector Search"
- "Quantization for Vector Search: Accuracy vs Speed Tradeoffs"
- "Benchmarking Vector Indexes: Recall, QPS, and Memory"
- "The Adapter Pattern for Vector Databases: One API, Many Backends"

## File Structure

```
packages/python/index/
├── __init__.py
├── base.py                  # VectorIndex ABC, SearchResult, SimilarityMetric
├── flat.py                  # FlatIndex
├── hnsw.py                  # HNSWIndex (from scratch)
├── hnsw_optimized.py        # HNSWLib wrapper (C++ backend, optional)
├── ivf.py                   # IVFIndex
├── quantization.py          # ScalarQuantizer, ProductQuantizer
├── management.py            # IndexManager, IndexStats
├── benchmark.py             # Benchmark runner
├── adapters/
│   ├── __init__.py
│   ├── lancedb.py           # LanceDBIndex
│   ├── chroma.py            # ChromaIndex
│   ├── pgvector.py          # PGVectorIndex
│   └── pinecone.py          # PineconeIndex
└── tests/
    ├── test_flat.py
    ├── test_hnsw.py
    ├── test_ivf.py
    ├── test_quantization.py
    ├── test_adapters.py
    └── benchmark_test.py
```
