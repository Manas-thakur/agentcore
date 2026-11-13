---
title: HTTP API
description: Every endpoint served by agentcore serve, including the SSE chat protocol and the OpenAI-compatible chat completions endpoint.
---

`agentcore serve` exposes these routes (defined in `src/agentcore/server/app.py`). Interactive
OpenAPI docs are at `GET /docs`. When `AGENTCORE_API_KEY` is set, every route below except
`/health` requires `Authorization: Bearer <key>` or `X-API-Key: <key>`
([Deployment](/agentcore/docs/deployment/#api-key)). Errors use FastAPI's `{"detail": "..."}` shape,
except the OpenAI-compatible endpoint, which uses OpenAI's `{"error": {...}}` shape.

## Overview

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness, version, default model, enabled tools, whether auth is on (always public) |
| `GET /v1/models` | OpenAI-style model list |
| `POST /v1/agent` | Run the agent once |
| `POST /v1/chat/completions` | OpenAI-compatible chat completions (`stream: true` supported) |
| `POST /api/chat` | Streaming chat turn (Server-Sent Events) with server-side sessions |
| `GET /api/sessions`, `POST /api/sessions` | List / create sessions |
| `GET /api/sessions/{id}`, `DELETE /api/sessions/{id}` | Transcript + memory / delete |
| `POST /api/sessions/{id}/stop` | Cancel the session's running turn |
| `GET /api/traces` | Trace summaries (filters, query language, sort, paging) |
| `GET /api/traces/explore` | Rows, facet counts, histogram and percentiles in one call |
| `GET /api/traces/facets` | Filter values with per-value counts |
| `GET /api/traces/{id}` | Summary + spans (id or unique prefix) |
| `GET /api/traces/{id}/export` | Trace as a JSON download |
| `GET /api/overview` | KPIs, previous-period KPIs, time series, top tools, models, recent failures |
| `GET /api/tools`, `POST /api/tools/{name}/invoke` | Enabled tools with schemas / invoke one |
| `GET /api/evals/suites` | Suites discovered in the eval directories |
| `POST /api/evals/starter` | Create `starter.yaml` in the first eval directory |
| `POST /api/evals/runs`, `GET /api/evals/runs` | Start a background run / run history |
| `GET /api/evals/runs/{id}` | Progress, results and the diff against the baseline |
| `POST /api/evals/runs/{id}/baseline` | Make a completed run the suite's baseline |
| `GET /api/evals/matrix` | Cases x recent runs with regression flags |
| `GET /api/config` | Effective configuration (never includes secrets) |
| `GET /metrics` | Prometheus text format |
| `GET /docs`, `GET /openapi.json` | OpenAPI UI and schema |
| `GET /`, `GET /{playground,traces,evals,overview,tools,settings}[/...]` | The web app shell; `/static/*` its assets |

## `GET /health`

```json
{"status": "ok", "version": "0.3.0", "model": "mock", "tools": ["calculator", "current_time"], "auth": false}
```

## `GET /v1/models`

The server default, `models` from `agentcore.toml`, `mock`, and the models a local Ollama has
pulled (checked at most every 30 s):

```json
{"object": "list", "data": [{"id": "mock", "object": "model", "created": 1794560000, "owned_by": "agentcore", "default": true}]}
```

## `POST /v1/agent`

Run the agent once. Body (JSON):

| Field | Type | Default |
|---|---|---|
| `input` | string | - (or `messages`) |
| `messages` | `[{role, content}]` | - |
| `model` | model spec | server default |
| `tools` | subset of the enabled tools | all enabled |
| `system_prompt` | string | config / built-in |
| `max_steps` | 1-50 | 8 |
| `session_id` | string; continue a server-side session (needs `input`) | none |

```bash
curl -s -X POST http://127.0.0.1:8000/v1/agent -H "Content-Type: application/json" \
     -d '{"input": "What is 2 ** 10?"}'
```

Response: `id`, `object: "agent.run"`, `created`, `model`, `output`, `stop_reason`, `steps`,
`usage`, `tool_calls` (`name`, `arguments`, `success`, `output`, `error`, `latency_ms`), `trace_id`,
`session_id`, `duration_ms`. Errors: `400` (no input, unknown tool or model), `409` (the session is
already running a turn), `502` (the agent failed).

## `POST /v1/chat/completions`

OpenAI-compatible. `model` is `agentcore` (or `default`, or empty) for the server default, or a spec
such as `mock` or `ollama:<model>`; unknown specs return `404 model_not_found`. Messages accept
`system`, `developer` (treated as system), `user`, `assistant` (with `tool_calls`) and `tool` roles,
and string or text-part content. `temperature`, `max_tokens` / `max_completion_tokens` are passed
to the model. The agent runs with the server's enabled tools (up to 8 steps).

Compatibility notes:

- `n` must be `1` (or omitted); `n > 1` returns `400` with `param: "n"`.
- `tools`, `tool_choice` (and other OpenAI fields such as `user`) are accepted and **ignored**:
  the agent calls the server's own tools itself and returns the final answer, so the response never
  contains `tool_calls` for the client to execute.

Errors use OpenAI's shape, `{"error": {"message", "type", "param", "code"}}`:

| Status | `type` | When |
|---|---|---|
| `400` | `invalid_request_error` | Body does not match the schema (`param` names the field, e.g. `messages` or `messages.0.content`), an unknown role (`param: "messages.N.role"`), no user message, `n > 1` |
| `404` | `invalid_request_error` (`code: model_not_found`) | Unknown model spec |
| `502` | `server_error` | The model failed (server down, HTTP error); `message` has the upstream error as text |

When streaming, a failure after the stream started is sent as one `data: {"error": {...}}` event
(`type: "server_error"`) followed by `data: [DONE]`.

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions -H "Content-Type: application/json" \
     -d '{"model": "agentcore", "messages": [{"role": "user", "content": "What is 2 ** 10?"}]}'
```

The response is a standard `chat.completion` plus an `agentcore` object with `trace_id`, `steps`,
`stop_reason` and the agent's `tool_calls`. With `"stream": true` it streams `chat.completion.chunk`
events (`data: {...}`) and ends with `data: [DONE]`; `"stream_options": {"include_usage": true}`
adds a final chunk with `usage`.

## `POST /api/chat` (Server-Sent Events)

One chat turn, streamed. Body: `message` (required), and optional `session_id`, `model`, `tools`,
`system_prompt`, `max_steps` (1-50, default 8). Without a `session_id` a new session is created.

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" \
     -d '{"message": "What is 17 * 23 + 4?"}'
```

Each event is `event: <name>` + `data: <json>`:

| Event | Data |
|---|---|
| `session` | `session_id`, `title`, `model`, `context` (`tools`, `system_prompt`: `default`/`custom`, `memory_messages`) |
| `run_start` | `step`, `trace_id` |
| `step_start` | `step` |
| `token` | `step`, `content` (a streamed piece of text) |
| `model_response` | `step`, `content`, `tool_calls`, `usage`, `latency_ms` |
| `tool_start` | `step`, `id`, `name`, `arguments` |
| `tool_end` | `step`, `id`, `name`, `success`, `output`, `error`, `latency_ms` |
| `reflection` | `step`, `content` |
| `final` | `step`, `output` |
| `run_end` | `step`, `stop_reason` (`final`, `max_steps`, `timeout`), `usage`, `duration_ms` (the agent loop finished; `done` follows) |
| `done` | `session_id`, `trace_id`, `output`, `stop_reason`, `steps`, `usage`, `cost_usd`, `duration_ms` |
| `stopped` | `trace_id` (the turn was cancelled) |
| `error` | `message`, `trace_id` (the turn failed, e.g. the model is unreachable) |

When the run fails, the agent first reports the failure as an `error` event with `step` and
`error`, then the stream ends with the `error` event above (`message`, `trace_id`). Every stream
ends with exactly one of `done`, `stopped` or that final `error`. A second turn on a busy session
returns `409`. If the client disconnects, the agent run is cancelled.

## Sessions

- `GET /api/sessions` lists `{id, title, created, updated, turns, busy}`, newest first.
- `POST /api/sessions` (optional `{"title": "..."}`) creates one (`201`).
- `GET /api/sessions/{id}` adds `settings`, `messages` (the transcript, including each assistant
  turn's `parts`: text, model calls, tool calls, notes) and `memory`.
- `DELETE /api/sessions/{id}` deletes it; `POST /api/sessions/{id}/stop` cancels the running turn
  (`{"stopped": true|false}`).

Sessions are kept in memory and mirrored to `<state_dir>/sessions/<id>.json`.

## Traces

`GET /api/traces` returns a JSON array of trace summaries (`trace_id`, `name`, `start_time`,
`duration_ms`, `span_count`, `status`, `total_tokens`, `cost_usd`, `model`, `input`, `output`,
`tool_calls`, `tool_errors`, `error`, `tools`, `attributes`) with the total in `X-Total-Count`.

| Query parameter | Meaning |
|---|---|
| `query` | [Trace query language](/agentcore/docs/reference/query-language/) |
| `q` | Free-text search (id, name, model, input, output, error) |
| `status`, `model` | Exact filters |
| `kind` | `agent` or `eval` |
| `since`, `until` | Epoch seconds or ISO 8601 |
| `sort` | `time` (default), `latency`, `tokens`, `cost`, `name`, `status`, `model` |
| `order` | `desc` (default) or `asc` |
| `limit`, `offset` | Paging (1-1000, default 50) |

`GET /api/traces/explore` takes `query`, `since`, `until`, `sort`, `order`, `limit` (default 100),
`offset` and `buckets` (4-200, default 48) and returns `items` (with a `kind` field), `total`,
`facets` (per-value counts for `status`, `kind`, `model`, `tool`, `name`), `histogram`
(`start`, `end`, `bucket_seconds`, `buckets: [{t, count, errors}]`), `stats` (`count`, `errors`,
`p50_ms`, `p95_ms`, `p90_cost_usd`, `p90_tokens`) and the parsed `query`. An invalid query returns
`400` with `{"detail", "position", "type": "query_error"}`.

`total`, `histogram` and `stats` all describe the traces that match `query` inside the time
window (`since`/`until`); with `query=status:error`, `stats.count` is the number of failed
traces. `facets` count over the window with the query applied to the other fields, so the facet
panel still shows the values you could switch to.

`GET /api/traces/facets?query=` returns `count`, `models`, `names` and `facets`.
`GET /api/traces/{id}` returns `{trace_id, summary, spans}`; `GET /api/traces/{id}/export`
returns the same as a file download. Both accept a unique id prefix; `404` when nothing matches.

## `GET /api/overview`

Parameters: `days` (default 7, up to 365) and `tz` (the browser's `getTimezoneOffset()` in minutes,
so daily buckets start at local midnight). Returns `range`, `kpis` (`runs`, `errors`,
`success_rate`, `p50_ms`, `p95_ms`, `tokens`, `cost_usd`, `tool_calls`), `previous` (the same KPIs
for the preceding period, or `null`), `series` (hourly for up to 2 days, daily otherwise),
`top_tools` (with `error_rate` and `avg_ms`), `models` and `recent_errors`.

## Tools

`GET /api/tools` lists the enabled tools: `name`, `description`, `parameters` (JSON Schema),
`category`, `timeout`, `source` (`builtin` or `custom`).

`POST /api/tools/{name}/invoke` with `{"arguments": {...}}` runs one tool (traced as `tool.invoke`)
and returns `success`, `output`, `error`, `error_type`, `latency_ms`, `attempts`, `text` and
`trace_id`. Unknown tools return `404`.

## Evals

- `GET /api/evals/suites`: `path`, `dir`, `name`, `description`, `cases`, `tools`, `model`, `tags`,
  `case_names`, `last_run`, `baseline`; unreadable or invalid files are listed with an `error`
  (the validation message). Suites that share a `name` with another file have
  `duplicate_name: true`.
- `POST /api/evals/starter`: writes `starter.yaml` into the first eval directory (`201`), `409` if
  it exists, `500` with a `detail` such as `cannot write to evals: permission denied; set
  eval_dirs in agentcore.toml (or AGENTCORE_EVAL_DIRS) to a writable folder` when the directory
  is not writable.
- `POST /api/evals/runs` with `{"suite": "<path or name>", "model": null, "tags": null}` starts a
  background run and returns it (`202`); `404` for an unknown suite, `409` when several files use
  that suite name (run one by `path`), `400` for an invalid suite.
- `GET /api/evals/runs?suite=&limit=` lists running and finished runs (newest first) with
  `is_baseline`.
- `GET /api/evals/runs/{id}` returns `status` (`queued`, `running`, `completed`, `failed`) and the
  progress as top-level fields: `done`, `total`, `passed` (cases finished / in the suite / passed
  so far), `started_at`, `finished_at` and `elapsed_s` (seconds so far while running; the total
  run time once finished). Also `summary`, per-case `results` (metrics, trajectory, `trace_id`),
  and `baseline` + `diff` when the suite has a baseline.
- `POST /api/evals/runs/{id}/baseline` marks a completed run as the baseline.
- `GET /api/evals/matrix?suite=&limit=8` returns `runs` (oldest first), `cases` with one cell per
  run (`passed`, `score`, `failing` metrics, `regressed`, `baseline_regressed`), `baseline` and the
  number of `regressions`.

## `GET /api/config`

The effective configuration: `config_file`, `model`, `models`, `tools`, `tool_modules`,
`trace_dir`, `state_dir`, `workspace`, `eval_dirs`, `server` (`host`, `port`,
`auth_enabled`, `cors_origins`, `max_body_bytes`), plus `version`, `python`, `default_model`,
`enabled_tools` and `custom_tools` (tools defined in your `tool_modules`; built-ins they re-export,
such as `calculator`, are not listed). `server.host` and `server.port` are the address actually
being served (`agentcore serve --port 9000` reports `9000`). Never includes the API key.

## Limits and errors

- `401` `invalid_api_key` when a key is required and missing or wrong.
- `413` `request_too_large` above `max_body_kb` (default 1024 KB).
- `422` for bodies that do not match the schema (FastAPI validation), except on
  `/v1/chat/completions`, which answers `400` in OpenAI's error shape.
