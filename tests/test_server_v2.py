"""Tests for the v0.2 HTTP API: SSE chat, sessions, OpenAI-compatible endpoint, eval jobs,
traces/overview, tools, auth, CORS and request limits."""

from __future__ import annotations

import json
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agentcore.server import create_app  # noqa: E402
from tests.conftest import EXAMPLES  # noqa: E402

SUITE_PATH = (EXAMPLES / "evals" / "calculator_suite.yaml").resolve()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "AGENTCORE_API_KEY",
        "AGENTCORE_CORS_ORIGINS",
        "AGENTCORE_MODEL",
        "AGENTCORE_TOOLS",
    ):
        monkeypatch.delenv(var, raising=False)


def make_client(tmp_path, **kwargs) -> TestClient:
    kwargs.setdefault("model", "mock")
    kwargs.setdefault("trace_dir", str(tmp_path / "traces"))
    kwargs.setdefault("eval_dirs", [str(EXAMPLES / "evals")])
    return TestClient(create_app(**kwargs))


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        name, data = "message", []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


def chat(client: TestClient, message: str, **extra) -> list[tuple[str, dict]]:
    with client.stream("POST", "/api/chat", json={"message": message, **extra}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    return parse_sse(body)


# --- shell ------------------------------------------------------------------------------------


def test_web_app_shell_and_static(client):
    html = client.get("/").text
    assert "AgentCore" in html and "/static/js/app.js?v=" in html and "{{version}}" not in html
    js = client.get("/static/js/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert js.headers["cache-control"] == "no-cache"
    for path in (
        "/static/app.css",
        "/static/js/api.js",
        "/static/js/md.js",
        "/static/js/views/playground.js",
        "/static/js/views/traces.js",
        "/static/js/views/evals.js",
        "/static/js/views/overview.js",
        "/static/js/views/tools.js",
        "/static/js/views/settings.js",
        "/static/js/palette.js",
        "/static/js/peek.js",
        "/static/js/query.js",
        "/static/js/trace-detail.js",
        "/favicon.ico",
    ):
        assert client.get(path).status_code == 200, path
    cfg = client.get("/api/config").json()
    assert cfg["default_model"] == "mock" and cfg["server"]["auth_enabled"] is False
    assert "api_key" not in json.dumps(cfg)


# --- streaming chat + sessions ----------------------------------------------------------------


def test_chat_stream_events_and_tool_calls(client):
    events = chat(client, "What is 17 * 23 + 4?")
    names = [n for n, _ in events]
    assert names[0] == "session" and names[-1] == "done"
    for expected in ("run_start", "step_start", "tool_start", "tool_end", "token", "final"):
        assert expected in names, expected
    data = dict(events)
    assert data["tool_start"]["name"] == "calculator"
    assert data["tool_start"]["arguments"] == {"expression": "17 * 23 + 4"}
    assert data["tool_end"]["success"] is True and data["tool_end"]["output"] == "395"
    tokens = "".join(d["content"] for n, d in events if n == "token")
    assert tokens == "The answer is 395."
    done = data["done"]
    assert done["output"] == "The answer is 395." and done["stop_reason"] == "final"
    assert done["trace_id"] == data["run_start"]["trace_id"]
    assert done["usage"]["total_tokens"] > 0
    # the answer links to a real trace
    trace = client.get(f"/api/traces/{done['trace_id']}").json()
    assert trace["summary"]["name"] == "agent.run:chat"


def test_sessions_keep_memory_across_turns(client):
    first = chat(client, "What is 2 + 2?")
    sid = dict(first)["session"]["session_id"]
    second = chat(client, "And 3 * 3?", session_id=sid)
    assert dict(second)["session"]["session_id"] == sid
    assert dict(second)["done"]["output"] == "The answer is 9."
    session = client.get(f"/api/sessions/{sid}").json()
    roles = [m["role"] for m in session["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert session["title"] == "What is 2 + 2?"
    tool_part = next(p for p in session["messages"][1]["parts"] if p["type"] == "tool")
    assert tool_part["name"] == "calculator" and tool_part["status"] == "ok"
    assert session["messages"][1]["trace_id"]
    # memory was sent to the model on the second turn: more messages in the prompt
    t2 = client.get(f"/api/traces/{dict(second)['done']['trace_id']}").json()
    first_call = next(s for s in t2["spans"] if s["name"] == "model.generate")
    assert first_call["attributes"]["messages"] == 4  # system + user + assistant + user
    assert [m["role"] for m in first_call["attributes"]["input.messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    listing = client.get("/api/sessions").json()
    assert listing[0]["id"] == sid and listing[0]["turns"] == 4
    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.post("/api/sessions/nope/stop").status_code == 404


def test_sessions_persist_to_disk(tmp_path):
    c1 = make_client(tmp_path)
    sid = dict(chat(c1, "What is 5 * 5?"))["session"]["session_id"]
    c2 = make_client(tmp_path)  # a "restarted" server with the same state dir
    session = c2.get(f"/api/sessions/{sid}").json()
    assert len(session["messages"]) == 2 and session["memory"]["messages"]
    created = c2.post("/api/sessions", json={"title": "Scratch"})
    assert created.status_code == 201 and created.json()["title"] == "Scratch"


def test_chat_validation(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert (
        client.post("/api/chat", json={"message": "hi", "tools": ["python_exec"]}).status_code
        == 400
    )
    assert client.post("/api/chat", json={"message": "hi", "model": "nope:x"}).status_code == 400
    assert (
        client.post("/api/chat", json={"message": "hi", "session_id": "../etc"}).status_code == 400
    )


def test_chat_with_session_via_v1_agent(client):
    r1 = client.post("/v1/agent", json={"input": "What is 6 * 7?", "session_id": "demo-1"}).json()
    assert r1["output"] == "The answer is 42." and r1["session_id"] == "demo-1"
    client.post("/v1/agent", json={"input": "What is 1 + 1?", "session_id": "demo-1"})
    assert len(client.get("/api/sessions/demo-1").json()["messages"]) == 4


def test_stop_endpoint_cancels_a_running_turn(tmp_path):
    import threading

    from agentcore.tools import tool

    @tool(timeout=30)
    async def slow_search(query: str) -> str:
        """Search slowly.

        Args:
            query: What to look for.
        """
        import asyncio

        await asyncio.sleep(5)
        return "found"

    with make_client(tmp_path, extra_tools={"slow_search": slow_search}) as c:
        events: list = []

        def run() -> None:
            events.extend(chat(c, "Find documents about agents", session_id="slow-1"))

        worker = threading.Thread(target=run)
        worker.start()
        deadline = time.time() + 5
        while time.time() < deadline and not c.get("/api/sessions/slow-1").json().get("busy"):
            time.sleep(0.02)
        assert (
            c.post("/api/chat", json={"message": "again", "session_id": "slow-1"}).status_code
            == 409
        )
        assert c.post("/api/sessions/slow-1/stop").json() == {"stopped": True}
        worker.join(5)
        assert not worker.is_alive()
        names = [n for n, _ in events]
        assert "tool_start" in names and names[-1] == "stopped" and "done" not in names
        session = c.get("/api/sessions/slow-1").json()
        assert session["busy"] is False and session["messages"][-1]["status"] == "stopped"
        trace = c.get("/api/traces", params={"status": "error"}).json()
        assert trace and "Cancelled" in (trace[0]["error"] or "")


# --- OpenAI-compatible endpoint ----------------------------------------------------------------


def test_chat_completions_non_streaming(client):
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "agentcore",
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": [{"type": "text", "text": "What is 12 * 12?"}]},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion" and body["model"] == "agentcore"
    choice = body["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": "The answer is 144."}
    assert choice["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] > 0
    assert body["agentcore"]["tool_calls"][0]["name"] == "calculator"
    # explicit model spec works too; unknown specs give an OpenAI-style 404
    assert (
        client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "user", "content": "hi"}]},
        ).status_code
        == 200
    )
    bad = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-9", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert bad.status_code == 404 and bad.json()["error"]["code"] == "model_not_found"
    no_user = client.post(
        "/v1/chat/completions", json={"messages": [{"role": "system", "content": "x"}]}
    )
    assert no_user.status_code == 400


def test_chat_completions_streaming(client):
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "agentcore",
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "What is 2 ** 10?"}],
        },
    ) as r:
        assert r.status_code == 200
        lines = [ln for ln in "".join(r.iter_text()).splitlines() if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(ln[6:]) for ln in lines[:-1]]
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
    assert text == "The answer is 1024."
    finishes = [c["choices"][0]["finish_reason"] for c in chunks if c["choices"]]
    assert finishes[-1] == "stop"
    assert chunks[-1]["choices"] == [] and chunks[-1]["usage"]["total_tokens"] > 0


def test_models_list(client):
    data = client.get("/v1/models").json()["data"]
    ids = [m["id"] for m in data]
    assert ids[0] == "mock" and data[0]["default"] is True


# --- traces, overview, tools -------------------------------------------------------------------


def test_trace_filters_export_and_overview(client):
    ok = client.post("/v1/agent", json={"input": "What is 3 + 4?"}).json()
    client.post("/v1/agent", json={"input": "Say hello"})
    all_traces = client.get("/api/traces")
    assert all_traces.headers["x-total-count"] == "2"
    assert len(client.get("/api/traces", params={"q": "3 + 4"}).json()) == 1
    assert len(client.get("/api/traces", params={"status": "error"}).json()) == 0
    assert len(client.get("/api/traces", params={"model": "mock"}).json()) == 2
    assert len(client.get("/api/traces", params={"kind": "eval"}).json()) == 0
    assert client.get("/api/traces", params={"since": "2999-01-01"}).json() == []
    assert client.get("/api/traces", params={"since": "not-a-date"}).status_code == 400
    item = client.get("/api/traces", params={"q": "3 + 4"}).json()[0]
    assert item["model"] == "mock" and item["tool_calls"] == 1 and item["input"] == "What is 3 + 4?"
    facets = client.get("/api/traces/facets").json()
    assert facets["models"] == ["mock"] and facets["count"] == 2

    detail = client.get(f"/api/traces/{ok['trace_id']}").json()
    gen = next(s for s in detail["spans"] if s["name"] == "model.generate")
    assert gen["attributes"]["input.messages"][-1]["content"] == "What is 3 + 4?"
    assert gen["attributes"]["output.tool_calls"][0]["name"] == "calculator"
    exp = client.get(f"/api/traces/{ok['trace_id']}/export")
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"]
    assert json.loads(exp.text)["trace_id"] == ok["trace_id"]
    assert client.get("/api/traces/zzzz/export").status_code == 404

    ov = client.get("/api/overview", params={"days": 1, "tz": -330}).json()
    assert ov["kpis"]["runs"] == 2 and ov["kpis"]["success_rate"] == 1.0
    assert ov["kpis"]["p95_ms"] >= ov["kpis"]["p50_ms"] > 0
    assert sum(b["runs"] for b in ov["series"]) == 2 and ov["range"]["bucket_seconds"] == 3600
    assert ov["top_tools"][0] == {
        "name": "calculator",
        "calls": 1,
        "errors": 0,
        "avg_ms": pytest.approx(ov["top_tools"][0]["avg_ms"]),
        "error_rate": 0.0,
    }
    assert ov["models"][0]["model"] == "mock"


def test_tools_list_and_invoke(client):
    tools = client.get("/api/tools").json()
    calc = next(t for t in tools if t["name"] == "calculator")
    assert calc["parameters"]["required"] == ["expression"] and calc["source"] == "builtin"
    r = client.post(
        "/api/tools/calculator/invoke", json={"arguments": {"expression": "2 ** 8"}}
    ).json()
    assert r["success"] is True and r["output"] == "256" and r["trace_id"]
    bad = client.post("/api/tools/calculator/invoke", json={"arguments": {}}).json()
    assert bad["success"] is False and bad["error_type"] == "ToolValidationError"
    assert client.post("/api/tools/python_exec/invoke", json={"arguments": {}}).status_code == 404
    trace = client.get(f"/api/traces/{r['trace_id']}").json()
    assert {s["name"] for s in trace["spans"]} == {"tool.invoke", "tool.execute"}


def test_custom_tools_are_served(tmp_path):
    from agentcore.tools import tool

    @tool
    def shout(text: str) -> str:
        """Upper-case some text.

        Args:
            text: Text to shout.
        """
        return text.upper()

    c = make_client(tmp_path, extra_tools={"shout": shout})
    names = [t["name"] for t in c.get("/api/tools").json()]
    assert names == ["calculator", "current_time", "shout"]
    r = c.post("/api/tools/shout/invoke", json={"arguments": {"text": "hey"}}).json()
    assert r["output"] == "HEY"


# --- evals -------------------------------------------------------------------------------------


def wait_for(client: TestClient, run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/evals/runs/{run_id}").json()
        if run["status"] in ("completed", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError("eval run did not finish")


def test_eval_jobs_history_baseline_and_diff(tmp_path):
    suite_dir = tmp_path / "evals"
    suite_dir.mkdir()
    (suite_dir / "calc.yaml").write_text(SUITE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (suite_dir / "broken.yaml").write_text("cases: [", encoding="utf-8")
    # background jobs need one long-lived event loop: use the client as a context manager
    with make_client(tmp_path, eval_dirs=[str(suite_dir)]) as client:
        _eval_scenario(client, suite_dir)


def _eval_scenario(client: TestClient, suite_dir) -> None:
    suites = client.get("/api/evals/suites").json()
    by_name = {s["name"]: s for s in suites}
    assert by_name["calculator-basic"]["cases"] == 5 and "error" in by_name["broken"]

    path = by_name["calculator-basic"]["path"]
    started = client.post("/api/evals/runs", json={"suite": path, "model": "mock"})
    assert started.status_code == 202
    job = started.json()
    assert job["total"] == 5 and job["status"] in ("queued", "running", "completed")
    run = wait_for(client, job["id"])
    assert run["status"] == "completed" and run["summary"]["pass_rate"] == 1.0
    assert len(run["results"]) == 5 and run["diff"] is None and run["baseline"] is None

    assert client.post(f"/api/evals/runs/{job['id']}/baseline").json()["baseline"] == job["id"]
    assert client.get(f"/api/evals/runs/{job['id']}").json()["is_baseline"] is True

    # break one case on disk -> the next run regresses against the baseline
    text = (suite_dir / "calc.yaml").read_text(encoding="utf-8")
    (suite_dir / "calc.yaml").write_text(
        text.replace('expected_output: "395"', 'expected_output: "999"'), encoding="utf-8"
    )
    second = wait_for(
        client, client.post("/api/evals/runs", json={"suite": "calculator-basic"}).json()["id"]
    )
    assert second["summary"]["passed"] == 4
    assert second["diff"]["has_regressions"] is True
    assert second["diff"]["new_failures"] == ["multiply_add"]
    assert second["baseline"]["id"] == job["id"]
    assert second["baseline"]["cases"]["multiply_add"]["passed"] is True

    history = client.get("/api/evals/runs", params={"suite": "calculator-basic"}).json()
    assert [h["id"] for h in history] == [second["id"], job["id"]]
    assert history[1]["is_baseline"] is True
    assert client.post("/api/evals/runs", json={"suite": "missing"}).status_code == 404
    assert client.get("/api/evals/runs/ev_nope").status_code == 404
    assert client.post("/api/evals/runs/ev_nope/baseline").status_code == 404
    # eval traces are tagged as such
    assert client.get("/api/traces", params={"kind": "eval"}).json()


# --- security ----------------------------------------------------------------------------------


def test_api_key_auth(tmp_path):
    c = make_client(tmp_path, api_key="s3cret-test-key")
    assert c.get("/health").json()["auth"] is True
    assert c.get("/").status_code == 200 and c.get("/static/app.css").status_code == 200
    r = c.get("/api/traces")
    assert r.status_code == 401 and r.json()["error"]["type"] == "invalid_api_key"
    assert c.post("/v1/agent", json={"input": "1+1"}).status_code == 401
    assert c.get("/metrics").status_code == 401
    assert c.get("/api/traces", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert (
        c.get("/api/traces", headers={"Authorization": "Bearer s3cret-test-key"}).status_code == 200
    )
    assert c.get("/v1/models", headers={"X-API-Key": "s3cret-test-key"}).status_code == 200


def test_api_key_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCORE_API_KEY", "env-test-key")
    c = make_client(tmp_path)
    assert c.get("/api/tools").status_code == 401
    assert c.get("/api/tools", headers={"Authorization": "Bearer env-test-key"}).status_code == 200


def test_cors_and_body_limit(tmp_path):
    c = make_client(tmp_path, cors_origins=["http://localhost:5173"], max_body_bytes=2048)
    pre = c.options(
        "/v1/chat/completions",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = c.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers
    big = c.post("/v1/agent", json={"input": "x" * 5000})
    assert big.status_code == 413 and big.json()["error"]["type"] == "request_too_large"
    assert c.post("/v1/agent", json={"input": "What is 1 + 1?"}).status_code == 200
    # no CORS headers at all unless configured
    plain = make_client(tmp_path / "p")
    assert (
        "access-control-allow-origin"
        not in plain.get("/health", headers={"Origin": "http://x"}).headers
    )


def test_starter_eval_suite_can_be_created_and_run(tmp_path):
    eval_dir = tmp_path / "evals"
    client = make_client(tmp_path, eval_dirs=[str(eval_dir)])
    assert client.get("/api/evals/suites").json() == []

    made = client.post("/api/evals/starter")
    assert made.status_code == 201, made.text
    assert made.json()["name"] == "starter"
    assert (eval_dir / "starter.yaml").is_file()

    suites = client.get("/api/evals/suites").json()
    assert [s["name"] for s in suites] == ["starter"] and suites[0]["cases"] == 3

    # Never overwrites an existing suite.
    assert client.post("/api/evals/starter").status_code == 409
