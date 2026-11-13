# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- **Web app UI/UX rebuild** (still no build step; patterns and rationale in
  `docs/design/references.md`):
  - *Traces* is now an explorer: query bar with a small query language and autocomplete, facet
    sidebar with per-value counts, volume histogram with drag-to-zoom, quick filters (Errors,
    Slow > p95, Expensive), dense sortable table, and a resizable side peek with metadata pills,
    a nested span tree with latency bars and Preview / Attributes / JSON tabs. `j`/`k`/`Enter`/`Esc`
    keyboard navigation; filters, sort, time range and the open trace live in the URL.
  - *Playground*: each reply starts with a collapsible run summary that expands into a step
    timeline (model calls, tool calls with arguments and results, "added to context" chips);
    run settings move to a collapsible right panel with switches and a max-steps slider.
  - *Evals*: results matrix (cases x recent runs) with regressions outlined and a case side peek
    showing metrics, trajectory and the case across runs.
  - *Overview*: KPI cards with sparklines and deltas vs the previous period; tool error rates.
  - *Shell*: sectioned sidebar, `Ctrl/Cmd+K` command palette, `?` shortcut help, `g`-prefixed
    navigation, calmer visual system, 375 px layouts with sheets for filters and peeks.

### Added

- `GET /api/traces/explore` (rows, facet counts, histogram, percentiles in one call), a `query`
  parameter plus `sort`/`order` on `GET /api/traces`, per-value counts in `/api/traces/facets`,
  `GET /api/evals/matrix`, `previous` period KPIs and tool `error_rate` in `/api/overview`.
- Chat traces carry `session.id`; chat turns record per-step model parts and the context given to
  the model; eval case results include the agent `trace_id`.

## [0.2.0] - 2026-11-13

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

## [0.1.0] - 2026-11-12

### Added

- First release: ReAct runtime, tool framework with sandbox, evaluation harness with replay and
  regression checks, RAG with hybrid search, from-scratch vector indexes, workflow graphs,
  multi-agent patterns, observability, CLI, FastAPI server with a trace dashboard.

[0.2.0]: https://github.com/Manas-thakur/agentcore/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Manas-thakur/agentcore/releases/tag/v0.1.0
