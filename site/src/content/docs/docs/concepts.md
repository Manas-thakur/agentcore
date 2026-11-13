---
title: How it fits together
description: The AgentCore architecture, from the runtime loop to tools, evals, retrieval, graphs, multi-agent teams and observability.
---

AgentCore is a set of independent modules that compose. Each one is usable on its own and
tested on its own; together they form an agent platform.

```text
                ┌──────────────────────── agentcore serve ────────────────────────┐
                │  web app (Playground, Traces, Evals, Overview, Tools, Settings) │
                │  HTTP API · SSE chat · OpenAI-compatible /v1/chat/completions   │
                └─────────────────────────────────────────────────────────────────┘
                                 │ runs agents, reads traces + eval history
  runtime ──► tools ──► eval ──► rag / index ──► graph ──► agents ──► obs
  (ReAct loop)  (@tool,   (suites,  (hybrid search,  (state graphs,  (teams over   (spans, metrics,
                 schema,   replay,   vector indexes)  HITL, saga)     an A2A bus)   logs, cost)
                 sandbox)  judge)
```

## The runtime loop

An [`Agent`](/agentcore/docs/modules/runtime/) holds a **model client**, a **tool registry**, an
optional **memory** and a config (max steps, timeout, stuck detection, reflection). `run()` is a
ReAct loop:

1. Build the message list: system prompt, memory, the task.
2. Call the model with the tool schemas (native tool calling).
3. If the model asked for tools, execute them (in parallel by default), append the results and go
   back to 2.
4. If it answered, stop with `stop_reason="final"`; otherwise stop on `max_steps`, `timeout` or
   `error`. When the model repeats the same tool call (stuck detection) it gets a nudge to change
   course, and `reflect_every=N` adds periodic self-reflection.

Every step emits events (`run_start`, `step_start`, `token`, `model_response`, `tool_start`,
`tool_end`, `reflection`, `final`, `error`, `run_end`). The CLI prints them, the web app streams them over
Server-Sent Events, and the tracer turns them into spans.

## Models are strings

`create_model(spec)` turns a string into a client: `mock`, `auto`, `ollama:<model>`,
`openai:<model>` (and the `vllm:`, `lmstudio:`, `groq:` aliases for OpenAI-compatible servers).
`auto` uses Ollama when it is reachable and the model is pulled, and falls back to `mock`. The
same string works in Python, on the CLI (`--model`), in `agentcore.toml`, in eval suites and in
the web app's model picker.

## Tools are typed functions

[`@tool`](/agentcore/docs/modules/tools/) inspects a function's signature and docstring and produces
a JSON Schema (including dataclasses, `Literal`, `Enum`, `Optional`, `TypedDict` and pydantic
models). The execution engine validates and coerces arguments, applies timeouts, retries and rate
limits, and returns a `ToolResult` instead of raising, so the model sees the error and can recover.

## Evals make agents testable

A [suite](/agentcore/docs/modules/eval/) is YAML: cases with an input and what to expect (output,
tool calls, trajectory, step budget, rubric). The runner builds a fresh agent per case, records the
trajectory, scores every metric and can **record model responses to a cassette and replay them**,
so a suite that needed a real model runs deterministically in CI. Reports compare against a
baseline to flag regressions.

## Retrieval and indexes

[RAG](/agentcore/docs/modules/rag/) loads and chunks documents, searches with BM25 and a vector index
at the same time, fuses the rankings (reciprocal rank fusion), reranks, and generates an answer with
citations that are checked against the retrieved text. The vector indexes in
[`agentcore.index`](/agentcore/docs/modules/indexes/) (Flat, HNSW, IVF, SQ8, PQ) are implemented with
numpy and can be saved and loaded.

## Graphs and teams

[Workflow graphs](/agentcore/docs/modules/graph/) run nodes (plain functions or agents) with static
and conditional edges, parallel fan-out and joins, reducers, retries, fallbacks, checkpoints,
`interrupt()` for human approval and compensation for rollback. [Multi-agent](/agentcore/docs/modules/agents/)
patterns (manager-worker, pipeline, peer review) coordinate specialist agents over an in-process
message bus.

## Everything is traced

[Observability](/agentcore/docs/modules/obs/) is built in: agent runs, steps, model calls (tokens,
cost, latency, and the size-bounded prompt and response), tool calls, graph nodes and A2A messages
are spans with a shared trace id. Spans go to JSONL files (one per trace) and, optionally, to
OpenTelemetry. The web app reads the same files: nothing else needs to be running.

## Where state lives

| What | Where (defaults) |
|---|---|
| Traces | `.agentcore/traces/<trace_id>.jsonl` (`trace_dir`) |
| Chat sessions (web app / API) | `.agentcore/sessions/<id>.json` (`data_dir`, default: parent of the trace dir) |
| Eval run history and baselines | `.agentcore/evals/<suite>/runs/*.json`, `.../baseline.json` |
| Eval suites | `evals/`, `examples/evals/` (`eval_dirs`) |
| Project settings | `agentcore.toml` + `AGENTCORE_*` environment variables |
