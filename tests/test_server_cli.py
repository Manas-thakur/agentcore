from __future__ import annotations

import json

import pytest

from agentcore.cli import main
from tests.conftest import EXAMPLES


@pytest.fixture
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agentcore.server import create_app

    return TestClient(create_app(model="mock", trace_dir=str(tmp_path / "traces")))


def test_server_endpoints(client):
    health = client.get("/health").json()
    assert (
        health["status"] == "ok" and health["model"] == "mock" and "calculator" in health["tools"]
    )
    r = client.post("/v1/agent", json={"input": "What is 12 * 12?"})
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "agent.run" and body["output"] == "The answer is 144."
    assert body["tool_calls"][0]["name"] == "calculator" and body["trace_id"]
    traces = client.get("/api/traces").json()
    assert traces and traces[0]["trace_id"] == body["trace_id"]
    detail = client.get(f"/api/traces/{body['trace_id'][:10]}").json()
    assert any(s["name"] == "tool.execute" for s in detail["spans"])
    assert client.get("/api/traces/doesnotexist").status_code == 404
    assert "AgentCore" in client.get("/").text
    assert "agentcore_model_calls_total" in client.get("/metrics").text
    msgs = client.post(
        "/v1/agent", json={"messages": [{"role": "user", "content": "What is 2 + 3?"}]}
    ).json()
    assert msgs["output"] == "The answer is 5."
    assert (
        client.post("/v1/agent", json={"input": "x", "tools": ["python_exec"]}).status_code == 400
    )
    assert client.post("/v1/agent", json={}).status_code == 400
    assert client.get("/v1/models").json()["data"][0]["id"] == "mock"


def test_cli_tools_and_version(capsys):
    assert main(["tools"]) == 0
    out = capsys.readouterr().out
    assert "calculator [math]" in out and "python_exec" in out
    with pytest.raises(SystemExit):
        main(["--version"])


def test_cli_eval_baseline_and_regression(tmp_path, capsys):
    suite = str(EXAMPLES / "evals" / "calculator_suite.yaml")
    baseline = tmp_path / "baseline.json"
    assert (
        main(
            [
                "eval",
                "--suite",
                suite,
                "--model",
                "mock",
                "--baseline",
                str(baseline),
                "--save-baseline",
            ]
        )
        == 0
    )
    assert baseline.exists()
    out_json = tmp_path / "out.json"
    md = tmp_path / "report.md"
    code = main(
        [
            "eval",
            "--suite",
            suite,
            "--model",
            "mock",
            "--baseline",
            str(baseline),
            "--output",
            str(out_json),
            "--markdown",
            str(md),
        ]
    )
    assert code == 0
    assert json.loads(out_json.read_text())["summary"]["pass_rate"] == 1.0
    assert "No regressions." in capsys.readouterr().out and md.exists()
    # a deliberately broken baseline (higher scores than reality is impossible, so fake a failing current run)
    data = json.loads(baseline.read_text())
    for r in data["runs"]:
        r["passed"] = True
    data["runs"][0]["metrics"][0]["score"] = 1.0
    broken_suite = tmp_path / "suite.yaml"
    broken_suite.write_text(
        (EXAMPLES / "evals" / "calculator_suite.yaml")
        .read_text()
        .replace('expected_output: "395"', 'expected_output: "999"')
    )
    assert (
        main(["eval", "--suite", str(broken_suite), "--model", "mock", "--baseline", str(baseline)])
        == 1
    )


def test_cli_chat_one_shot(tmp_path, capsys):
    assert (
        main(["chat", "--model", "mock", "-p", "What is 9 * 9?", "--trace-dir", str(tmp_path)]) == 0
    )
    assert "The answer is 81." in capsys.readouterr().out


def test_cli_traces(tmp_path, capsys):
    main(["chat", "--model", "mock", "-p", "What is 1 + 2?", "--trace-dir", str(tmp_path)])
    capsys.readouterr()
    assert main(["traces", "--dir", str(tmp_path), "list"]) == 0
    listing = capsys.readouterr().out
    trace_id = listing.splitlines()[1].split()[0]
    assert main(["traces", "--dir", str(tmp_path), "show", trace_id[:8]]) == 0
    assert "agent.run:chat" in capsys.readouterr().out
    assert main(["traces", "--dir", str(tmp_path), "show", "zzzz"]) == 1


def test_cli_run_example_and_research(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["run", str(EXAMPLES / "calculator_agent.py"), "--model", "mock"]) == 0
    assert "The answer is 131.6666667." in capsys.readouterr().out
    out = tmp_path / "r" / "report.md"
    assert (
        main(
            [
                "research",
                "What is BM25?",
                "--docs",
                str(EXAMPLES / "data"),
                "--model",
                "mock",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert (
        out.exists()
        and (tmp_path / "r" / "report.trace.json").exists()
        and (tmp_path / "r" / "report.cost.json").exists()
    )
    trace = json.loads((tmp_path / "r" / "report.trace.json").read_text())
    assert trace["spans"] and trace["result"]["stop_reason"] == "final"
    assert main(["research", "x"]) == 2
