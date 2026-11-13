"""Trace explorer: the query language, faceted filters, histogram, sorting, the eval results
matrix and overview period deltas."""

from __future__ import annotations

import time

import pytest

from agentcore.obs.storage import JSONLTraceStore, TraceSummary
from agentcore.obs.tracing import Span
from agentcore.server.query import QueryError, kind_of, parse_query

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agentcore.server import create_app  # noqa: E402
from tests.conftest import EXAMPLES  # noqa: E402


def summary(**kw) -> TraceSummary:
    base = dict(
        trace_id="abc123def456",
        name="agent.run:chat",
        start_time=time.time(),
        duration_ms=850.0,
        span_count=5,
        status="ok",
        total_tokens=420,
        cost_usd=0.002,
        attributes={"session.id": "s_1", "steps": 2},
        model="mock",
        input="What is 2 + 2?",
        output="The answer is 4.",
        tool_calls=1,
        tools={"calculator": {"calls": 1, "errors": 0, "total_ms": 1.0}},
    )
    base.update(kw)
    return TraceSummary(**base)


# --- parser ------------------------------------------------------------------------------------


def test_parse_fields_operators_negation_and_text():
    q = parse_query('status:error -model:mock latency:>1.5s tokens:<=500 "two words" refund -foo')
    got = [(c.field, c.op, c.value, c.negate) for c in q.clauses]
    assert got == [
        ("status", "=", "error", False),
        ("model", "=", "mock", True),
        ("latency", ">", 1500.0, False),
        ("tokens", "<=", 500.0, False),
        ("", "contains", "two words", False),
        ("", "contains", "refund", False),
        ("", "contains", "foo", True),
    ]
    assert parse_query("").clauses == [] and parse_query(None).clauses == []


def test_parse_units_aliases_and_colons_in_values():
    q = parse_query("duration:>=250 latency:<2m cost:>0.01 level:err name:agent.run:eval:*")
    assert [(c.field, c.value) for c in q.clauses] == [
        ("latency", 250.0),
        ("latency", 120000.0),
        ("cost", 0.01),
        ("status", "error"),
        ("name", "agent.run:eval:*"),
    ]
    assert parse_query("tokens:>1.5k").clauses[0].value == 1500.0


@pytest.mark.parametrize(
    "bad, fragment",
    [
        ("colour:red", "unknown field"),
        ("latency:>", "missing a number"),
        ("latency:>fast", "expected a number"),
        ("latency:>3h", "unknown unit"),
        ("status:maybe", "use ok or error"),
        ("kind:robot", "kind: use one of"),
        ('"unterminated', "unterminated"),
        ("status:", "missing a value"),
        ("status:ok,maybe", "use ok or error"),
    ],
)
def test_parse_errors(bad, fragment):
    with pytest.raises(QueryError) as info:
        parse_query(bad)
    assert fragment in str(info.value)


def test_matching_rules():
    s = summary()
    m = lambda text: parse_query(text).matches(s)  # noqa: E731
    assert m("status:ok") and not m("status:error") and m("-status:error")
    assert m("model:MOCK") and m("model:mo*") and not m("model:gpt*")
    assert m("tool:calculator") and not m("tool:web_search") and m("-tool:web_search")
    assert m("latency:>500") and m("latency:<1s") and not m("latency:>1s")
    assert m("tokens:420") and m("tokens:>=420") and not m("tokens:!=420")
    assert m("cost:>0.001") and m("session:s_1") and m("id:abc123") and m("steps:2")
    assert m("kind:chat") and m("name:agent.run:*") and m('"answer is 4"')
    assert not m('"2 + 3"') and m("-nothing-here")
    assert m("model:gpt-4o,mock") and not m("-model:gpt-4o,mock") and m("status:error,ok")
    assert parse_query("model:a,b").clauses[0].options == ["a", "b"]
    assert parse_query('model:"a,b"').clauses[0].options == ["a,b"]
    assert kind_of(summary(name="agent.run:eval:calc")) == "eval"
    assert kind_of(summary(name="tool.invoke")) == "tool"
    assert kind_of(summary(name="graph.run")) == "other"


# --- endpoints ---------------------------------------------------------------------------------


def write_trace(
    root: JSONLTraceStore,
    *,
    name: str = "agent.run:chat",
    model: str = "mock",
    status: str = "ok",
    ms: float = 100.0,
    tokens: int = 100,
    tool: str | None = "calculator",
    started: float | None = None,
    task: str = "What is 1 + 1?",
) -> str:
    t0 = started if started is not None else time.time()
    trace_id = f"t{int(t0 * 1e6):x}{tokens:x}{len(name)}"
    rid = trace_id[-8:] + "root"
    root.export(
        Span(
            name,
            trace_id,
            rid,
            start_time=t0,
            end_time=t0 + ms / 1000,
            attributes={"model": model, "task": task, "output": "done"},
            status=status,
            error="boom" if status == "error" else None,
        )
    )
    root.export(
        Span(
            "model.generate",
            trace_id,
            rid + "m",
            parent_id=rid,
            start_time=t0,
            end_time=t0 + ms / 2000,
            attributes={"model": model, "tokens.total": tokens, "cost.usd": tokens / 1e5},
        )
    )
    if tool:
        root.export(
            Span(
                "tool.execute",
                trace_id,
                rid + "t",
                parent_id=rid,
                start_time=t0 + ms / 2000,
                end_time=t0 + ms / 1000,
                attributes={"tool.name": tool},
            )
        )
    return trace_id


@pytest.fixture
def seeded(tmp_path):
    traces = tmp_path / "traces"
    store = JSONLTraceStore(traces)
    now = time.time()
    write_trace(store, ms=120, tokens=90, started=now - 300)
    write_trace(store, ms=2400, tokens=900, started=now - 200, task="slow one")
    write_trace(store, status="error", ms=60, tokens=30, tool=None, started=now - 100)
    write_trace(store, model="ollama:qwen", ms=700, tokens=400, tool="web_search", started=now - 50)
    write_trace(store, name="agent.run:eval:calc", ms=300, tokens=200, started=now - 10)
    client = TestClient(
        create_app(model="mock", trace_dir=str(traces), eval_dirs=[str(EXAMPLES / "evals")])
    )
    return client, now


def test_explore_filters_sorts_and_counts(seeded):
    client, now = seeded
    r = client.get("/api/traces/explore").json()
    assert r["total"] == 5 and len(r["items"]) == 5
    assert r["items"][0]["name"] == "agent.run:eval:calc"  # newest first
    assert r["items"][0]["kind"] == "eval"
    assert r["stats"]["count"] == 5 and r["stats"]["errors"] == 1
    assert r["stats"]["p95_ms"] >= r["stats"]["p50_ms"] > 0

    def total(q, **extra):
        return client.get("/api/traces/explore", params={"query": q, **extra}).json()["total"]

    assert total("status:error") == 1
    assert total("-status:error") == 4
    assert total("tool:calculator") == 3
    assert total("-tool:calculator") == 2
    assert total("latency:>1s") == 1
    assert total("tokens:>=400 model:mock") == 1
    assert total("model:ollama*") == 1
    assert total("kind:eval") == 1
    assert total('"slow one"') == 1
    assert total("cost:>0.003") == 2
    assert total("", since=str(now - 150)) == 3
    assert total("", until=str(now - 150)) == 2

    by_latency = client.get(
        "/api/traces/explore", params={"sort": "latency", "order": "asc"}
    ).json()["items"]
    lat = [i["duration_ms"] for i in by_latency]
    assert lat == sorted(lat)
    page = client.get("/api/traces/explore", params={"limit": 2, "offset": 4}).json()
    assert page["total"] == 5 and len(page["items"]) == 1


def test_explore_facets_are_disjunctive_and_histogram_counts(seeded):
    client, _ = seeded
    r = client.get("/api/traces/explore", params={"query": "status:error"}).json()
    status = {f["value"]: f["count"] for f in r["facets"]["status"]}
    assert status == {"ok": 4, "error": 1}  # own-field clause ignored for its own counts
    models = {f["value"]: f["count"] for f in r["facets"]["model"]}
    assert models == {"mock": 1}  # other facets respect status:error
    full = client.get("/api/traces/explore").json()
    tools = {f["value"]: f["count"] for f in full["facets"]["tool"]}
    assert tools == {"calculator": 3, "web_search": 1}
    kinds = {f["value"]: f["count"] for f in full["facets"]["kind"]}
    assert kinds == {"chat": 4, "eval": 1}
    hist = full["histogram"]
    assert sum(b["count"] for b in hist["buckets"]) == 5
    assert sum(b["errors"] for b in hist["buckets"]) == 1
    assert len(hist["buckets"]) == 48 and hist["end"] > hist["start"]
    small = client.get("/api/traces/explore", params={"buckets": 6}).json()["histogram"]
    assert len(small["buckets"]) == 6


def test_explore_and_list_reject_bad_queries(seeded):
    client, _ = seeded
    bad = client.get("/api/traces/explore", params={"query": "latency:>"})
    assert bad.status_code == 400
    assert bad.json()["type"] == "query_error" and "missing a number" in bad.json()["detail"]
    assert client.get("/api/traces/explore", params={"sort": "vibes"}).status_code == 400
    assert client.get("/api/traces", params={"query": "colour:red"}).status_code == 400
    # the classic list endpoint accepts the query language too
    listed = client.get("/api/traces", params={"query": "tool:calculator", "sort": "tokens"})
    assert listed.headers["x-total-count"] == "3"
    assert [t["total_tokens"] for t in listed.json()] == [900, 200, 90]
    facets = client.get("/api/traces/facets", params={"query": "kind:eval"}).json()
    assert facets["count"] == 5 and facets["facets"]["model"] == [{"value": "mock", "count": 1}]


def test_chat_traces_carry_the_session_id(tmp_path):
    client = TestClient(create_app(model="mock", trace_dir=str(tmp_path / "t")))
    with client.stream("POST", "/api/chat", json={"message": "What is 2 + 3?"}) as r:
        body = "".join(r.iter_text())
    assert "event: done" in body
    sid = client.get("/api/sessions").json()[0]["id"]
    turn = client.get(f"/api/sessions/{sid}").json()["messages"][1]
    assert turn["context"] == {
        "tools": ["calculator", "current_time"],
        "system_prompt": "default",
        "memory_messages": 0,
    }
    r = client.get("/api/traces/explore", params={"query": f"session:{sid}"}).json()
    assert r["total"] == 1 and r["items"][0]["attributes"]["session.id"] == sid


def test_overview_reports_the_previous_period(tmp_path):
    traces = tmp_path / "traces"
    store = JSONLTraceStore(traces)
    now = time.time()
    write_trace(store, ms=100, started=now - 3600)
    write_trace(store, ms=300, started=now - 1800, status="error")
    write_trace(store, ms=200, started=now - 86400 - 3600)  # previous 24 h window
    client = TestClient(create_app(model="mock", trace_dir=str(traces)))
    ov = client.get("/api/overview", params={"days": 1}).json()
    assert ov["kpis"]["runs"] == 2 and ov["kpis"]["errors"] == 1
    assert ov["previous"]["runs"] == 1 and ov["previous"]["errors"] == 0
    assert ov["top_tools"][0]["error_rate"] == 0.0
    empty = TestClient(create_app(model="mock", trace_dir=str(tmp_path / "none")))
    assert empty.get("/api/overview").json()["previous"] is None


# --- eval matrix --------------------------------------------------------------------------------


def _wait(client: TestClient, run_id: str) -> dict:
    deadline = time.time() + 20
    while time.time() < deadline:
        run = client.get(f"/api/evals/runs/{run_id}").json()
        if run["status"] in ("completed", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError("eval run did not finish")


def test_eval_matrix_marks_regressions(tmp_path):
    suite_dir = tmp_path / "evals"
    suite_dir.mkdir()
    src = (EXAMPLES / "evals" / "calculator_suite.yaml").read_text(encoding="utf-8")
    (suite_dir / "calc.yaml").write_text(src, encoding="utf-8")
    app = create_app(model="mock", trace_dir=str(tmp_path / "t"), eval_dirs=[str(suite_dir)])
    with TestClient(app) as client:
        empty = client.get("/api/evals/matrix", params={"suite": "calculator-basic"}).json()
        assert empty["runs"] == [] and all(c["cells"] == [] for c in empty["cases"])
        assert [c["case"] for c in empty["cases"]][0] == "multiply_add"

        first = _wait(
            client, client.post("/api/evals/runs", json={"suite": "calculator-basic"}).json()["id"]
        )
        assert first["results"][0]["trace_id"]  # each case links to its agent trace
        client.post(f"/api/evals/runs/{first['id']}/baseline")
        (suite_dir / "calc.yaml").write_text(
            src.replace('expected_output: "395"', 'expected_output: "999"'), encoding="utf-8"
        )
        time.sleep(1.05)  # run ids/started_at have second resolution
        second = _wait(
            client, client.post("/api/evals/runs", json={"suite": "calculator-basic"}).json()["id"]
        )
        m = client.get("/api/evals/matrix", params={"suite": "calculator-basic", "limit": 5}).json()
    assert m["suite"] == "calculator-basic" and m["baseline"] == first["id"]
    assert [r["id"] for r in m["runs"]] == [first["id"], second["id"]]
    assert m["runs"][0]["is_baseline"] is True
    rows = {c["case"]: c for c in m["cases"]}
    bad = rows["multiply_add"]["cells"]
    assert bad[0]["passed"] is True and bad[0]["regressed"] is False
    assert bad[1]["passed"] is False and bad[1]["regressed"] is True
    assert bad[1]["baseline_regressed"] is True and bad[1]["failing"]
    assert rows["power"]["cells"][1]["regressed"] is False
    assert m["regressions"] == 1
