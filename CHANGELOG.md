# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **Install hints no longer point at PyPI.** The `agentcore` package on PyPI is a different
  project. The CLI, `agentcore doctor`, the server's missing-extra error, generated project READMEs
  and the docs now give `pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"`
  (pin with `@v0.3.0`) and say the PyPI name is taken.
- **Docker: creating the starter eval suite failed with a 500.** The server runs as uid 1000 but
  its working directory was root-owned `/app`. The image now runs from `/data` (owned by the app
  user; example suites in `/data/examples/evals`), and an unwritable eval directory returns a clear
  error (`cannot write to evals: permission denied; set eval_dirs ...`) instead of a traceback.
- **Docker: `AGENTCORE_MODEL=auto` in the image overrode `model` in a mounted `agentcore.toml`.**
  The image no longer sets it; the default is still `auto`. The deployment docs explain the Git
  Bash path conversion (`MSYS_NO_PATHCONV=1`, `$(pwd -W)`).
- **`agentcore eval --baseline missing.json` silently skipped the regression gate.** A missing
  baseline is now an error (exit 2); create it with `--save-baseline`.
- **Eval suites are validated strictly.** Unknown keys (with "did you mean" hints), cases without
  `name` or `input`, invalid `match` values (`fuzzy`; `Contains` is accepted as `contains`),
  malformed tool-call expectations (`{tol: calculator}` used to crash with `KeyError`), invalid
  regexes, rubrics and YAML are reported with the case and the allowed keys. A case with no checks
  now fails with a `no_checks` metric instead of passing with score 1.0.
- **The CLI prints one-line errors instead of tracebacks** for ordinary mistakes: bad model specs
  (`bogus:x`, `openai:`), an unreachable or failing model server, missing suite / cassette /
  `--docs` paths, invalid YAML, malformed suites, unknown tools or missing tool modules in
  `agentcore.toml`. They exit 2; `--debug` (or `AGENTCORE_DEBUG=1`) shows the traceback.
- **Graph: `timeout=` was ignored for sync nodes and sync fan-out ran serially.** Sync nodes now
  run in worker threads, so timeouts apply and fan-out branches run concurrently. A timed-out node
  reports `TimeoutError: node 'x' timed out after 0.5s` (it was an empty `TimeoutError: `).
- Graph: a conditional edge can map a key to a list of nodes (fan-out), and a router result that
  is not in `path_map` fails the run with a clear error instead of raising `KeyError`.
- `Agent.run()` no longer raises on model errors: the result has `stop_reason="error"` and
  `error` set, as documented. `raise_on_error=True` restores raising (the server uses it).
- Eval rubrics accept the list form `[{criterion, weight}]` (it crashed) and plain criterion
  lists. `--judge-model` judges only cases that define a rubric (new `--judge-all` judges every
  case); the mock model answers judge prompts with valid JSON.
- `agentcore eval --concurrency 0` hung; values below 1 are rejected. `--fail-under` is checked
  to be a pass rate between 0 and 1, and the docs now describe the exit codes precisely.
- `ExecutionEngine(before=..., after=...)` accepts a single callable as well as a list.
- `@tool(retries=0)` was treated as "use the engine default" (2 retries); it now disables retries.
  The default is `retries=None` (engine default).
- `python_exec` returned `success=True` with `TIMEOUT` text when code ran too long; it is now a
  failed call (`ToolTimeoutError`) and is not retried. The built-in `python_exec` blocks imports of
  `os`, `subprocess`, `socket`, `shutil`, `ctypes` and similar modules by default (configurable
  with `SandboxConfig(blocked_imports=...)`); the docs explain the Windows sandbox limitations.
- RAG: `RAGPipeline().answer()` without a model returns an extractive, cited answer instead of
  raising. Markdown front matter is stripped and its `title` used as the source title; `.mdx`
  files are ingested (imports, exports and JSX removed, alt text kept). Sources use forward slashes.
- Indexes: search filters can be dicts (`{"lang": "en"}`, `{"lang": ["en", "de"]}`) as well as
  callables; a repeated id inside one `add()` call now upserts (last wins) in every index type.
- A `SpecializedAgent` subclass can set `system_prompt` to a string. `Pipeline` stops at the first
  failing member and reports it in `TeamResult.error` instead of returning empty output.
- `/v1/chat/completions`: errors use OpenAI's shape with `param` (validation errors are `400`, not
  FastAPI's `422`), unknown roles and `n > 1` are rejected, model failures are `502` with type
  `server_error`, and streamed errors carry the upstream message as text (not `b'...'`).
  `tools` / `tool_choice` are accepted and ignored (documented).
- `/api/config` reports the port actually served (`agentcore serve --port N`) and lists only
  tools defined in your tool modules as custom.
- Unknown keys under `[server]` in `agentcore.toml` (e.g. `prot`) are errors; `port` and
  `max_body_kb` are range-checked.
- Two suite files with the same `name` are flagged (`duplicate_name`) and running by that name
  returns 409 listing the files; the unknown-suite 404 no longer shows server paths.
- Observability: with an OpenTelemetry SDK configured, AgentCore root spans use the OTel trace id
  (and every span records `agentcore.trace_id`); eval runs are counted under `agent="eval"` instead
  of one metrics series per case; `doctor` checks for the OTel SDK, not just the API;
  `agentcore eval` writes traces (`kind:eval`) like web eval runs (`--no-trace` to skip).
- Mock model: a lookup miss reads `I could not find an answer with lookup_fact: No matching fact
  found.` (it was `The answer is No matching fact found..`), and `reflect_every=1` no longer turns
  answers into refusals.
- Smaller fixes: `traces list --limit 0` is rejected with a clear message; the starter suite says
  "web app", not "dashboard"; `current_time` and `make_python_exec` are exported from
  `agentcore.tools`; `chat -v --stream` prints the `[final ...]` summary on its own line;
  `agentcore eval --markdown` prints the report path.

### Docs

- HTTP API: the `run_end` SSE event, eval run progress fields (`elapsed_s` is now also set after a
  run finishes), OpenAI-compatible error shapes and ignored fields, starter-suite and
  duplicate-name errors. The trace explorer's `stats` now follow the query (they covered the whole
  time window) and the docs say so.
- Graph `interrupts` (all pending) vs `interrupt` (the first one); eval case names, rubric formats
  and judge scope; tool hook signatures; index filter signature.

## [0.3.0] - 2026-11-13

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

[Unreleased]: https://github.com/Manas-thakur/agentcore/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Manas-thakur/agentcore/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Manas-thakur/agentcore/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Manas-thakur/agentcore/releases/tag/v0.1.0
