# AgentCore — From-Scratch Production-Grade Agentic AI Platform

## Philosophy

Build every component of an agentic AI system from scratch. No LangChain, no LangGraph, no AutoGen, no CrewAI. Raw Python, raw TypeScript, raw understanding.

This is not a wrapper project. This is an **architecture and implementation deep-dive** into what makes agentic systems work: the agent loop, the tool registry, the memory systems, the evaluation harness, the orchestration graph, and the observability layer. Each component is independently usable, fully tested, and documented with the intent that someone reading the code can understand exactly how production agent systems work under the hood.

## Why This Matters

Most AI engineers today know how to call an LLM API and string together a few LangChain chains. Far fewer understand:
- How a ReAct loop actually works (the plan → act → observe → reflect cycle)
- How to build a type-safe tool registry with JSON Schema generation from Python functions
- How to implement hybrid search (BM25 + dense vectors) from scratch
- How to build a DAG-based workflow engine with human-in-the-loop and compensation
- How to instrument an agent system with OpenTelemetry for full observability
- How to evaluate non-deterministic agent behavior deterministically

**AgentCore proves you understand all of these.**

## Target Audience

- AI Engineer roles (internship / new grad / junior)
- Companies building production agentic systems
- Teams that need engineers who can operate below the framework abstraction

## Key Differentiators

| Aspect | Typical Project | AgentCore |
|--------|----------------|-----------|
| Agent loop | Uses LangChain AgentExecutor | Custom ReAct loop with planning, reflection, streaming |
| Tools | LangChain tool decorator | `@tool` → JSON Schema → sandboxed execution from scratch |
| Memory | ConversationBufferWindowMemory | Multi-tier: short-term, sliding window, summarizing, long-term (vector) |
| Evaluation | Manual testing | Trajectory comparison, LLM-as-judge, deterministic replay, CI integration |
| RAG | LangChain retrieval chain | Custom: ingest, chunk, hybrid search, rerank, citation from scratch |
| Vector Index | FAISS/Pinecone wrapper | Abstraction layer: HNSW, IVF, Flat + quantization from scratch |
| Orchestration | LangGraph | Custom DAG engine with HITL, compensation, subgraphs |
| Observability | None | OpenTelemetry spans, metrics, logging, cost tracking, React dashboard |

## Monorepo Structure

```
agentcore/
├── packages/
│   ├── python/
│   │   ├── runtime/        # Agent loop, memory, context management
│   │   ├── tools/          # Tool registry, schema→fn binding, sandbox
│   │   ├── eval/           # Evaluation harness, trajectory replay, LLM-as-judge
│   │   ├── rag/            # Ingest, chunk, hybrid search, rerank, cite
│   │   ├── index/          # Vector index abstraction (HNSW, IVF, Flat)
│   │   ├── graph/          # DAG workflow engine, HITL, compensation
│   │   ├── agents/         # Specialized agents + A2A protocol
│   │   ├── obs/            # OpenTelemetry spans, metrics, logging, cost
│   │   └── deploy/         # Docker, CI/CD templates, Helm, Terraform
│   └── typescript/
│       ├── cli/            # agentcore CLI: init, run, eval, deploy, serve
│       └── dashboard/      # React dashboard: traces, evals, cost, model mgmt
├── apps/
│   └── researcher/         # Showcase: Autonomous Technical Researcher
├── docs/                   # Astro + MDX blog + API docs
├── infra/                  # Terraform, docker-compose
└── .github/workflows/      # CI matrix: lint, typecheck, test, eval
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Core Runtime** | Python 3.11+ (uv for package management) |
| **CLI / Dashboard** | TypeScript, Node 20+ (pnpm workspaces) |
| **Local LLM** | Ollama (dev) → vLLM (prod) on RTX 4060 |
| **Vector DB** | LanceDB (embedded, local) + pgvector/Neon (cloud) |
| **Observability** | OpenTelemetry + Grafana Cloud (free tier) |
| **Blog/Docs** | Astro + MDX on GitHub Pages |
| **CI/CD** | GitHub Actions (Turborepo for monorepo orchestration) |
| **Cloud Deploy** | GCP Free Tier (Cloud Run, Cloud SQL, Artifact Registry) |

## Cost: $0

- Local LLM inference on RTX 4060 (Llama 3.1 8B / Qwen 2.5 7B at 4-bit)
- LanceDB for local vector storage (embedded, zero-dependency)
- Neon PostgreSQL for cloud (free tier with pgvector)
- GCP Free Tier for cloud services
- Grafana Cloud for observability (free tier)
- GitHub Actions for CI (2000 min/month free)
- GitHub Pages for docs/blog

## Development Principles

1. **No framework dependencies for core logic.** The core agent loop, tools, eval, RAG, and orchestration are built from scratch. We may use libraries for specific implementation details (e.g., `httpx` for HTTP, `trafilatura` for web scraping) but never for architecture decisions.
2. **Every component is independently testable.** Each package has a comprehensive test suite. Mock the LLM calls, test the logic.
3. **Deterministic where possible.** Eval harness uses replay with seeded randomness to ensure reproducible results.
4. **Observability is a first-class concern.** Every span, every metric, every log is instrumented from day one.
5. **Model-agnostic.** Swap Ollama → OpenAI → vLLM → Anthropic with a config change. The abstraction layer makes this seamless.

## Success Metrics

- 9+ Python packages published to PyPI (or installable from source)
- 1 TypeScript CLI tool published to npm
- 1 React dashboard deployable standalone
- 1 showcase app (Autonomous Technical Researcher) running on GCP
- 20+ blog posts documenting architecture decisions and implementation details
- CI pipeline with lint, typecheck, test, eval, build, deploy stages
- Full evaluation suite with benchmarks

## Blog Content Roadmap

| Phase | Posts |
|-------|-------|
| Foundations | "Building an Agent Loop from Scratch", "Type-Safe Tool Calling Without Frameworks", "Memory Systems for Agents: A Deep Dive", "Context Management: The Hidden Complexity of Agent Systems" |
| Eval | "Testing Non-Deterministic Systems: An Evaluation Harness for Agents", "LLM-as-Judge: When, Why, and How", "Trajectory Analysis: Debugging Agent Behavior" |
| RAG | "Hybrid Search from Scratch: BM25 + Dense Vectors", "Chunking Strategies: A Systematic Comparison", "RAG Evaluation Methodology: Beyond Naive Metrics" |
| Index | "Building a Vector Index Abstraction Layer", "HNSW from Scratch: Implementation and Optimization", "Quantization for Vector Search: Accuracy vs Speed Tradeoffs" |
| Orchestration | "Workflow Engines for Multi-Agent Systems", "Human-in-the-Loop Patterns in Practice", "Compensation Sagas: Handling Failures in Agent Workflows" |
| Agents | "Multi-Agent Communication Protocols: Design and Implementation", "Specialized Agents: Researcher, Coder, Reviewer, Planner" |
| Production | "Observability for Agentic Systems with OpenTelemetry", "Deploying Local-First AI to Cloud: A Practical Guide", "Building an Autonomous Technical Researcher End-to-End" |

## Getting Started

```bash
# Clone and install
git clone https://github.com/Manas-thakur/agentcore.git
cd agentcore
make install  # or: uv sync && pnpm install

# Run the calculator agent demo
agentcore run examples/calculator_agent.py

# Start the dashboard
agentcore serve --dashboard

# Run the eval suite
agentcore eval --suite basic
```
