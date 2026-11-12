# AgentCore

**A from-scratch agentic AI platform in plain Python.** ReAct runtime with native tool calling, a
type-safe tool framework with sandboxed execution, an evaluation harness with deterministic replay,
RAG with hybrid search, vector indexes (HNSW / IVF / PQ) written from scratch, a workflow-graph engine
with human-in-the-loop and saga compensation, multi-agent collaboration, and built-in observability.

No LangChain, no LangGraph, no AutoGen, no CrewAI. Runtime dependencies: `httpx`, `numpy`, `pyyaml`.

[![CI](https://github.com/Manas-thakur/agentcore/actions/workflows/ci.yml/badge.svg)](https://github.com/Manas-thakur/agentcore/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
![license](https://img.shields.io/badge/license-MIT-green)

Everything runs **offline** out of the box: a deterministic rule-based `mock` model drives the
examples, tests and CI. Point the same code at a local model (Ollama) or any OpenAI-compatible
server (OpenAI, vLLM, LM Studio, Groq, llama.cpp, ...) by changing one flag.

---

## Philosophy

Build every component of an agentic AI system from scratch, so that someone reading the code can
understand exactly how production agent systems work under the hood: the agent loop, the tool
registry, memory, the evaluation harness, the orchestration graph and the observability layer. Each
component is independently usable and tested.

Most AI engineers know how to call an LLM API and chain a few framework calls together. Far fewer
understand how a ReAct loop actually works, how to generate JSON Schema from Python functions, how to
implement BM25 + dense hybrid search, how HNSW navigates a graph, how a workflow engine checkpoints
and compensates, or how to evaluate non-deterministic agents deterministically. This repository is an
implementation of all of those.

### Development principles

1. **No framework dependencies for core logic.** Libraries are used for transport (`httpx`), math
   (`numpy`) and parsing (`pyyaml`) - never for architecture.
2. **Every component is independently testable.** LLM calls are mocked or replayed; the full test
   suite runs offline in seconds.
3. **Deterministic where possible.** Scripted/mock models and recorded "cassettes" make agent runs
   reproducible.
4. **Observability is first-class.** Agent runs, model calls, tool calls, graph nodes and A2A
   messages all emit spans, metrics and cost data.
5. **Model-agnostic.** `mock`, `ollama:<model>` or `openai:<model>` - one string.

## What's inside

| Module | What it implements | Key types |
|---|---|---|
| `agentcore.runtime` | ReAct loop with native tool calling, parallel tool execution, max-steps/timeout guards, stuck detection, reflection hooks, token streaming, event callbacks; memory tiers; context-window budgeting | `Agent`, `create_model`, `OllamaClient`, `OpenAICompatibleClient`, `MockModel`, `ScriptedModel`, `BufferMemory`, `SlidingWindowMemory`, `SummarizingMemory`, `LongTermMemory`, `HybridMemory`, `ContextManager` |
| `agentcore.tools` | `@tool` -> JSON Schema from type hints + Google/NumPy/Sphinx docstrings (Optional, Union, Literal, Enum, list/dict, dataclass, TypedDict, pydantic); validation with type coercion; execution engine with timeouts, retries, rate limits, hooks; subprocess sandbox; built-ins | `tool`, `ToolRegistry`, `ExecutionEngine`, `SubprocessSandbox`, `calculator`, `python_exec`, `file_tools`, `http_get`, `web_search` |
| `agentcore.eval` | YAML/JSON suites, trajectory recording, exact/contains/regex, tool-call and trajectory matching, step budgets, LLM-as-judge, record/replay cassettes, baseline regression detection, markdown reports | `EvalSuite`, `EvalRunner`, `TrajectoryRecorder`, `LLMAsJudge`, `Cassette`, `compare` |
| `agentcore.rag` | Loaders (txt/md/html/jsonl/dirs), fixed/recursive/sentence/markdown-aware chunkers, BM25, hybrid retrieval with reciprocal rank fusion, lexical and MMR rerankers, citation tracking and verification | `RAGPipeline`, `BM25`, `HybridRetriever`, `MarkdownChunker`, `CitationTracker` |
| `agentcore.index` | Flat (exact), HNSW, IVF (k-means++), scalar (int8) and product quantization with ADC, metadata filters, deletes, save/load | `FlatIndex`, `HNSWIndex`, `IVFIndex`, `SQIndex`, `PQIndex`, `load_index` |
| `agentcore.graph` | State-graph engine: nodes, static/conditional edges, parallel fan-out and joins, per-key reducers, retries, fallbacks, checkpoints (memory/file), `interrupt()`/resume for human-in-the-loop, saga compensation, subgraphs, Mermaid export | `StateGraph`, `interrupt`, `FileCheckpointer` |
| `agentcore.agents` | Researcher, Coder (sandboxed execution), Reviewer, Planner; in-process A2A message bus (direct, broadcast, topics, request/response); manager-worker, pipeline and peer-review patterns | `ResearcherAgent`, `CoderAgent`, `ReviewerAgent`, `PlannerAgent`, `MessageBus`, `ManagerWorker`, `Pipeline` |
| `agentcore.obs` | Span tracer (contextvar-based, async-safe) with optional OpenTelemetry mirroring, JSONL trace store, Prometheus-style metrics, JSON logging with trace ids, per-model cost tracking | `configure_tracing`, `JSONLTraceStore`, `MetricsCollector`, `CostTracker` |
| `agentcore.server` | FastAPI app: `POST /v1/agent`, trace API, `/metrics`, and a self-contained HTML trace dashboard | `create_app` |
| `agentcore.research` | Showcase "technical researcher": cited markdown report + trace + cost files | `research` |

### How it compares

| Aspect | Typical project | AgentCore |
|--------|----------------|-----------|
| Agent loop | Framework agent executor | Custom ReAct loop: native tool calls, parallel tools, reflection, stuck detection, streaming |
| Tools | Framework tool decorator | `@tool` -> JSON Schema -> validated, retried, sandboxed execution |
| Memory | Conversation buffer | Buffer, sliding window, summarizing, long-term vector memory, hybrid |
| Evaluation | Manual testing | Trajectory matching, LLM-as-judge, deterministic replay, regression gates in CI |
| RAG | Framework retrieval chain | Chunking, BM25 + dense hybrid search, RRF, rerank, verified citations |
| Vector index | FAISS/Pinecone wrapper | HNSW, IVF, Flat, SQ8, PQ implemented with numpy |
| Orchestration | LangGraph | State-graph engine with HITL interrupts, checkpoints, compensation, subgraphs |
| Observability | None | Spans (+ optional OpenTelemetry), metrics, structured logs, cost, trace dashboard |

## Installation

Requires Python 3.10+.

```bash
# Library + CLI
pip install "git+https://github.com/Manas-thakur/agentcore"

# With the HTTP server / dashboard (FastAPI + uvicorn)
pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"

# Everything (server, OpenTelemetry, pydantic support)
pip install "agentcore[all] @ git+https://github.com/Manas-thakur/agentcore"
```

### Development setup (uv)

```bash
git clone https://github.com/Manas-thakur/agentcore.git
cd agentcore
uv sync --all-extras          # or: make install
uv run pytest -q              # or: make test
uv run ruff check .           # or: make lint
```

`make` targets (`install`, `test`, `lint`, `format`, `eval`, `examples`, `serve`, `docker`, `check`)
are thin wrappers around the `uv` commands; on Windows without `make`, run the commands directly.

## Quick start (offline, no LLM needed)

Every command below works without any model server, using the deterministic `mock` model.
Inside a clone, prefix commands with `uv run` (or activate `.venv`).

```bash
# A tool-using ReAct agent
agentcore run examples/calculator_agent.py --model mock

# Ask one question from the CLI (or drop -p for an interactive chat)
agentcore chat --model mock -p "What is 17 * 23 + 4?"

# RAG over the sample docs with hybrid search and citations
python examples/rag_qa.py --model mock "How does reciprocal rank fusion work?"

# Workflow graph: fan-out/join, loop, human approval, compensation
python examples/workflow_graph.py
python examples/workflow_graph.py --fail

# Planner -> Researcher / Coder -> Reviewer over the A2A bus
python examples/multi_agent.py --model mock

# Run the eval suite (exit code 1 on failures/regressions)
agentcore eval --suite examples/evals/calculator_suite.yaml --model mock

# Research a topic over a local corpus -> report.md, report.trace.json, report.cost.json
agentcore research "How does HNSW search work?" --docs examples/data --model mock

# Inspect traces written by the runs above
agentcore traces list
agentcore traces show <trace-id-prefix>

# API + trace dashboard at http://127.0.0.1:8000 (needs the [server] extra)
agentcore serve --model mock
curl -s -X POST http://127.0.0.1:8000/v1/agent -H "Content-Type: application/json" \
     -d '{"input": "What is 2 ** 10?"}'
```

### Using a real model

```bash
# Ollama (https://ollama.com): pull a model with tool-calling support first
ollama pull qwen2.5:7b
agentcore chat --model ollama:qwen2.5:7b
python examples/calculator_agent.py --model ollama:qwen2.5:7b "What is 2**20 - 1?"

# OpenAI
export OPENAI_API_KEY=sk-...
agentcore chat --model openai:gpt-4o-mini

# Any OpenAI-compatible server (vLLM, LM Studio, llama.cpp, Groq, ...)
export OPENAI_BASE_URL=http://localhost:8000/v1   # e.g. vLLM
agentcore chat --model openai:Qwen/Qwen2.5-7B-Instruct
```

The examples default to `--model auto`: Ollama is used if it is reachable and
`AGENTCORE_OLLAMA_MODEL` (default `qwen2.5:7b`) is pulled; otherwise they fall back to `mock` and say so.

## Usage by module

### Runtime: agents, models, memory

```python
from agentcore import Agent, create_model, tool
from agentcore.runtime import SlidingWindowMemory
from agentcore.tools import calculator

@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get the current weather for a city.

    Args:
        city: City name, e.g. "Pune".
        unit: "celsius" or "fahrenheit".
    """
    return f"22 degrees {unit} and sunny in {city}"

agent = Agent(
    create_model("mock"),                 # or "ollama:qwen2.5:7b", "openai:gpt-4o-mini"
    tools=[calculator, get_weather],
    memory=SlidingWindowMemory(max_turns=5),
    max_steps=8,
)
agent.on(lambda ev: print(ev.type, ev.data.get("name", "")))   # event callbacks
result = agent.run_sync("What is 17 * 23 + 4?")
print(result.output, result.stop_reason, result.usage.total_tokens)
```

`await agent.run(...)` is the async API; `async for ev in agent.stream(task)` yields events (including
tokens when `stream=True`). Other options: `reflect_every=N` (periodic LLM self-reflection),
`reflection_hook=fn`, `stuck_threshold`, `timeout_seconds`, `context_window` (enables truncation via
`ContextManager`), `parallel_tool_calls`. `agent.as_tool()` turns an agent into a tool for another agent.

Memory tiers: `BufferMemory` (message/token budget), `SlidingWindowMemory` (last N turns),
`SummarizingMemory(model)` (folds old turns into a structured summary), `LongTermMemory` (vector
recall with importance scores), `HybridMemory` (window + long-term). All support `save()`/`load()`.

### Tools: schema generation, validation, sandbox

```python
from dataclasses import dataclass
from typing import Literal
from agentcore.tools import tool, ToolRegistry, ExecutionEngine, SubprocessSandbox, SandboxConfig

@dataclass
class Point:
    x: float
    y: float = 0.0

@tool(timeout=5, retries=1, category="geometry")
def distance(a: Point, b: Point, metric: Literal["euclid", "manhattan"] = "euclid") -> float:
    """Distance between two points.

    Args:
        a: First point.
        b: Second point.
        metric: Distance metric.
    """
    if metric == "manhattan":
        return abs(a.x - b.x) + abs(a.y - b.y)
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5

print(distance.parameters)              # JSON Schema (dataclass -> nested object, Literal -> enum)
engine = ExecutionEngine(ToolRegistry([distance]))
import asyncio
res = asyncio.run(engine.execute("distance", {"a": {"x": "3"}, "b": {"x": 0, "y": 4}}))
print(res.success, res.output)          # True 5.0  ("3" was coerced to 3.0)

print(SubprocessSandbox(SandboxConfig(timeout_seconds=5)).run("print(sum(range(10)))").stdout)
```

Built-ins: `calculator` (AST-based, no `eval`), `python_exec` (sandboxed subprocess), `read_file` /
`write_file` / `list_files` (workspace-scoped, path-traversal safe), `http_get`, `web_search`
(DuckDuckGo HTML), `current_time`. The sandbox is best-effort isolation (isolated interpreter, temp dir,
timeout, POSIX resource limits, no network, optional import allow-list) - use containers for untrusted
multi-tenant code.

### Eval: suites, trajectories, replay, regressions

```yaml
# examples/evals/calculator_suite.yaml (excerpt)
name: calculator-basic
agent:
  tools: [calculator]
  max_steps: 5
cases:
  - name: multiply_add
    input: "What is 17 * 23 + 4?"
    expected_output: "395"            # match: contains (default) | exact | regex
    expected_tool_calls:
      - tool: calculator
        args: {expression: "17 * 23 + 4"}
    max_steps: 3
```

```python
from agentcore.eval import EvalRunner, load_suite, compare

suite = load_suite("examples/evals/calculator_suite.yaml")
report = EvalRunner("mock", record_to="cassette.json").run_suite_sync(suite)
print(report.to_markdown())

replayed = EvalRunner(replay_from="cassette.json").run_suite_sync(suite)   # no model needed
print(compare(report, replayed).has_regressions)                            # False
```

CLI: `agentcore eval --suite S --model M [--baseline base.json --save-baseline] [--record c.json |
--replay c.json] [--judge-model ollama:qwen2.5:7b] [--output r.json --markdown r.md]`.

### RAG: hybrid search with citations

```python
from agentcore import create_model
from agentcore.index import HNSWIndex
from agentcore.rag import RAGPipeline, MarkdownChunker, HashingEmbedder

emb = HashingEmbedder(256)        # offline; or OllamaEmbedder("nomic-embed-text"), OpenAIEmbedder()
rag = RAGPipeline(embedder=emb, index=HNSWIndex(256), chunker=MarkdownChunker(600),
                  model=create_model("mock"), k=3)
rag.ingest("examples/data")
answer = rag.answer_sync("What does ef_search control?")
print(answer.format())            # answer text with [n] citations + verified sources
search_tool = rag.as_tool("search_docs")   # give retrieval to an agent
```

### Vector indexes

```python
import numpy as np
from agentcore.index import FlatIndex, HNSWIndex, IVFIndex, PQIndex, load_index, recall_at_k

x = np.random.default_rng(0).normal(size=(2000, 64)).astype("float32")
ids = [f"v{i}" for i in range(len(x))]
flat, hnsw = FlatIndex(64), HNSWIndex(64, M=16, ef_construction=200, ef_search=64)
flat.add(x, ids); hnsw.add(x, ids)
truth = [[r.id for r in flat.search(q, 10)] for q in x[:20]]
approx = [[r.id for r in hnsw.search(q, 10)] for q in x[:20]]
print(recall_at_k(truth, approx, 10))
hnsw.save("hnsw.npz"); same = load_index("hnsw.npz")
```

### Workflow graphs

```python
from agentcore.graph import StateGraph, START, END, append, interrupt

g = StateGraph("review", reducers={"notes": append})
g.add_node("search_a", lambda s: {"notes": "A"})
g.add_node("search_b", lambda s: {"notes": "B"})
g.add_node("approve", lambda s: {"ok": interrupt({"question": "Ship it?"}) == "yes"})
g.add_node("ship", lambda s: {"shipped": True}, compensate=lambda s: print("rollback"))
g.add_edge(START, ["search_a", "search_b"])          # parallel fan-out
g.add_edge(["search_a", "search_b"], "approve")      # join
g.add_conditional_edges("approve", lambda s: "yes" if s["ok"] else "no", {"yes": "ship", "no": END})
app = g.compile()

r = app.run_sync({})                 # -> status "interrupted", r.interrupt["payload"]
r = app.resume_sync(r.thread_id, "yes")
print(r.status, r.state)             # completed {'notes': [...], 'ok': True, 'shipped': True}
print(g.to_mermaid())
```

### Multi-agent

```python
import asyncio
from agentcore import create_model
from agentcore.agents import ManagerWorker, PlannerAgent, ResearcherAgent, CoderAgent, ReviewerAgent
from agentcore.rag import RAGPipeline

model = create_model("mock")
kb = RAGPipeline(); kb.ingest("examples/data")
team = ManagerWorker(PlannerAgent(model), {
    "researcher": ResearcherAgent(model, knowledge_base=kb),
    "coder": CoderAgent(model),
    "reviewer": ReviewerAgent(model),
})
result = asyncio.run(team.run("Research HNSW and compute 2**10, then review the results"))
print(result.output)
```

### Observability

```python
from agentcore.obs import configure_tracing, get_metrics, CostTracker

configure_tracing(".agentcore/traces", use_otel=False)   # JSONL spans; use_otel=True mirrors to OpenTelemetry
costs = CostTracker()                                     # pass cost_tracker=costs to Agent / agents
# ... run agents ...
print(get_metrics().export_prometheus())
```

Spans: `agent.run:<name>` > `agent.step` > `model.generate` (tokens, cost, latency) / `tool.execute`;
`graph.run:<name>` > `graph.node:<node>`; `a2a.deliver`. With `use_otel=True` and the `otel` extra
installed, every span is mirrored to the OpenTelemetry API so any configured exporter (OTLP, Jaeger,
Tempo, ...) receives it. The dashboard served by `agentcore serve` reads the same JSONL files.

## CLI reference

| Command | Description |
|---|---|
| `agentcore run SCRIPT [ARGS...]` | Run a Python script (e.g. an example) with arguments |
| `agentcore chat [--model M] [--tools a,b] [-p PROMPT] [--stream] [-v]` | Interactive or one-shot chat with a tool-using agent (sliding-window memory) |
| `agentcore eval --suite PATH [--model M] [...]` | Run an eval suite; options for baselines, regression threshold, record/replay, LLM judge, reports, `--fail-under` |
| `agentcore traces list [--limit N]` / `agentcore traces show ID [--json]` | Inspect stored traces (`--dir` before the subcommand to change the directory) |
| `agentcore serve [--host H] [--port P] [--model M] [--tools a,b]` | HTTP API + dashboard (requires `[server]`) |
| `agentcore research TOPIC (--docs DIR \| --web) [--out report.md]` | Researcher agent; writes report, trace and cost JSON |
| `agentcore tools [--schema]` | List built-in tools and their JSON Schemas |

HTTP API (`agentcore serve`): `POST /v1/agent` with `{"input": "..."}` or `{"messages": [...]}`
(optional `model`, `tools`, `system_prompt`, `max_steps`); `GET /health`, `GET /v1/models`,
`GET /api/traces`, `GET /api/traces/{id}`, `GET /metrics`, and the dashboard at `/`. Only
`calculator` and `current_time` are enabled by default; enable more with `--tools`
(be careful exposing `python_exec` or file tools on a network).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AGENTCORE_MODEL` | `auto` | Default model spec when `--model` is not given |
| `AGENTCORE_OLLAMA_MODEL` | `qwen2.5:7b` | Model `auto` looks for in Ollama |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `OPENAI_API_KEY` | - | API key for `openai:<model>` |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint (vLLM, LM Studio, Groq, ...) |
| `AGENTCORE_EMBEDDER` | `hash` | Embedder for `create_embedder()`: `hash`, `ollama:<model>`, `openai:<model>` |
| `AGENTCORE_TRACE_DIR` | `.agentcore/traces` | Where the CLI and server write traces |

Model specs: `mock`, `auto`, `ollama:<model>`, `openai:<model>`; `vllm:`, `lmstudio:` and `groq:`
prefixes are aliases for the OpenAI-compatible client (they read `OPENAI_BASE_URL` / `OPENAI_API_KEY`).
Costs come from `agentcore.obs.PRICE_TABLE` (USD per 1M tokens, illustrative - pass your own table to
`CostTracker`); local models are free.

### Optional extras

| Extra | Adds |
|---|---|
| `server` | FastAPI + uvicorn for `agentcore serve` |
| `otel` | OpenTelemetry API/SDK for span mirroring |
| `pydantic` | pydantic v2 models as tool parameters (schema + validation) |
| `all` | all of the above |

`tiktoken` is used for token counting automatically if installed; otherwise a calibrated heuristic is used.

## Deployment

```bash
docker compose up --build                              # AgentCore API/dashboard + Ollama
docker compose exec ollama ollama pull qwen2.5:7b      # first run only
open http://localhost:8000
```

The `Dockerfile` builds a slim image (`agentcore serve` on port 8000, traces in `/data`).
`docker run -p 8000:8000 -e AGENTCORE_MODEL=mock <image>` runs it with no model server.

## Project layout

```
agentcore/
├── src/agentcore/
│   ├── types.py          # Message, ToolCall, ChatResponse, Usage, stream events
│   ├── embeddings.py     # Hashing / Ollama / OpenAI embedders
│   ├── runtime/          # Agent loop, providers (ollama, openai_compat, mock), memory, context
│   ├── tools/            # @tool, schema, validation, registry, execution, sandbox, builtins/
│   ├── eval/             # suite, trajectory, metrics, replay, runner, regression
│   ├── rag/              # documents, chunking, bm25, retrieval, rerank, generation
│   ├── index/            # flat, hnsw, ivf, kmeans, quantization
│   ├── graph/            # state graph engine, checkpoints
│   ├── agents/           # specialists, A2A bus, collaboration patterns
│   ├── obs/              # tracing, storage, metrics, logging, cost
│   ├── server/           # FastAPI app + static dashboard
│   ├── research.py       # showcase researcher
│   └── cli.py            # `agentcore` command
├── examples/             # runnable demos, sample corpus, eval suite
├── tests/                # pytest suite (offline)
├── plans/                # original design documents for each component
├── Dockerfile, docker-compose.yml, Makefile
└── .github/workflows/ci.yml
```

## Roadmap

Implemented pragmatically from `plans/`; not done yet:

- **TypeScript CLI and React dashboard** - replaced by the Python `agentcore` CLI and a
  self-contained static HTML dashboard served by `agentcore serve` (no build step).
- **More provider adapters** - only Ollama (native API) and OpenAI-compatible HTTP are built in.
- **Container/WASM tool sandboxes** - only the subprocess sandbox exists; shell and SQL tools are not
  included.
- **External vector stores** - LanceDB, pgvector and Pinecone adapters; IVF-PQ composite index.
- **RAG extras** - PDF loading, semantic/hierarchical chunking, cross-encoder model (a hook exists via
  `CallableReranker`), outline -> draft -> critique multi-pass generation.
- **Eval extras** - embedding-based semantic similarity metric, PR-comment GitHub workflow,
  per-config baseline storage.
- **Graph extras** - notification channels (Slack/email) and timeouts for human input, adaptive
  execution strategies.
- **Observability storage** - SQLite store and Grafana dashboards (JSONL + Prometheus text today).
- **Deployment** - Helm chart, Terraform/GCP Cloud Run; docs site and blog posts.

## License

MIT - see [LICENSE](LICENSE).
