---
title: Changelog
description: Every notable change to AgentCore, by version.
---

This page mirrors [`CHANGELOG.md`](https://github.com/Manas-thakur/agentcore/blob/main/CHANGELOG.md) in the repository.

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## 0.3.0 (2026-11-13)

### Changed

- **The web app is rebuilt on a component kit**: Vite + React 19 + TypeScript + Tailwind CSS v4 +
  shadcn/ui (Radix primitives), with the agent patterns from shadcn's AI Elements (Message,
  Chat with Message Scroller, Prompt Input, Tool, Task, Chain of Thought, Reasoning, Queue,
  Confirmation, Context, Model Selector, Code Block, Stack Trace, Test Results, Subagent).
  Sources live in `web/`; `pnpm --dir web build` writes the bundle into
  `src/agentcore/server/static/`, which is committed so `pip install` still needs no Node.js.
  Fonts (Geist, Geist Mono) are self-hosted; no CDN scripts or remote fonts. Every capability of
  the previous UI is kept:
  - *Playground*: streaming chat with server-side sessions, a run summary that expands into a step
    timeline (context, model calls, reasoning, tool calls with arguments and results, errors with
    stack frames), run settings (model picker with `/v1/models` + free text, tool switches, max
    steps, system prompt), Stop, View trace, a context meter, the mock-model notice and example
    prompts.
  - *Traces*: query bar with autocomplete and pills, facet sidebar with counts, histogram with
    drag-to-zoom, quick filters, a dense server-sorted table (TanStack Table), a resizable side
    peek with the span tree and Preview / Attributes / JSON tabs (nested subagent runs shown in
    the preview), `j`/`k` navigation and URL state.
  - *Evals*: suites, background runs with progress and a queue of cases, results matrix with
    regressions and the case peek, run history, baselines, the starter-suite button.
  - *Overview*: KPI cards with sparklines and deltas, shadcn charts (Recharts) for runs, latency,
    tokens and cost, top tools with error rates, models, recent failures.
  - *Tools*: schema + generated try-it form; tools that run code, write files or use the network
    ask for confirmation first. *Settings*, the API-key prompt, `Ctrl/Cmd+K` command palette,
    shortcuts help, light/dark, and sheets at phone width.
- The app uses real paths (`/traces/<id>?query=...`, `/playground/<session>`) instead of hash
  routes; the server returns the app shell for these paths (an SPA fallback limited to the app's
  routes) and old `#/...` links are redirected. With an API key set, these shell routes stay
  public like `/` (they contain no data); every API route still needs the key.
- Hashed build assets are served with `Cache-Control: immutable`; the shell is revalidated.
- `agentcore serve --help` describes the web app instead of the old dashboard.

### Added

- `GET /api/traces/explore` (rows, facet counts, histogram, percentiles in one call), a `query`
  parameter plus `sort`/`order` on `GET /api/traces`, per-value counts in `/api/traces/facets`,
  `GET /api/evals/matrix`, `previous` period KPIs and tool `error_rate` in `/api/overview`.
- Chat traces carry `session.id`; chat turns record per-step model parts and the context given to
  the model; eval case results include the agent `trace_id`.
- Documentation site and landing page (Astro + Starlight) in `site/`, published to
  <https://manas-thakur.github.io/agentcore/> by `.github/workflows/pages.yml`.
- CI: a `web` job (install with the frozen lockfile, typecheck, ESLint, Vitest, build, and a check
  that the committed build is up to date); the release workflow builds the web app before the
  Python distributions.
- `CONTRIBUTING.md`.

## 0.2.0 (2026-11-13)

### Added

- **Web app** served by `agentcore serve` (plain HTML/CSS/ES modules, no build step) with sidebar
  navigation, light/dark themes (system default + toggle) and phone-width layouts:
  - *Playground*: multi-turn chat streamed over Server-Sent Events, server-side sessions with
    memory, inline tool-call cards (arguments, result, duration, errors), model picker, tool
    toggles, system prompt, max steps, Stop button, per-answer trace links, sanitized Markdown.
  - *Traces*: search and filters (status, model, kind, date range), span waterfall with nested
    duration bars, span attributes, model inputs/outputs, tokens and cost, JSON export.
  - *Evals*: suite discovery in configurable directories, background runs with progress polling,
    per-case scores and metric breakdowns, run history, baselines and regression highlighting.
  - *Overview*: runs, success rate, p50/p95 latency, tokens and cost over 24 h / 7 d / 30 d with
    charts, top tools by calls and errors, models, recent failures.
  - *Tools*: JSON Schema view and a generated "try it" form to invoke any enabled tool.
  - *Settings*: theme, browser-stored API key, effective server configuration.
- **API**: `POST /api/chat` (SSE), session endpoints (`/api/sessions...`, including stop),
  OpenAI-compatible `POST /v1/chat/completions` with streaming and `stream_options.include_usage`,
  trace filters/facets/export, `/api/overview`, `/api/tools` + invoke, eval job endpoints
  (`/api/evals/...`), `/api/config`; `/v1/agent` accepts `session_id`.
- **Server hardening**: optional API key (`AGENTCORE_API_KEY`, bearer or `X-API-Key`; the UI
  prompts once), configurable CORS (off by default), request body size limit (413).
- **CLI**: `agentcore init` scaffolds a project that runs offline with `--model mock`;
  `agentcore doctor` checks the environment, config and model reachability (`--ping`);
  global `--config`; `serve --cors-origins`.
- **Configuration file** `agentcore.toml` (default model, model list, tools, custom tool modules,
  trace/state/eval directories, server settings) with env-var and CLI overrides.
- **Custom tools** from `tool_modules` are available to `chat`, `eval`, `serve` and `tools`.
- Model spans record size-bounded prompt messages and the response (`trace_content=False` to
  disable); trace summaries include model, input/output previews and per-tool stats.
- `EvalRunner(on_result=...)` progress callback and `tools=` for custom tools;
  `EvalDiff.to_dict()`.
- `MockModel` streams word by word (optional `stream_delay`).
- Release workflow: sdist + wheel, GitHub Release with artifacts, multi-arch Docker image on
  `ghcr.io/manas-thakur/agentcore`, PyPI trusted publishing gated behind `PYPI_PUBLISH`.
- Tests for every new endpoint and CLI command; README screenshots.

### Changed

- The single-file trace dashboard (`server/static/dashboard.html`) is replaced by the web app;
  `dashboard_html()` now returns the app shell.
- `create_app()` takes keyword options for config, auth, CORS, body limits, eval/state dirs and
  extra tools; positional arguments are unchanged.
- `serve`, `chat`, `traces` and `research` read defaults from `agentcore.toml` when present.
- Development status classifier raised to Beta; `tomli` is required on Python 3.10.

## 0.1.0 (2026-11-12)

### Added

- First release: ReAct runtime, tool framework with sandbox, evaluation harness with replay and
  regression checks, RAG with hybrid search, from-scratch vector indexes, workflow graphs,
  multi-agent patterns, observability, CLI, FastAPI server with a trace dashboard.
