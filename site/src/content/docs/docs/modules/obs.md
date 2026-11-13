---
title: Observability
description: Spans with an async-safe tracer, a JSONL trace store, optional OpenTelemetry mirroring, Prometheus-style metrics, JSON logs and cost tracking.
---

`agentcore.obs` makes every run inspectable. Agents, model calls, tool calls, graph nodes and A2A
messages emit **spans** that share a trace id; counters and histograms feed **metrics**; a
**cost tracker** prices token usage. The web app reads the same trace files.

```python
from agentcore import Agent, create_model
from agentcore.obs import CostTracker, JSONLTraceStore, configure_tracing, get_metrics, render_tree
from agentcore.tools import calculator

configure_tracing(".agentcore/traces")  # JSONL spans; use_otel=True mirrors to OpenTelemetry
costs = CostTracker()
agent = Agent(create_model("mock"), tools=[calculator], cost_tracker=costs)
result = agent.run_sync("What is 6 * 7?")

store = JSONLTraceStore(".agentcore/traces")
print(render_tree(store.load(result.trace_id)))
print(costs.summary())
print(get_metrics().export_prometheus())
```

```text
- agent.run:agent [16.9 ms] agent.name=agent model=mock tokens.total=168
  - agent.step [15.7 ms] step=1
    - model.generate [0.1 ms] model=mock step=1 tokens.total=74 cost.usd=0.0
    - tool.execute [5.2 ms] tool.name=calculator
  - agent.step [0.5 ms] step=2
    - model.generate [0.1 ms] model=mock step=2 tokens.total=94 cost.usd=0.0
{'total_usd': 0.0, 'total_tokens': 168, 'calls': 2, 'by_model': {'mock': 0.0}, 'by_agent': {'agent': 0.0}}
# TYPE agentcore_agent_runs_total counter
agentcore_agent_runs_total{agent="agent"} 1.0
# TYPE agentcore_model_calls_total counter
agentcore_model_calls_total{model="mock"} 2.0
...
```

## Spans

| Span | Attributes (selection) |
|---|---|
| `agent.run:<name>` | `agent.name`, `task`, `model`, `steps`, `stop_reason`, `tokens.total`, `output`, `session.id` (web chats) |
| `agent.step` | `step` |
| `model.generate` | `model`, `tokens.prompt`, `tokens.completion`, `tokens.total`, `cost.usd`, `latency.ms`, `tool_calls`, `input.messages`, `output.content`, `output.tool_calls` |
| `tool.execute` | `tool.name`, `tool.arguments`, `tool.success`, `tool.output`, `latency.ms` |
| `tool.invoke` | Tool calls made directly from the web app's Tools page |
| `graph.run:<name>` / `graph.node:<node>` | Workflow graph runs and nodes |
| `a2a.deliver` | Messages on the multi-agent bus |

The tracer uses context variables, so concurrent async runs keep their own trace. Model spans
record the size-bounded prompt and response; pass `trace_content=False` to an `Agent` to turn that
off.

## Storage

`configure_tracing(trace_dir=".agentcore/traces", *, console=False, use_otel=False,
extra_exporters=None)` installs the global tracer. The `JSONLTraceStore` writes one file per trace
(`<trace_id>.jsonl`, one span per line) and summarizes traces for listing (latency, tokens, cost,
model, tool stats, errors). The CLI (`agentcore traces list|show`) and the web app read it.

With the `otel` extra and `use_otel=True`, every span is mirrored to the OpenTelemetry API, so any
configured exporter (OTLP, Jaeger, Tempo, ...) receives it as well. The two share one trace id:
when an OpenTelemetry SDK tracer provider is configured, a root span adopts the OTel trace id as
its AgentCore `trace_id` (both are 32 hex characters), so the id in the web app is the id to
search for in Jaeger or Tempo. Every mirrored span also carries `agentcore.trace_id` and
`agentcore.span_id` attributes. With only `opentelemetry-api` installed (no SDK) OTel spans are
no-ops and AgentCore keeps its own ids; `agentcore doctor` reports the `otel` extra as installed
only when both the API and the SDK are present.

`agentcore eval` writes traces too (one per case, `kind:eval` in the explorer, like eval runs
started from the web app); pass `--no-trace` to skip them.

## Metrics

`get_metrics()` returns the process-wide `MetricsCollector` with counters, gauges and histograms:
`agentcore_agent_runs_total`, `agentcore_model_calls_total`, `agentcore_tokens_total`,
`agentcore_model_latency_ms`, `agentcore_tool_calls_total` and `agentcore_tool_latency_ms`.
`export_prometheus()` renders the Prometheus text format; `agentcore serve` exposes it at
`GET /metrics`. The `agent` label of `agentcore_agent_runs_total` is the agent name up to the
first `:`, so eval runs (agents named `eval:<case>`) count under `agent="eval"` instead of one
series per case.

## Logs and cost

`configure_logging(level="INFO", json_format=True)` sets up JSON logs for the `agentcore` logger
hierarchy, with the current trace id on every record (`get_logger(name)` for your own modules).

`CostTracker(price_table=None)` records every model call; `summary()` breaks spend down by model and
by agent. Prices come from `agentcore.obs.PRICE_TABLE` (USD per million input and output tokens).
The table is illustrative and not kept up to date: pass your own to `CostTracker` for real
accounting. Local models (`ollama:`, `mock`, `vllm:`) are free.
