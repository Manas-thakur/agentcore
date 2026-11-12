from __future__ import annotations

import asyncio
import time

import pytest

from agentcore.graph import (
    END,
    START,
    FileCheckpointer,
    StateGraph,
    WorkflowError,
    add,
    append,
    interrupt,
)
from tests.conftest import run


def linear():
    g = StateGraph("linear")
    g.add_node("a", lambda s: {"x": s["x"] + 1})
    g.add_node("b", lambda s: {"x": s["x"] * 10})
    g.add_edge(START, "a").add_edge("a", "b").add_edge("b", END)
    return g


def test_linear_graph():
    result = linear().compile().run_sync({"x": 1})
    assert result.status == "completed" and result.state["x"] == 20 and result.history == ["a", "b"]


def test_fan_out_join_runs_in_parallel_with_reducers(spans):
    g = StateGraph("fan", reducers={"items": append, "count": add})

    async def worker(name):
        async def fn(state):
            await asyncio.sleep(0.3)
            return {"items": name, "count": 1}

        return fn

    g.add_node("start", lambda s: {"items": [], "count": 0})
    for name in ("w1", "w2", "w3"):
        g.add_node(name, run(worker(name)))
    g.add_node("join", lambda s: {"total": len(s["items"])})
    g.add_edge(START, "start").add_edge("start", ["w1", "w2", "w3"]).add_edge(
        ["w1", "w2", "w3"], "join"
    )
    t0 = time.perf_counter()
    result = g.compile().run_sync({})
    assert time.perf_counter() - t0 < 0.75  # three 0.3 s nodes ran concurrently (sequential: 0.9 s)
    assert sorted(result.state["items"]) == ["w1", "w2", "w3"]
    assert result.state["count"] == 3 and result.state["total"] == 3
    assert result.history.count("join") == 1
    names = [s.name for s in spans.spans]
    assert "graph.run:fan" in names and "graph.node:w2" in names


def test_conditional_loop():
    g = StateGraph("loop")
    g.add_node("inc", lambda s: {"n": s["n"] + 1})
    g.add_edge(START, "inc")
    g.add_conditional_edges(
        "inc", lambda s: "again" if s["n"] < 5 else "stop", {"again": "inc", "stop": END}
    )
    result = g.compile().run_sync({"n": 0})
    assert result.state["n"] == 5 and result.steps == 5


def test_max_steps_guard():
    g = StateGraph("forever")
    g.add_node("spin", lambda s: None)
    g.add_edge(START, "spin").add_edge("spin", "spin")
    result = g.compile(max_steps=7).run_sync({})
    assert result.status == "failed" and "max_steps" in result.error


def test_interrupt_and_resume_with_checkpointer(tmp_path):
    g = StateGraph("hitl")
    g.add_node("draft", lambda s: {"draft": "v1"})

    def review(state):
        answer = interrupt({"question": "approve?", "draft": state["draft"]})
        return {"approved": answer == "yes"}

    g.add_node("review", review)
    g.add_edge(START, "draft").add_edge("draft", "review").add_edge("review", END)
    cp = FileCheckpointer(tmp_path)
    app = g.compile(cp)
    first = app.run_sync({}, thread_id="t-1")
    assert first.status == "interrupted"
    assert first.interrupt == {"node": "review", "payload": {"question": "approve?", "draft": "v1"}}
    assert app.get_state("t-1").next_nodes == ["review"]

    # a *new* compiled app (e.g. after a restart) can resume from the file checkpoint
    app2 = g.compile(FileCheckpointer(tmp_path))
    done = app2.resume_sync("t-1", "yes")
    assert done.status == "completed" and done.state["approved"] is True
    assert done.history == ["draft", "review"]
    assert len(cp.history("t-1")) >= 3
    with pytest.raises(WorkflowError):
        app2.resume_sync("t-1", "again")


def test_parallel_interrupts_resume_with_mapping():
    g = StateGraph("two-approvals", reducers={"answers": append})
    g.add_node("split", lambda s: None)
    g.add_node("legal", lambda s: {"answers": f"legal:{interrupt('legal?')}"})
    g.add_node("finance", lambda s: {"answers": f"finance:{interrupt('finance?')}"})
    g.add_edge(START, "split").add_edge("split", ["legal", "finance"])
    app = g.compile()
    r = app.run_sync({})
    assert r.status == "interrupted" and {i["node"] for i in r.interrupts} == {"legal", "finance"}
    r = app.resume_sync(r.thread_id, {"legal": "ok", "finance": "no"})
    assert r.status == "completed" and sorted(r.state["answers"]) == ["finance:no", "legal:ok"]


def test_saga_compensation_on_failure():
    log = []
    g = StateGraph("saga", reducers={"log": append})
    g.add_node(
        "book_flight", lambda s: {"log": "flight"}, compensate=lambda s: log.append("cancel flight")
    )
    g.add_node(
        "book_hotel", lambda s: {"log": "hotel"}, compensate=lambda s: log.append("cancel hotel")
    )

    def charge(state):
        raise RuntimeError("card declined")

    g.add_node("charge", charge, retries=2)
    g.add_edge(START, "book_flight").add_edge("book_flight", "book_hotel").add_edge(
        "book_hotel", "charge"
    )
    result = g.compile().run_sync({})
    assert result.status == "failed" and result.failed_node == "charge"
    assert "card declined" in result.error
    assert log == ["cancel hotel", "cancel flight"]
    assert result.compensated == ["book_hotel", "book_flight"]


def test_retries_then_success_and_fallback():
    attempts = {"n": 0}

    def flaky(state):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("flaky")
        return {"ok": True}

    def always_fails(state):
        raise ValueError("search is down")

    g = StateGraph("retry")
    g.add_node("flaky", flaky, retries=2)
    g.add_node("search", always_fails, fallback="cache")
    g.add_node("cache", lambda s: {"source": "cache"})
    g.add_edge(START, "flaky").add_edge("flaky", "search")
    result = g.compile().run_sync({})
    assert result.status == "completed" and result.state["ok"] and result.state["source"] == "cache"
    assert "search" in result.state["errors"] and attempts["n"] == 3


def test_subgraph_node():
    inner = StateGraph("inner")
    inner.add_node("double", lambda s: {"y": s["x"] * 2})
    inner.add_edge(START, "double")
    outer = StateGraph("outer")
    outer.add_node("sub", inner.compile().as_node(input_keys=["x"], output_keys=["y"]))
    outer.add_node("after", lambda s: {"z": s["y"] + 1})
    outer.add_edge(START, "sub").add_edge("sub", "after")
    result = outer.compile().run_sync({"x": 4, "other": "kept"})
    assert result.state == {"x": 4, "other": "kept", "y": 8, "z": 9}


def test_validation_and_mermaid():
    g = StateGraph("bad")
    g.add_node("a", lambda s: None)
    with pytest.raises(ValueError):
        g.compile()  # no entry point
    g.add_edge(START, "a").add_edge("a", "missing")
    with pytest.raises(ValueError):
        g.compile()

    g = linear()
    g.add_conditional_edges("a", lambda s: "x", {"x": "b"})
    mermaid = g.to_mermaid(highlight={"a": "done"})
    assert mermaid.startswith("flowchart TD")
    assert "START --> a" in mermaid and 'a -.->|"x"| b' in mermaid and "class a done" in mermaid


def test_node_must_return_dict():
    g = StateGraph("bad-return")
    g.add_node("a", lambda s: 42)
    g.add_edge(START, "a")
    result = g.compile().run_sync({})
    assert result.status == "failed" and "must return a dict" in result.error


def test_callbacks_receive_events():
    events = []
    linear().compile().run_sync(
        {"x": 0}, callbacks=[lambda e: events.append((e["type"], e["node"]))]
    )
    assert events == [
        ("node_start", "a"),
        ("node_end", "a"),
        ("node_start", "b"),
        ("node_end", "b"),
    ]
