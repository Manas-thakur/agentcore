---
title: RAG
description: Document loading, chunking, BM25 + dense hybrid retrieval with reciprocal rank fusion, reranking and verified citations.
---

`agentcore.rag` is a complete retrieval-augmented generation pipeline: loaders, chunkers,
embedders, BM25, hybrid retrieval, rerankers, context assembly and answers with citations that are
checked against the retrieved text.

## Pipeline

```python
from agentcore import create_model
from agentcore.index import HNSWIndex
from agentcore.rag import HashingEmbedder, MarkdownChunker, RAGPipeline

emb = HashingEmbedder(256)  # offline; or OllamaEmbedder("nomic-embed-text"), OpenAIEmbedder()
rag = RAGPipeline(
    embedder=emb,
    index=HNSWIndex(256),
    chunker=MarkdownChunker(600),
    model=create_model("mock"),
    k=3,
)
rag.ingest("examples/data")
answer = rag.answer_sync("What does ef_search control?")
print(answer.format())  # answer text with [n] citations + verified sources
search_tool = rag.as_tool("search_docs")  # give retrieval to an agent
```

```text
A larger ef_search increases recall at the cost of latency. [1] Typical values are M=16, ef_construction=200 and ef_search=64. [1]

Sources:
  [1] HNSW Vector Index (examples/data/hnsw.md)
```

`RAGPipeline(*, embedder, index, chunker, reranker, model, k=4, candidate_k=20, hybrid_weights,
max_context_tokens=3000)`. Every argument has an offline default, so `RAGPipeline()` works with no
configuration (hashing embeddings, a flat index, a recursive chunker, a lexical reranker).

## Building blocks

| Stage | Classes |
|---|---|
| Loading | `load_file`, `load_directory`, `load_path` (txt, md, html, jsonl, directories) |
| Chunking | `FixedSizeChunker`, `RecursiveChunker`, `SentenceChunker`, `MarkdownChunker` (heading-aware), `create_chunker` |
| Embedding | `HashingEmbedder` (offline), `OllamaEmbedder`, `OpenAIEmbedder`, `create_embedder` (`AGENTCORE_EMBEDDER`) |
| Retrieval | `BM25`, `BM25Retriever`, `VectorRetriever`, `HybridRetriever` with `reciprocal_rank_fusion` |
| Reranking | `LexicalReranker`, `MMRReranker` (diversity), `CallableReranker` (plug in a cross-encoder) |
| Generation | `ContextAssembler` (token budget), `CitationTracker` (numbering + verification), `RAGAnswer` |

## How hybrid search works

The query goes to BM25 (exact terms, rare words, identifiers) and to the vector index (meaning,
paraphrases) in parallel; each returns `candidate_k` chunks. Reciprocal rank fusion merges the two
rankings by `1 / (k + rank)`, so a chunk ranked well by either retriever rises without needing the
scores to be comparable. A reranker then picks the final `k`, the context assembler fits them into
`max_context_tokens`, and the model answers with `[n]` markers. The citation tracker maps each
marker to its source and reports markers that point at no retrieved chunk in
`answer.invalid_citations`; `CitationTracker.verify_claim()` checks that a cited sentence actually
overlaps the chunk it cites.

## Retrieval for agents

`rag.as_tool("search_docs")` returns a `@tool` that an `Agent` (or the `ResearcherAgent`) can call.
`agentcore research "topic" --docs DIR` runs the showcase researcher over a local corpus and writes
a cited report plus trace and cost files.
