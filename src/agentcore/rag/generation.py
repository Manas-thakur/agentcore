"""Context assembly, citation tracking and the end-to-end ``RAGPipeline``."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentcore.embeddings import Embedder, HashingEmbedder
from agentcore.index.base import VectorIndex, load_index
from agentcore.index.flat import FlatIndex
from agentcore.rag.bm25 import BM25, tokenize
from agentcore.rag.chunking import Chunker, RecursiveChunker
from agentcore.rag.documents import Chunk, Document, load_path
from agentcore.rag.rerank import LexicalReranker, Reranker
from agentcore.rag.retrieval import (
    BM25Retriever,
    ChunkStore,
    HybridRetriever,
    ScoredChunk,
    VectorRetriever,
)
from agentcore.runtime.context import TokenCounter
from agentcore.runtime.model_client import ModelClient
from agentcore.types import Message

RAG_SYSTEM_PROMPT = (
    "You answer questions using ONLY the numbered sources provided. Cite every claim with "
    "the source number in square brackets, e.g. [1] or [2][3]. If the sources do not contain "
    "the answer, say you don't know. Be concise."
)


class ContextAssembler:
    """Format retrieved chunks as numbered sources within a token budget."""

    def __init__(self, max_tokens: int = 3000, counter: TokenCounter | None = None):
        self.max_tokens = max_tokens
        self.counter = counter or TokenCounter()

    def assemble(self, chunks: list[ScoredChunk]) -> tuple[str, list[ScoredChunk]]:
        parts, used, total = [], [], 0
        for sc in chunks:
            n = len(used) + 1
            title = sc.chunk.metadata.get("title", "")
            heading = sc.chunk.metadata.get("heading", "")
            header = f"[{n}] {title}" + (f" - {heading}" if heading and heading != title else "")
            block = f"{header}\n{sc.content}"
            cost = self.counter.count(block)
            if used and total + cost > self.max_tokens:
                break
            parts.append(block)
            used.append(sc)
            total += cost
        return "\n\n".join(parts), used


@dataclass
class Citation:
    number: int
    chunk_id: str
    source: str
    title: str
    supported: bool = True

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class CitationTracker:
    """Map ``[n]`` markers in generated text back to source chunks and sanity-check them."""

    _MARK = re.compile(r"\[(\d+)\]")

    def __init__(self, sources: list[ScoredChunk]):
        self.sources = sources

    def cited_numbers(self, text: str) -> list[int]:
        seen: list[int] = []
        for m in self._MARK.finditer(text):
            n = int(m.group(1))
            if n not in seen:
                seen.append(n)
        return seen

    def invalid_numbers(self, text: str) -> list[int]:
        return [n for n in self.cited_numbers(text) if not 1 <= n <= len(self.sources)]

    def verify_claim(self, claim: str, number: int, threshold: float = 0.3) -> bool:
        """Lexical support check: enough of the claim's content words appear in the source."""
        if not 1 <= number <= len(self.sources):
            return False
        claim_terms = set(tokenize(self._MARK.sub("", claim)))
        if not claim_terms:
            return True
        source_terms = set(tokenize(self.sources[number - 1].content))
        return len(claim_terms & source_terms) / len(claim_terms) >= threshold

    def citations(self, text: str) -> list[Citation]:
        out = []
        # "Claim. [1] Next" -> "Claim [1]. Next" so markers stay with the sentence they follow
        normalized = re.sub(r"([.!?])\s*((?:\[\d+\])+)", r" \2\1", text)
        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        for n in self.cited_numbers(text):
            if not 1 <= n <= len(self.sources):
                continue
            sc = self.sources[n - 1]
            claims = [s for s in sentences if f"[{n}]" in s]
            supported = all(self.verify_claim(c, n) for c in claims) if claims else True
            out.append(
                Citation(
                    n, sc.id, sc.chunk.source, str(sc.chunk.metadata.get("title", "")), supported
                )
            )
        return out

    def bibliography(self, text: str | None = None) -> str:
        numbers = self.cited_numbers(text) if text is not None else range(1, len(self.sources) + 1)
        lines = []
        for n in numbers:
            if 1 <= n <= len(self.sources):
                c = self.sources[n - 1].chunk
                lines.append(f"[{n}] {c.metadata.get('title', '')} ({c.source})")
        return "\n".join(lines)


@dataclass
class RAGAnswer:
    question: str
    text: str
    citations: list[Citation]
    contexts: list[ScoredChunk]
    invalid_citations: list[int] = field(default_factory=list)

    def format(self) -> str:
        refs = "\n".join(f"  [{c.number}] {c.title} ({c.source})" for c in self.citations)
        return f"{self.text}\n\nSources:\n{refs}" if refs else self.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.text,
            "citations": [c.to_dict() for c in self.citations],
            "invalid_citations": self.invalid_citations,
            "contexts": [
                {"id": c.id, "score": c.score, "content": c.content} for c in self.contexts
            ],
        }


class RAGPipeline:
    """Ingest -> chunk -> embed/index (+BM25) -> hybrid retrieve -> rerank -> cite.

    Defaults are fully offline: ``HashingEmbedder`` + ``FlatIndex`` + BM25 + RRF +
    ``LexicalReranker``. Swap any component (e.g. ``HNSWIndex``, ``OllamaEmbedder``).
    """

    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        index: VectorIndex | None = None,
        chunker: Chunker | None = None,
        reranker: Reranker | None = None,
        model: ModelClient | None = None,
        k: int = 4,
        candidate_k: int = 20,
        hybrid_weights: list[float] | None = None,
        max_context_tokens: int = 3000,
    ):
        self.embedder = embedder or HashingEmbedder()
        self.index = index or FlatIndex(self.embedder.dimension or 384)
        self.chunker = chunker or RecursiveChunker(chunk_size=700, overlap=100)
        self.reranker = reranker if reranker is not None else LexicalReranker()
        self.model = model
        self.k = k
        self.store = ChunkStore()
        self.vector = VectorRetriever(self.embedder, self.index, self.store)
        self.bm25 = BM25Retriever(self.store)
        self.retriever = HybridRetriever(
            [self.bm25, self.vector], weights=hybrid_weights, candidate_k=candidate_k
        )
        self.assembler = ContextAssembler(max_context_tokens)

    # ingestion -------------------------------------------------------------------
    def add_documents(self, documents: list[Document]) -> int:
        chunks = self.chunker.chunk_many(documents)
        self.add_chunks(chunks)
        return len(chunks)

    def add_chunks(self, chunks: list[Chunk]) -> None:
        self.store.add(chunks)
        self.vector.add(chunks)
        self.bm25.add(chunks)

    def add_texts(self, texts: list[str], source: str = "inline") -> int:
        return self.add_documents(
            [Document(t, source=f"{source}:{i}") for i, t in enumerate(texts)]
        )

    def ingest(self, path: str | Path) -> int:
        """Load a file or directory and index it. Returns the number of chunks."""
        return self.add_documents(load_path(path))

    # retrieval -------------------------------------------------------------------
    def retrieve(self, query: str, k: int | None = None) -> list[ScoredChunk]:
        k = k or self.k
        candidates = self.retriever.retrieve(query, max(k * 3, k))
        if self.reranker is not None:
            return self.reranker.rerank(query, candidates, k)
        return candidates[:k]

    def build_messages(
        self, question: str, contexts: list[ScoredChunk]
    ) -> tuple[list[Message], list[ScoredChunk]]:
        context, used = self.assembler.assemble(contexts)
        user = f"Sources:\n\n{context}\n\nQuestion: {question}"
        return [Message.system(RAG_SYSTEM_PROMPT), Message.user(user)], used

    async def answer(self, question: str, k: int | None = None) -> RAGAnswer:
        if self.model is None:
            raise ValueError("RAGPipeline.answer() needs a model; pass model=create_model('mock')")
        contexts = self.retrieve(question, k)
        messages, used = self.build_messages(question, contexts)
        resp = await self.model.generate(messages)
        tracker = CitationTracker(used)
        return RAGAnswer(
            question,
            resp.content,
            tracker.citations(resp.content),
            used,
            tracker.invalid_numbers(resp.content),
        )

    def answer_sync(self, question: str, k: int | None = None) -> RAGAnswer:
        return asyncio.run(self.answer(question, k))

    def as_tool(self, name: str = "search_docs", k: int = 4, description: str | None = None) -> Any:
        """Expose retrieval as an agent tool returning numbered snippets with sources."""
        from agentcore.tools.decorator import Tool
        from agentcore.tools.schema import function_to_schema

        def search(query: str) -> str:
            """Search the knowledge base.

            Args:
                query: What to search for.
            """
            hits = self.retrieve(query, k)
            if not hits:
                return "No results."
            return "\n\n".join(
                f"[{i}] {h.chunk.metadata.get('title', '')} ({h.chunk.source})\n{h.content}"
                for i, h in enumerate(hits, start=1)
            )

        _, params = function_to_schema(search)
        return Tool(
            name=name,
            description=description
            or "Search the local knowledge base and return relevant passages with sources.",
            parameters=params,
            fn=search,
            category="retrieval",
        )

    # persistence ---------------------------------------------------------------------
    def save(self, directory: str | Path) -> None:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        self.index.save(d / "index.npz")
        (d / "chunks.json").write_text(
            json.dumps([c.to_dict() for c in self.store.chunks.values()]), encoding="utf-8"
        )
        (d / "bm25.json").write_text(json.dumps(self.bm25.bm25.to_dict()), encoding="utf-8")

    @classmethod
    def load(cls, directory: str | Path, **kwargs: Any) -> RAGPipeline:
        d = Path(directory)
        pipe = cls(index=load_index(d / "index.npz"), **kwargs)
        chunks = [
            Chunk.from_dict(c) for c in json.loads((d / "chunks.json").read_text(encoding="utf-8"))
        ]
        pipe.store.add(chunks)
        pipe.bm25.bm25 = BM25.from_dict(json.loads((d / "bm25.json").read_text(encoding="utf-8")))
        return pipe
