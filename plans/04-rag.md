# Part 4: `agentcore-rag` — Retrieval-Augmented Generation

## Purpose

RAG is the backbone of knowledge-grounded AI agents. It allows agents to access and reason over large corpora of documents — fetching the most relevant information at inference time rather than relying solely on parametric knowledge.

This package builds a complete RAG pipeline from scratch: document ingestion, chunking, embedding, hybrid search, reranking, citation tracking, and multi-pass generation. No LangChain, no LlamaIndex — every component is custom.

## Architecture

```
Documents (PDF, HTML, MD, etc.)
    │
    ▼
┌─────────────────────────────┐
│      Ingestion Pipeline     │
│  Load → Validate → Transform│
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│        Chunking Layer       │
│  Fixed / Recursive /        │
│  Semantic / Hierarchical    │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│       Embedding Layer       │
│  TextEmbedder / CodeEmbedder│
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐      ┌──────────────────┐
│      Index Storage         │──────│   Vector Store   │
│  (Document + Chunk + Meta)  │      │  (LanceDB/Chroma)│
└─────────────────────────────┘      └──────────────────┘
                                          ▲
                                          │
┌─────────────────────────────┐           │
│       Retrieval Layer      │───────────┘
│  Vector / BM25 / Hybrid    │
│  Reranking / Fusion        │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│      Generation Layer       │
│  Context Assembly → Outline │
│  → Draft → Critique → Final │
│  + Citations                │
└─────────────────────────────┘
```

## Component Breakdown

### 1. `Document` and `DocumentLoader`

**File:** `agentcore/rag/documents.py`

**Purpose:** Define the fundamental `Document` unit and provide loaders for various formats.

```python
@dataclass
class Document:
    content: str                # Text content (or markdown for structured docs)
    metadata: dict              # {source, title, author, date, url, ...}
    doc_id: str                 # Unique identifier (hash of content + source)
    modality: str = "text"      # text, code, table, image_description
    embedding: list[float] | None = None  # Pre-computed embedding

@dataclass
class Chunk:
    content: str                # Chunk text content
    chunk_id: str               # Unique within document
    doc_id: str                 # Parent document
    metadata: dict              # Inherited from document + chunk-specific (position, heading)
    embedding: list[float] | None = None
    parent_chunk_id: str | None = None  # For hierarchical chunking
```

**Loader Interface:**

```python
class DocumentLoader(ABC):
    @abstractmethod
    async def load(self, source: str | Path) -> list[Document]: ...
    
    @abstractmethod
    async def load_stream(self, source: str | Path) -> AsyncGenerator[Document, None]: ...
```

**Implementations:**

| Loader | Format | Backend |
|--------|--------|---------|
| `TextLoader` | .txt, .md, .rst | Direct file read |
| `PDFLoader` | .pdf | pypdfium2 (fast, layout-aware) |
| `HTMLLoader` | .html, .htm | trafilatura (content extraction) |
| `WebLoader` | URL | httpx + trafilatura |
| `CSVLoader` | .csv | csv module |
| `JSONLoader` | .json, .jsonl | json module |
| `CodeLoader` | .py, .js, .ts, .java, etc. | Path detection + AST parsing |
| `EPubLoader` | .epub | ebooklib |

---

### 2. Chunking Strategies

**File:** `agentcore/rag/chunking.py`

**Purpose:** Split documents into coherent chunks suitable for embedding and retrieval. The chunking strategy significantly impacts retrieval quality.

```python
class Chunker(ABC):
    @abstractmethod
    def chunk(self, document: Document) -> list[Chunk]: ...
    
    @abstractmethod
    def chunk_batch(self, documents: list[Document]) -> list[list[Chunk]]: ...
```

**Strategies:**

**`FixedSizeChunker`:**
- Splits text into chunks of `chunk_size` characters/tokens with `overlap` characters/tokens
- Pros: simple, predictable chunk counts
- Cons: may split in the middle of a sentence or concept
- Config: `size=512, overlap=64, unit="tokens"`

**`RecursiveCharacterChunker`:**
- Recursively splits on separators: `["\n\n", "\n", ".", " ", ""]`
- First tries to split on paragraph boundaries, then sentences, then words
- Each chunk is at most `chunk_size` tokens
- Config: `max_size=512, separators=["\n\n", "\n", ". ", " ", ""]`
- This is the default recommendation for most text

**`SemanticChunker`:**
- Splits at points where the semantic embedding similarity between adjacent sentences drops below a threshold
- Step 1: segment text into sentences
- Step 2: embed each sentence
- Step 3: compute cosine similarity between adjacent sentences
- Step 4: split where similarity drops below threshold
- Config: `threshold=0.7, min_chunk_size=50, max_chunk_size=1000`
- Pros: chunks align with topic boundaries
- Cons: expensive (requires embedding all sentences)

**`CodeChunker`:**
- Splits code files at function/class/module boundaries
- Uses AST parsing to identify structural units
- Each chunk: a function, class, or module-level code block
- Config: `include_docstrings=True, include_signature=True`
- Pros: chunks are semantically meaningful code units

**`HierarchicalChunker`:**
- Creates a two-level hierarchy: parent chunks (sections) → child chunks (paragraphs)
- Retrieval returns child chunks, but you can also retrieve the parent for context
- Config: `parent_size=2000, child_size=512, overlap=64`

**Comparison of Strategies:**

| Strategy | Use Case | Pros | Cons |
|----------|----------|------|------|
| Fixed | Baselines, simple documents | Fast, predictable | May split concepts |
| Recursive | General text, documentation | Balances chunk quality and speed | Still heuristic |
| Semantic | Long-form articles, research papers | Topic-aligned chunks | Computationally expensive |
| Code | Code repositories | Preserves code structure | Only for code |
| Hierarchical | Any (with parent context retrieval) | Best context richness | Double the chunk count |

---

### 3. Retrieval Layer

**File:** `agentcore/rag/retrieval.py`

**Purpose:** Given a query, retrieve the most relevant chunks from the index. Supports multiple retrieval strategies and combination methods.

**Retriever Interface:**

```python
class Retriever(ABC):
    @abstractmethod
    async def retrieve(
        self,
        query: str,
        k: int = 10,
        filters: dict | None = None,
    ) -> list[ScoredChunk]:
        ...
```

**`ScoredChunk`:**
```python
@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float
    retrieval_method: str  # "vector", "bm25", "hybrid", "reranked"
```

**Retriever Implementations:**

**`VectorRetriever`:**
- Embeds the query, performs nearest neighbor search in vector index
- Config: `model="BAAI/bge-small-en-v1.5", metric="cosine", ef_search=40`

**`BM25Retriever`:**
- Custom BM25 implementation from scratch
- Tokenization: whitespace + porter stemmer (for English)
- IDF variant: BM25+ (with relevance saturation to handle long documents)
- Config: `k1=1.5, b=0.75, delta=0.5` (for BM25+)
- No external dependencies — pure Python implementation

**`HybridRetriever`:**
- Runs vector + BM25 in parallel, combines results
- Fusion strategies:
  - `WeightedFusion`: `final_score = alpha * vector_score + (1-alpha) * bm25_score` (alpha ~0.5-0.7)
  - `RRF`: reciprocal rank fusion — `score = 1/(k + rank_vector) + 1/(k + rank_bm25)` — robust to score distributions
  - `ScoreNormalizedFusion`: normalize both score distributions to [0,1], then weighted sum
- Config: `alpha=0.6, fusion_method="rrf"`

**`EnsembleRetriever`:**
- Runs N retrievers in parallel, combines via RRF or weighted voting
- Useful when you have multiple embedding models or retrieval strategies

---

### 4. Reranking

**File:** `agentcore/rag/reranking.py`

**Purpose:** Improve retrieval precision by reranking the top-K candidates with a more expensive but more accurate model.

```python
class Reranker(ABC):
    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        k: int = 5,
    ) -> list[ScoredChunk]:
        ...
```

**Implementations:**

**`CrossEncoderReranker`:**
- Uses a cross-encoder model (e.g., `BAAI/bge-reranker-v2-m3`) to score query-chunk pairs
- Cross-encoders jointly encode query + chunk, producing a relevance score
- More accurate than bi-encoders but slower (O(n) forward passes for n candidates)
- Config: `model="BAAI/bge-reranker-v2-m3", batch_size=16, device="cuda"`
- Optimization: batch inference for all candidates in one forward pass

**`LLMReranker`:**
- Use the local LLM to rate relevance on a scale of 1-5
- Prompt: "On a scale of 1-5, how relevant is this document to the query: {query}?\nDocument: {chunk}\nRelevance score:"
- Pros: no dedicated model needed, can reason about relevance
- Cons: slow, expensive (each candidate = one inference)

**`MMRReranker` (Maximal Marginal Relevance):**
- Reranks to balance relevance and diversity
- `MMR = lambda * sim(q, d_i) - (1-lambda) * max(sim(d_i, d_j))` for all selected d_j
- Config: `lambda_param=0.7` (higher → more relevance-focused, lower → more diverse)
- Prevents redundant chunks from dominating the result set

**`RecencyReranker`:**
- Boosts more recent documents based on `date` metadata
- Config: `decay_rate=0.1` (per day), `boost_window_days=30`

---

### 5. Generation Layer

**File:** `agentcore/rag/generation.py`

**Purpose:** Synthesize retrieved context into a coherent, well-cited answer.

**`ContextAssembler`:**
```python
class ContextAssembler:
    def assemble(
        self,
        query: str,
        chunks: list[ScoredChunk],
        max_tokens: int = 4096,
    ) -> str:
        """Pack chunks into a context string within token budget.
        
        Order: highest relevance first.
        Format: 
            Source [1]: {content}
            Source [2]: {content}
        """
        ...
```

**`CitationTracker`:**
```python
class CitationTracker:
    def __init__(self):
        self.sources: dict[int, ScoredChunk] = {}
    
    def add_source(self, idx: int, chunk: ScoredChunk): ...
    
    def cite(self, indices: list[int]) -> str:
        """Generate citation string: [1][2]"""
    
    def format_bibliography(self) -> str:
        """Generate bibliography from tracked sources"""
    
    def verify_claim(self, claim: str, source_idx: int) -> bool:
        """Use LLM to check if claim is supported by source"""
```

**Multi-Pass Generation Pipeline:**

```
1. OutlinePhase
   Input: query + context
   Output: structured outline (sections, key points per section)
   
2. DraftPhase (per section)
   Input: outline section + relevant context
   Output: section draft with inline citations
   
3. CritiquePhase
   Input: full draft + query + context
   Output: critique (missing info, inaccuracies, improvements)
   
4. RevisePhase
   Input: draft + critique + context
   Output: revised section
   
5. FinalizePhase
   Input: all sections
   Output: unified final document with table of contents + bibliography
```

**Config:**
```python
@dataclass
class GenerationConfig:
    model: ModelClient
    max_tokens_per_output: int = 4096
    temperature: float = 0.0
    passes: list[Pass] = field(default_factory=lambda: [
        "outline", "draft", "critique", "revise", "finalize"
    ])
    citation_required: bool = True
    verify_citations: bool = True
```

---

### 6. Ingestion Pipeline

**File:** `agentcore/rag/pipeline.py`

**Purpose:** Orchestrate the end-to-end flow: load → transform → chunk → embed → store.

```python
class IngestionPipeline:
    def __init__(
        self,
        loaders: dict[str, DocumentLoader],      # Extension → loader
        chunker: Chunker,
        embedder: Embedder,
        store: DocumentStore,
    ):
        ...
    
    async def ingest_file(self, path: str) -> IngestResult: ...
    async def ingest_directory(self, path: str, recursive: bool = True) -> list[IngestResult]: ...
    async def ingest_url(self, url: str) -> IngestResult: ...
    
    async def ingest_stream(
        self, source: str | Path
    ) -> AsyncGenerator[IngestProgress, None]:
        """Stream ingest with progress updates"""
        ...
```

**`IngestResult`:**
```python
@dataclass
class IngestResult:
    source: str
    documents: int = 0
    chunks: int = 0
    duration_ms: float = 0.0
    error: str | None = None
```

---

## The Complete RAG Pipeline

```python
# 1. Load document
doc = await TextLoader().load("report.md")

# 2. Chunk
chunks = RecursiveCharacterChunker(max_size=512).chunk(doc)

# 3. Embed (done in batch)
embeddings = embedder.embed_batch([c.content for c in chunks])

# 4. Store
store.add([ChunkWithEmbedding(c, e) for c, e in zip(chunks, embeddings)])

# 5. Retrieve
retriever = HybridRetriever(
    vector_retriever=VectorRetriever(store, embedder),
    bm25_retriever=BM25Retriever(store),
    fusion="rrf",
)
results = await retriever.retrieve("How does the authentication work?", k=10)

# 6. Rerank
reranker = CrossEncoderReranker(model="BAAI/bge-reranker-v2-m3")
reranked = await reranker.rerank("How does the authentication work?", results, k=5)

# 7. Generate
generator = RAGGenerator(
    model=ollama_client,
    citation_tracker=CitationTracker(),
)
answer = await generator.generate(
    query="How does the authentication work?",
    chunks=reranked,
)
# Returns: "The system uses JWT-based authentication [1][2]. Tokens expire after 24 hours [3]."
```

## Testing Strategy

| Test | Description |
|------|-------------|
| `test_chunking_strategies` | Verify chunk counts, sizes, overlap correctness |
| `test_bm25_from_scratch` | Known corpus → expected IDF scores + retrieval results |
| `test_hybrid_fusion` | Mock vector + BM25 scores → correct combined ranking |
| `test_reranking_improvement` | Reranker lifts relevant results above less relevant ones |
| `test_citation_tracking` | Every claim in output maps to a source chunk |
| `test_pipeline_end_to_end` | Ingest → retrieve → generate produces coherent answer |
| `test_token_budget_enforcement` | Context assembly never exceeds token budget |

## Benchmarking

```bash
agentcore eval --suite rag --metrics relevance,latency,token_efficiency
```

Benchmark datasets:
- **Simple QA**: 50 single-fact questions from ingested docs (exact match in single chunk)
- **Multi-hop**: 30 questions requiring combining info from 2+ chunks
- **Comparative**: 20 questions comparing information across documents
- **Open-ended**: 20 complex questions requiring synthesis + reasoning

## Blog Content Angles

- "Hybrid Search from Scratch: BM25 + Dense Vector Retrieval"
- "Chunking Strategies: A Systematic Comparison (And Why It Matters)"
- "RAG Evaluation: Beyond Simple Recall@K"
- "Building a Cross-Encoder Reranker Pipeline"
- "Multi-Pass Generation: Outline → Draft → Critique → Revise → Final"
- "Citation Tracking in RAG Systems: From Sources to Claims"
- "The Ingestion Pipeline: From Raw Documents to Searchable Chunks"

## File Structure

```
packages/python/rag/
├── __init__.py
├── documents.py              # Document, Chunk dataclasses
├── loaders/
│   ├── __init__.py
│   ├── base.py               # DocumentLoader ABC
│   ├── text.py               # TextLoader
│   ├── pdf.py                # PDFLoader
│   ├── html.py               # HTMLLoader, WebLoader
│   ├── csv_json.py           # CSVLoader, JSONLoader
│   ├── code.py               # CodeLoader
│   └── epub.py               # EPubLoader
├── chunking.py               # Chunker ABC + all strategies
├── chunking_strategies/
│   ├── __init__.py
│   ├── fixed.py              # FixedSizeChunker
│   ├── recursive.py          # RecursiveCharacterChunker
│   ├── semantic.py           # SemanticChunker
│   ├── code.py               # CodeChunker
│   └── hierarchical.py       # HierarchicalChunker
├── retrieval.py              # Retriever ABC + implementations
├── bm25.py                   # Custom BM25+ implementation
├── reranking.py              # Reranker ABC + implementations
├── generation.py             # RAGGenerator, ContextAssembler, CitationTracker
├── pipeline.py               # IngestionPipeline
├── types.py                  # ScoredChunk, IngestResult, etc.
└── evaluation.py             # RAG-specific evaluation metrics
```
