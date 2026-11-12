"""Tests for v0.2 CLI features: init scaffold, doctor, agentcore.toml configuration."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from agentcore.cli import main
from agentcore.config import ConfigError, load_config, load_tool_modules


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "AGENTCORE_MODEL",
        "AGENTCORE_TRACE_DIR",
        "AGENTCORE_API_KEY",
        "AGENTCORE_TOOLS",
        "AGENTCORE_EVAL_DIRS",
    ):
        monkeypatch.delenv(var, raising=False)


def test_init_scaffold_runs_offline(tmp_path, capsys, monkeypatch):
    project = tmp_path / "my-agent"
    assert main(["init", str(project)]) == 0
    out = capsys.readouterr().out
    for name in ("agent.py", "evals/basic.yaml", "agentcore.toml", ".env.example", "README.md"):
        assert (project / name).exists(), name
        assert name in out
    # refuses to overwrite without --force
    assert main(["init", str(project)]) == 1
    assert main(["init", str(project), "--force"]) == 0

    # the agent script runs as a plain python program with the mock model
    proc = subprocess.run(
        [sys.executable, "agent.py", "--model", "mock", "What is the capital of France?"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "The answer is Paris." in proc.stdout
    assert any((project / ".agentcore" / "traces").glob("*.jsonl"))

    # the eval suite passes, with the custom tool found through agentcore.toml
    monkeypatch.chdir(project)
    capsys.readouterr()
    report = project / "report.json"
    assert (
        main(["eval", "--suite", "evals/basic.yaml", "--model", "mock", "--output", str(report)])
        == 0
    )
    summary = json.loads(report.read_text())["summary"]
    assert summary["cases"] == 3 and summary["pass_rate"] == 1.0

    # chat picks up model + tools from the config file
    assert main(["chat", "-p", "What is the speed of light?"]) == 0
    assert "299,792,458" in capsys.readouterr().out
    assert main(["tools"]) == 0
    assert "lookup_fact [knowledge] (custom)" in capsys.readouterr().out


def test_config_file_and_precedence(tmp_path, monkeypatch):
    (tmp_path / "tools_mod.py").write_text(
        "from agentcore import tool\n\n"
        "@tool\n"
        "def ping() -> str:\n"
        '    """Reply with pong."""\n'
        '    return "pong"\n',
        encoding="utf-8",
    )
    (tmp_path / "agentcore.toml").write_text(
        'model = "mock"\n'
        'models = ["ollama:llama3.2"]\n'
        'tools = ["calculator", "ping"]\n'
        'tool_modules = ["tools_mod.py"]\n'
        'trace_dir = "data/traces"\n'
        'eval_dirs = ["suites"]\n'
        "[server]\n"
        "port = 8123\n"
        'cors_origins = ["http://localhost:3000"]\n'
        "max_body_kb = 64\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.model == "mock" and cfg.tools == ["calculator", "ping"]
    assert cfg.trace_dir == str(tmp_path / "data" / "traces")
    assert cfg.state_dir == str(tmp_path / "data")
    assert cfg.eval_dirs == [str(tmp_path / "suites")]
    assert cfg.server.port == 8123 and cfg.server.max_body_bytes == 64 * 1024
    assert cfg.server.cors_origins == ["http://localhost:3000"]
    assert list(load_tool_modules(cfg.tool_modules)) == ["ping"]

    monkeypatch.setenv("AGENTCORE_MODEL", "ollama:qwen2.5:7b")
    monkeypatch.setenv("AGENTCORE_API_KEY", "k-test")
    cfg = load_config()
    assert cfg.model == "ollama:qwen2.5:7b" and cfg.server.api_key == "k-test"
    assert "k-test" not in json.dumps(cfg.to_dict())

    (tmp_path / "bad.toml").write_text("unknown_key = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown config keys"):
        load_config(tmp_path / "bad.toml")
    (tmp_path / "secret.toml").write_text('[server]\napi_key = "x"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="AGENTCORE_API_KEY"):
        load_config(tmp_path / "secret.toml")
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.toml")


def test_config_drives_the_server(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agentcore.server import create_app

    (tmp_path / "agentcore.toml").write_text(
        'model = "mock"\ntools = ["current_time"]\nsystem_prompt = "Be terse."\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app(config=load_config()))
    health = client.get("/health").json()
    assert health["tools"] == ["current_time"] and health["model"] == "mock"
    assert client.get("/api/config").json()["config_file"].endswith("agentcore.toml")


def test_cli_rejects_bad_config(tmp_path, capsys, monkeypatch):
    (tmp_path / "agentcore.toml").write_text("model = [", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["tools"]) == 2
    assert "cannot read" in capsys.readouterr().err
    # doctor still runs and reports the problem
    assert main(["doctor", "--model", "mock", "--timeout", "0.2"]) == 1
    out = capsys.readouterr().out
    assert "config error" in out and "fail" in out


def test_doctor(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")  # nothing listens here
    assert main(["doctor", "--model", "mock", "--timeout", "0.2", "--ping"]) == 0
    out = capsys.readouterr().out
    assert "python" in out and "mock (offline, deterministic)" in out
    assert "ping" in out and "replied" in out
    assert "not reachable" in out  # ollama probe, informational only
    assert not (tmp_path / ".agentcore").exists()  # doctor does not create directories
    # an unreachable model is a failure
    assert main(["doctor", "--model", "ollama:qwen2.5:7b", "--timeout", "0.2"]) == 1
    assert "Ollama is not reachable" in capsys.readouterr().out
