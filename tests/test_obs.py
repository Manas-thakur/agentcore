from __future__ import annotations

import asyncio
import io
import json
import logging

from agentcore.obs import (
    CostTracker,
    InMemoryExporter,
    JSONLTraceStore,
    MetricsCollector,
    Tracer,
    configure_logging,
    estimate_cost,
    get_metrics,
    price_for,
    render_tree,
    set_tracer,
)
from agentcore.runtime import Agent, MockModel
from agentcore.tools import calculator
from tests.conftest import run


def test_spans_nest_across_async_tasks():
    exp = InMemoryExporter()
    tracer = Tracer([exp])

    async def child(name):
        with tracer.span(name):
            await asyncio.sleep(0.01)

    async def main():
        with tracer.span("root", {"k": 1}):
            await asyncio.gather(child("a"), child("b"))

    run(main())
    by = {s.name: s for s in exp.spans}
    assert by["a"].parent_id == by["root"].span_id == by["b"].parent_id
    assert len({s.trace_id for s in exp.spans}) == 1
    assert by["root"].attributes == {"k": 1} and by["root"].duration_ms >= 10


def test_span_records_errors():
    exp = InMemoryExporter()
    tracer = Tracer([exp])
    try:
        with tracer.span("bad"):
            raise KeyError("x")
    except KeyError:
        pass
    assert exp.spans[0].status == "error" and "KeyError" in exp.spans[0].error


def test_jsonl_store_and_agent_instrumentation(tmp_path):
    store = JSONLTraceStore(tmp_path)
    set_tracer(Tracer([store]))
    result = Agent(MockModel(), tools=[calculator], name="calc").run_sync("What is 3 * 4?")
    assert result.trace_id
    summaries = store.list()
    assert len(summaries) == 1
    s = summaries[0]
    assert (
        s.trace_id == result.trace_id
        and s.name == "agent.run:calc"
        and s.total_tokens == result.usage.total_tokens
    )
    spans = store.load(s.trace_id)
    names = [sp.name for sp in spans]
    assert names.count("model.generate") == 2 and "tool.execute" in names and "agent.step" in names
    assert store.resolve(s.trace_id[:8]) == s.trace_id
    tree = render_tree(spans)
    assert tree.startswith("- agent.run:calc") and "tool.name=calculator" in tree


def test_metrics_collector():
    m = MetricsCollector(buckets=(10, 100))
    m.counter("calls_total", labels={"tool": "calc"})
    m.counter("calls_total", 2, labels={"tool": "calc"})
    m.gauge("queue", 5)
    m.histogram("latency_ms", 7)
    m.histogram("latency_ms", 70)
    m.histogram("latency_ms", 700)
    assert m.get_counter("calls_total", {"tool": "calc"}) == 3
    text = m.export_prometheus()
    assert 'calls_total{tool="calc"} 3.0' in text
    assert 'latency_ms_bucket{le="10"} 1' in text and 'latency_ms_bucket{le="+Inf"} 3' in text
    assert m.export_json()["histograms"]["latency_ms"][0]["count"] == 3


def test_agent_updates_global_metrics():
    Agent(MockModel(), tools=[calculator]).run_sync("What is 1 + 1?")
    m = get_metrics()
    assert m.get_counter("agentcore_tool_calls_total", {"tool": "calculator", "success": True}) == 1
    assert m.get_counter("agentcore_model_calls_total", {"model": "mock"}) == 2


def test_cost_tracking():
    assert price_for("openai:gpt-4o-mini") == (0.15, 0.60)
    assert price_for("gpt-4o-2024-08-06") == (2.50, 10.00)  # prefix match
    assert price_for("ollama:qwen2.5:7b") == (0.0, 0.0)
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == 0.75
    ct = CostTracker()
    ct.record("gpt-4o-mini", 1000, 1000, agent="a")
    ct.record("ollama:llama3.1", 5000, 100, agent="b")
    summary = ct.summary()
    assert summary["calls"] == 2 and summary["by_agent"]["b"] == 0.0
    assert abs(summary["total_usd"] - 0.00075) < 1e-9


def test_structured_logging_includes_trace_ids():
    stream = io.StringIO()
    configure_logging("INFO", json_format=True, stream=stream)
    tracer = Tracer()
    log = logging.getLogger("agentcore.test")
    with tracer.span("op") as span:
        log.info("hello", extra={"user": "u1"})
    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["msg"] == "hello" and record["user"] == "u1"
    assert record["trace_id"] == span.trace_id and record["span_id"] == span.span_id
