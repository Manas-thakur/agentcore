from __future__ import annotations

import json

from agentcore.index import HNSWIndex
from agentcore.rag import (
    BM25,
    CitationTracker,
    Document,
    FixedSizeChunker,
    HashingEmbedder,
    LexicalReranker,
    MarkdownChunker,
    MMRReranker,
    RAGPipeline,
    RecursiveChunker,
    SentenceChunker,
    load_directory,
    reciprocal_rank_fusion,
    tokenize,
)
from agentcore.rag.retrieval import ScoredChunk
from agentcore.runtime import MockModel, ScriptedModel
from tests.conftest import EXAMPLES, run

TEXT = (
    "Paragraph one talks about agents. Agents use tools to act.\n\n"
    "Paragraph two is about vector search. HNSW builds a layered graph. IVF uses k-means.\n\n"
    "Paragraph three covers evaluation. Trajectories are recorded and replayed deterministically."
)


def test_fixed_chunker_overlap():
    spans = FixedSizeChunker(chunk_size=50, overlap=10).split_text("x" * 120)
    assert spans == [(0, 50), (40, 90), (80, 120)]


def test_recursive_chunker_respects_size_and_paragraphs():
    doc = Document(TEXT, source="t.txt")
    chunks = RecursiveChunker(chunk_size=120, overlap=0).chunk(doc)
    assert all(len(c.content) <= 120 for c in chunks)
    assert chunks[0].content.startswith("Paragraph one") and len(chunks) >= 3
    assert all(c.doc_id == doc.id for c in chunks) and [c.index for c in chunks] == list(
        range(len(chunks))
    )
    # with overlap the next chunk repeats whole trailing pieces (here: sentences)
    text = " ".join(f"Sentence number {i} is here." for i in range(30))
    overlapped = RecursiveChunker(chunk_size=100, overlap=40).split_text(text)
    assert all(e - s <= 100 for s, e in overlapped)
    assert any(overlapped[i + 1][0] < overlapped[i][1] for i in range(len(overlapped) - 1))


def test_sentence_chunker_keeps_sentences_whole():
    spans = SentenceChunker(chunk_size=80, overlap_sentences=0).split_text(TEXT)
    for s, e in spans:
        piece = TEXT[s:e].strip()
        assert piece.endswith((".", "\n")) or piece == TEXT[s:].strip()


def test_markdown_chunker_heading_paths():
    md = "# Guide\nIntro text here.\n## Install\nRun pip install.\n## Usage\n### CLI\nUse the cli command.\n"
    chunks = MarkdownChunker(chunk_size=200).chunk(Document(md, source="g.md"))
    headings = [c.metadata["heading"] for c in chunks]
    assert headings == ["Guide", "Guide > Install", "Guide > Usage > CLI"]
    assert chunks[2].content.startswith("[Guide > Usage > CLI]")


def test_bm25_ranks_keyword_matches():
    bm = BM25()
    bm.add_many(
        [
            ("d1", "the cat sat on the mat"),
            ("d2", "dogs and cats are pets"),
            ("d3", "error code E1234 in the parser"),
        ]
    )
    assert bm.search("E1234", 1)[0][0] == "d3"
    assert bm.search("cats", 3)[0][0] in ("d1", "d2")
    assert tokenize("Running tests") == ["runn", "test"] or "test" in tokenize("Running tests")
    bm.remove("d3")
    assert bm.search("E1234") == []
    clone = BM25.from_dict(json.loads(json.dumps(bm.to_dict())))
    assert clone.search("pets") == bm.search("pets")


def test_rrf():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "a", "d"]], k=60)
    assert fused[0][0] == "a"
    assert {d for d, _ in fused} == {"a", "b", "c", "d"}


def test_rerankers():
    from agentcore.rag.documents import Chunk

    cands = [
        ScoredChunk(Chunk("unrelated words about cooking", "d", 0), 1.0),
        ScoredChunk(Chunk("hnsw graph search uses layers", "d", 1), 0.5),
    ]
    out = LexicalReranker().rerank("hnsw graph search", cands, 2)
    assert out[0].content.startswith("hnsw")
    mmr = MMRReranker(HashingEmbedder(64)).rerank("hnsw graph", cands, 1)
    assert len(mmr) == 1


def test_citation_tracker():
    from agentcore.rag.documents import Chunk

    srcs = [
        ScoredChunk(
            Chunk("BM25 is a lexical ranking function.", "d", 0, metadata={"title": "BM25"}), 1.0
        )
    ]
    t = CitationTracker(srcs)
    text = "BM25 is a lexical ranking function. [1] Penguins live in deserts [1]. Also [7]."
    assert t.cited_numbers(text) == [1, 7]
    assert t.invalid_numbers(text) == [7]
    cites = t.citations(text)
    assert len(cites) == 1 and cites[0].supported is False  # the penguin claim is unsupported
    assert t.verify_claim("BM25 is a ranking function", 1)
    assert "[1] BM25" in t.bibliography(text)


def test_pipeline_end_to_end_with_mock_model(tmp_path):
    emb = HashingEmbedder(128)
    rag = RAGPipeline(
        embedder=emb, index=HNSWIndex(128, M=8, ef_construction=50), model=MockModel(), k=3
    )
    n = rag.ingest(EXAMPLES / "data")
    assert n > 5
    hits = rag.retrieve("What does the parameter ef_search control in HNSW?")
    assert "hnsw" in hits[0].chunk.source.lower()
    answer = run(rag.answer("What does reciprocal rank fusion do?"))
    assert answer.citations and not answer.invalid_citations
    assert "hybrid-search" in answer.citations[0].source
    assert "[" in answer.text and answer.format().count("Sources:") == 1

    rag.save(tmp_path / "kb")
    loaded = RAGPipeline.load(tmp_path / "kb", embedder=emb, k=3)
    assert [h.id for h in loaded.retrieve("saga compensation")] == [
        h.id for h in rag.retrieve("saga compensation")
    ]


def test_pipeline_prompt_and_tool():
    model = ScriptedModel(["Answer [1]."])
    rag = RAGPipeline(model=model)
    rag.add_texts(["Ollama serves local models on port 11434.", "Bananas are yellow."])
    ans = rag.answer_sync("Which port does Ollama use?")
    sent = model.calls[0]["messages"][-1].content
    assert sent.startswith("Sources:") and "[1]" in sent and "Question: Which port" in sent
    assert ans.citations[0].number == 1
    search = rag.as_tool()
    assert search.name == "search_docs" and "11434" in search(query="ollama port")


def test_loaders(tmp_path):
    (tmp_path / "a.md").write_text("# Title A\nbody", encoding="utf-8")
    (tmp_path / "b.html").write_text("<title>Page B</title><p>hello html</p>", encoding="utf-8")
    (tmp_path / "c.jsonl").write_text(
        '{"text": "row one", "title": "R1"}\n{"text": "row two"}\n', encoding="utf-8"
    )
    (tmp_path / "skip.bin").write_bytes(b"\x00\x01")
    docs = load_directory(tmp_path)
    titles = sorted(d.title for d in docs)
    assert titles == ["Page B", "R1", "Title A", "c:1"]
    assert any("hello html" in d.content for d in docs)
