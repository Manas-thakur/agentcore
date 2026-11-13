# AgentCore

**Build, trace and evaluate AI agents, from scratch, in plain Python.**

[![CI](https://github.com/Manas-thakur/agentcore/actions/workflows/ci.yml/badge.svg)](https://github.com/Manas-thakur/agentcore/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Manas-thakur/agentcore?sort=semver)](https://github.com/Manas-thakur/agentcore/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)

AgentCore is an agent platform you can read: a ReAct runtime with native tool calling, a typed tool
framework with a sandbox, an evaluation harness with deterministic replay, RAG with hybrid search,
vector indexes (HNSW / IVF / PQ) written with numpy, a workflow-graph engine with human-in-the-loop
and saga compensation, multi-agent teams and built-in observability, plus a web app to chat with
your agent, inspect every step and catch regressions. No LangChain, LangGraph, AutoGen or CrewAI:
the runtime dependencies are `httpx`, `numpy` and `pyyaml`. Everything runs **offline** out of the
box on a deterministic mock model.

**[Website](https://manas-thakur.github.io/agentcore/)** ·
**[Documentation](https://manas-thakur.github.io/agentcore/docs/)** ·
**[Quickstart](https://manas-thakur.github.io/agentcore/docs/quickstart/)** ·
**[HTTP API](https://manas-thakur.github.io/agentcore/docs/reference/http-api/)** ·
**[Changelog](CHANGELOG.md)**

![The AgentCore web app: a chat reply with its run summary expanded into the step timeline, next to the run settings](docs/screenshots/playground.png)

<sub>Screenshots show **sample data**: the offline mock model plus generated sample traces (including
Ollama- and OpenAI-style runs) so the charts have shape. Your dashboard shows your own runs.</sub>

## Features

- **Runtime**: ReAct loop with native tool calling, parallel tools, token streaming, events, memory
  tiers, context budgeting, timeouts, stuck detection and reflection. One string picks the model:
  `mock`, `ollama:<model>` or `openai:<model>` (any OpenAI-compatible server).
- **Tools**: `@tool` turns typed Python functions into JSON-Schema tools (dataclasses, `Literal`,
  `Enum`, `TypedDict`, pydantic) with validation and coercion, timeouts, retries, rate limits and a
  subprocess sandbox.
- **Eval**: YAML suites that check outputs, tool calls, trajectories and step budgets, LLM-as-judge,
  record/replay cassettes, baselines and regression gates for CI.
- **RAG**: loaders, markdown-aware chunking, BM25 + dense hybrid retrieval with reciprocal rank
  fusion, rerankers and answers with citations.
- **Vector indexes**: Flat, HNSW, IVF, scalar and product quantization from scratch, with metadata
  filters, deletes and save/load.
- **Workflow graphs**: conditional edges, parallel fan-out and joins, reducers, retries, fallbacks,
  checkpoints, `interrupt()` for human approval, saga compensation, subgraphs, Mermaid export.
- **Multi-agent**: planner, researcher, coder and reviewer specialists on an A2A message bus, with
  manager-worker, pipeline and peer-review patterns.
- **Observability**: spans in JSONL files (optionally mirrored to OpenTelemetry), Prometheus-style
  metrics, JSON logs and cost tracking.
- **Web app and API** (`agentcore serve`): streaming chat with a step timeline, a trace explorer with
  a query language, an eval results matrix with regressions, an overview of latency, tokens and
  cost, a tool tester, a command palette, light/dark themes and phone layouts; plus `/v1/agent` and
  an **OpenAI-compatible `/v1/chat/completions`** endpoint.

| Traces | Evals |
|---|---|
| ![Trace explorer with query bar, facets, histogram and a side peek showing the span tree](docs/screenshots/traces.png) | ![Results matrix of cases by runs with a regression outlined and the case peek open](docs/screenshots/evals.png) |
| **Overview** | **Tools** |
| ![KPI cards with sparklines and deltas, latency and volume charts](docs/screenshots/overview.png) | ![Tool page with the generated try-it form, a result and the JSON Schema](docs/screenshots/tools.png) |

## Quickstart (offline, no model needed)

```bash
pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"

agentcore init my-agent && cd my-agent          # agent.py with a @tool, evals, agentcore.toml
python agent.py --model mock "What is the capital of France?"
agentcore eval --suite evals/basic.yaml --model mock
agentcore serve --model mock                    # web app at http://127.0.0.1:8000
```

Then open `http://127.0.0.1:8000`, press `Ctrl/Cmd+K` for the command palette and `?` for shortcuts.
For real answers use `--model ollama:qwen2.5:7b` or set `OPENAI_BASE_URL` / `OPENAI_API_KEY` and use
`--model openai:<model>` ([models guide](https://manas-thakur.github.io/agentcore/docs/models/)).

## Install

Python 3.10+. The web app ships pre-built inside the package, so no Node.js is needed.

```bash
# pip (library + CLI; add [server] for the web app, [all] for everything)
pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"

# uv
uv add "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"

# Docker (GHCR, linux/amd64 + linux/arm64)
docker run -p 8000:8000 -e AGENTCORE_MODEL=mock ghcr.io/manas-thakur/agentcore:latest
```

Pin a release with `...agentcore@v0.3.1`. Release wheels are attached to
[GitHub Releases](https://github.com/Manas-thakur/agentcore/releases).
**AgentCore is not on PyPI**: the `agentcore` package there is a different project, so always
install from GitHub as above. Extras: `server` (FastAPI + uvicorn), `otel` (OpenTelemetry),
`pydantic`, `all`.
See [Installation](https://manas-thakur.github.io/agentcore/docs/installation/).

## Usage

### Python

```python
from agentcore import Agent, create_model, tool
from agentcore.tools import calculator


@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get the current weather for a city.

    Args:
        city: City name, e.g. "Pune".
        unit: "celsius" or "fahrenheit".
    """
    return f"22 degrees {unit} and sunny in {city}"


agent = Agent(create_model("mock"), tools=[calculator, get_weather], max_steps=8)
result = agent.run_sync("What is 17 * 23 + 4?")
print(result.output, result.stop_reason, result.usage.total_tokens)  # The answer is 395. final 174
```

Each module has a guide with runnable examples:
[runtime](https://manas-thakur.github.io/agentcore/docs/modules/runtime/),
[tools](https://manas-thakur.github.io/agentcore/docs/modules/tools/),
[eval](https://manas-thakur.github.io/agentcore/docs/modules/eval/),
[RAG](https://manas-thakur.github.io/agentcore/docs/modules/rag/),
[vector indexes](https://manas-thakur.github.io/agentcore/docs/modules/indexes/),
[workflow graphs](https://manas-thakur.github.io/agentcore/docs/modules/graph/),
[multi-agent](https://manas-thakur.github.io/agentcore/docs/modules/agents/),
[observability](https://manas-thakur.github.io/agentcore/docs/modules/obs/).

### CLI

| Command | What it does |
|---|---|
| `agentcore init [DIR]` | Scaffold a project that runs offline with `--model mock` |
| `agentcore chat [-p PROMPT]` | Interactive or one-shot chat with a tool-using agent |
| `agentcore eval --suite S` | Run an eval suite; baselines, record/replay, LLM judge, `--fail-under` |
| `agentcore serve` | Web app + HTTP API |
| `agentcore traces list` / `show ID` | Inspect stored traces |
| `agentcore research TOPIC --docs DIR` | Researcher agent that writes a cited report |
| `agentcore tools [--schema]` | List tools and their JSON Schemas |
| `agentcore doctor [--ping]` | Check the environment, config and model reachability |
| `agentcore run SCRIPT` | Run a Python script with arguments |

Every flag: [CLI reference](https://manas-thakur.github.io/agentcore/docs/reference/cli/).

### Web app and HTTP API

`agentcore serve` serves the web app (Playground, Traces, Evals, Overview, Tools, Settings) and the
API: `/v1/agent`, streaming `/api/chat` (Server-Sent Events) with sessions, the OpenAI-compatible
`/v1/chat/completions`, trace, eval, overview, tool and config endpoints, `/metrics` and `/docs`.

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions -H "Content-Type: application/json" \
     -d '{"model": "agentcore", "messages": [{"role": "user", "content": "What is 2 ** 10?"}]}'
```

See the [web app guide](https://manas-thakur.github.io/agentcore/docs/web-app/), the
[HTTP API reference](https://manas-thakur.github.io/agentcore/docs/reference/http-api/) and the
[trace query language](https://manas-thakur.github.io/agentcore/docs/reference/query-language/).

## Configuration

Settings come from CLI flags, then `AGENTCORE_*` environment variables, then `agentcore.toml`, then
defaults:

```toml
model = "mock"                         # mock | auto | ollama:<m> | openai:<m>
models = ["ollama:qwen2.5:7b"]         # extra entries for the web app's model picker
tools = ["calculator", "current_time"]
tool_modules = ["agent.py"]            # files or modules defining @tool functions
trace_dir = ".agentcore/traces"
eval_dirs = ["evals"]

[server]
host = "127.0.0.1"
port = 8000
cors_origins = []
max_body_kb = 1024
```

Key environment variables: `AGENTCORE_MODEL`, `AGENTCORE_API_KEY` (protects the server; never in the
file), `AGENTCORE_TRACE_DIR`, `AGENTCORE_DATA_DIR`, `AGENTCORE_EVAL_DIRS`, `AGENTCORE_CORS_ORIGINS`,
`OLLAMA_HOST`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`. Full table:
[Configuration](https://manas-thakur.github.io/agentcore/docs/configuration/). Deploying beyond
localhost: [Deployment](https://manas-thakur.github.io/agentcore/docs/deployment/) (always set an API
key).

## Architecture

```text
                ┌──────────────────────── agentcore serve ────────────────────────┐
                │  web app (Playground, Traces, Evals, Overview, Tools, Settings) │
                │  HTTP API · SSE chat · OpenAI-compatible /v1/chat/completions   │
                └─────────────────────────────────────────────────────────────────┘
  runtime ──► tools ──► eval ──► rag / index ──► graph ──► agents ──► obs
```

| Module | Implements |
|---|---|
| `agentcore.runtime` | `Agent` (ReAct loop), model clients (`mock`, Ollama, OpenAI-compatible), memory tiers, context budgeting |
| `agentcore.tools` | `@tool`, schema generation, validation, `ExecutionEngine`, `SubprocessSandbox`, built-in tools |
| `agentcore.eval` | Suites, trajectories, metrics, LLM-as-judge, cassettes, `compare` |
| `agentcore.rag` | Loaders, chunkers, embedders, BM25, hybrid retrieval, rerankers, citations |
| `agentcore.index` | Flat, HNSW, IVF, SQ8, PQ indexes |
| `agentcore.graph` | `StateGraph`, reducers, checkpoints, `interrupt()`, compensation |
| `agentcore.agents` | Specialists, `MessageBus`, `ManagerWorker`, `Pipeline`, `peer_review` |
| `agentcore.obs` | Tracer, JSONL store, metrics, logging, cost |
| `agentcore.server` | FastAPI app, sessions, eval jobs, analytics, auth, and the built web app in `static/` |

How it fits together: [Concepts](https://manas-thakur.github.io/agentcore/docs/concepts/).

## Development

```bash
git clone https://github.com/Manas-thakur/agentcore.git && cd agentcore

# Python
uv sync --all-extras
uv run pytest -q && uv run ruff check . && uv run ruff format --check .

# Web app (web/: Vite + React 19 + TypeScript + Tailwind v4 + shadcn/ui)
pnpm --dir web install
pnpm --dir web dev          # http://127.0.0.1:8762, proxies the API to agentcore serve on :8761
pnpm --dir web typecheck && pnpm --dir web lint && pnpm --dir web test
pnpm --dir web build        # writes src/agentcore/server/static (commit it)

# Docs site (site/: Astro + Starlight)
pnpm --dir site install
pnpm --dir site dev         # http://127.0.0.1:8763/agentcore/
pnpm --dir site build
```

The UI kit choice and the patterns the app borrows are written up in
[docs/design/references.md](docs/design/references.md).

## Status and roadmap

AgentCore is beta (0.3.0): the APIs are tested and documented but may change between minor
versions. It is single-user and local-first (file-based state, one optional API key). Not built
yet: multi-user accounts and database-backed sessions, eval runs across several models side by
side, trace retention policies, provider adapters beyond Ollama and OpenAI-compatible HTTP,
container/WASM sandboxes, external vector stores (LanceDB, pgvector), PDF loading and
semantic chunking, and deployment templates beyond Docker. The original design documents are in
[`plans/`](plans/).

## Contributing

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) for the toolchains, the checks a
pull request must pass and the release process.

## License

MIT, see [LICENSE](LICENSE).
