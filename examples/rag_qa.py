"""Question answering over local documents with hybrid search and citations.

Pipeline: markdown-aware chunking -> BM25 + vector index (HNSW) -> reciprocal rank fusion
-> lexical rerank -> answer with [n] citations -> citation verification.

    python examples/rag_qa.py --model mock "How does reciprocal rank fusion work?"
    python examples/rag_qa.py --model ollama:qwen2.5:7b --docs examples/data "What is ef_search?"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agentcore import create_model
from agentcore.index import HNSWIndex
from agentcore.rag import HashingEmbedder, MarkdownChunker, RAGPipeline

HERE = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "question", nargs="?", default="How does reciprocal rank fusion combine BM25 and vectors?"
    )
    parser.add_argument("--docs", default=str(HERE / "data"), help="file or directory to index")
    parser.add_argument("--model", default="auto")
    parser.add_argument("-k", type=int, default=3, help="passages to use")
    args = parser.parse_args()

    embedder = HashingEmbedder(dimension=256)
    rag = RAGPipeline(
        embedder=embedder,
        index=HNSWIndex(embedder.dimension, M=12, ef_construction=100),
        chunker=MarkdownChunker(chunk_size=600, overlap=80),
        model=create_model(args.model, verbose=True),
        k=args.k,
    )
    n = rag.ingest(args.docs)
    print(f"Indexed {n} chunks from {args.docs}\n")

    print(f"Q: {args.question}\n")
    print("Retrieved:")
    for i, hit in enumerate(rag.retrieve(args.question), start=1):
        heading = hit.chunk.metadata.get("heading", "")
        print(f"  [{i}] score={hit.score:.3f} {Path(hit.chunk.source).name} :: {heading}")

    answer = rag.answer_sync(args.question)
    print(f"\nA: {answer.text}\n")
    for c in answer.citations:
        flag = "supported" if c.supported else "UNSUPPORTED"
        print(f"  [{c.number}] {c.title} ({Path(c.source).name}) - {flag}")
    if answer.invalid_citations:
        print(f"  invalid citation numbers: {answer.invalid_citations}")


if __name__ == "__main__":
    main()
