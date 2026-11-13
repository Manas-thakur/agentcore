"""Regressions for the hands-on QA pass of v0.3.0 (install hints, CLI errors, eval suite
validation, graph timeouts, Docker defaults, OpenAI-compatible errors and more)."""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import time

import numpy as np
import pytest

from agentcore import Agent, tool
from agentcore.agents import SpecializedAgent
from agentcore.agents.patterns import Pipeline
from agentcore.cli import main
from agentcore.config import ConfigError, load_config, resolve_tools
from agentcore.eval import EvalCase, EvalRunner, EvalSuite, LLMAsJudge, load_suite
from agentcore.eval.suite import SuiteError
from agentcore.graph import END, START, StateGraph
from agentcore.index import FlatIndex, HNSWIndex, IVFIndex
from agentcore.index.quantization import PQIndex, SQIndex
from agentcore.obs.metrics import get_metrics
from agentcore.rag import RAGPipeline, load_file, load_path
from agentcore.runtime.model_client import ModelClient, ModelError
from agentcore.runtime.providers import MockModel, ScriptedModel
from agentcore.tools import (
    ExecutionEngine,
    RetryPolicy,
    SandboxConfig,
    ToolRegistry,
    ToolTransientError,
    calculator,
    current_time,
    make_python_exec,
)
from tests.conftest import EXAMPLES, ROOT, run

SUITE = EXAMPLES / "evals" / "calculator_suite.yaml"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("AGENTCORE_MODEL", "AGENTCORE_TOOLS", "AGENTCORE_API_KEY", "AGENTCORE_DEBUG"):
        monkeypatch.delenv(var, raising=False)


def write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- M1: install hints never point at PyPI's unrelated "agentcore" ------------------------


def test_install_hints_use_the_github_package():
    from agentcore._install import install_command, install_hint
    from agentcore.scaffold import README_MD

    assert install_command("server") == (
        'pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"'
    )
    assert install_command(None, ref="v0.3.0").endswith('agentcore@v0.3.0"')
    assert "not published on PyPI" in install_hint("otel")
    assert "git+https://github.com/Manas-thakur/agentcore" in README_MD

    # no file anywhere suggests installing the PyPI name
    pattern = re.compile(
        r"""(pip|uv)\s+(install|add)\s+(-U\s+)?["']?agentcore(\[[a-z,]+\])?["']?(\s|$)"""
    )
    files = [
        *(ROOT / "src").rglob("*.py"),
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        *(ROOT / "site" / "src").rglob("*.md"),
        *(ROOT / "site" / "src").rglob("*.astro"),
    ]
    offenders = [
        f"{f.relative_to(ROOT)}: {line.strip()}"
        for f in files
        for line in f.read_text(encoding="utf-8").splitlines()
        if pattern.search(line) and "git+" not in line
    ]
    assert offenders == []


def test_doctor_reports_missing_extras_with_github_install(monkeypatch):
    from agentcore import doctor
    from agentcore.config import Config

    monkeypatch.setattr(doctor, "_has", lambda m: m != "opentelemetry.sdk")
    checks = {c.name: c for c in doctor.run_checks(Config(), model="mock", timeout=0.2)}
    otel = checks["extra [otel]"]
    assert otel.status == "info" and "missing opentelemetry.sdk" in otel.detail
    assert "git+https://github.com/Manas-thakur/agentcore" in otel.detail


# --- M2 / m14: Docker image defaults ------------------------------------------------------


def test_dockerfile_runs_from_a_writable_dir_without_a_model_default():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = text.split("FROM python:3.12-slim\n", 1)[1]
    assert "WORKDIR /data" in runtime and "chown -R agent:agent /data" in runtime
    assert "AGENTCORE_MODEL=" not in runtime  # would override model in agentcore.toml


def test_starter_suite_reports_unwritable_eval_dir(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agentcore.server import create_app

    eval_dir = tmp_path / "evals"
    app = create_app(
        model="mock", trace_dir=str(tmp_path / "state" / "t"), eval_dirs=[str(eval_dir)]
    )
    real_mkdir = pathlib.Path.mkdir

    def deny(self, *args, **kwargs):
        if self == eval_dir:
            raise PermissionError(13, "Permission denied", str(self))
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "mkdir", deny)
    resp = TestClient(app).post("/api/evals/starter")
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "cannot write to" in detail and "permission denied" in detail
    assert "eval_dirs" in detail


# --- M3: --baseline must exist --------------------------------------------------------------


def test_eval_baseline_missing_is_an_error(tmp_path, capsys):
    base = tmp_path / "base.json"
    args = ["eval", "--suite", str(SUITE), "--model", "mock", "--no-trace", "--baseline", str(base)]
    assert main(args) == 2
    assert "not found" in capsys.readouterr().err
    assert main([*args, "--save-baseline"]) == 0 and base.exists()
    assert main(args) == 0
    assert "regress" in capsys.readouterr().out.lower()


# --- M4: strict suite validation ------------------------------------------------------------


def suite_yaml(cases: str, extra: str = "") -> str:
    return f"name: s\n{extra}cases:\n{cases}"


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("  - {name: a, input: x, expected_output: '1', match: fuzzy}", "invalid match 'fuzzy'"),
        ("  - {name: a, input: x, expectd_output: '1'}", "did you mean 'expected_output'"),
        ("  - {input: x, expected_output: '1'}", "needs a 'name'"),
        (
            "  - {name: a, input: x, expected_tool_calls: [{tol: calculator}]}",
            "did you mean 'tool'",
        ),
        (
            "  - {name: a, input: x, expected_tool_calls: [{tool: calculator, match: fuzzy}]}",
            "invalid match",
        ),
        ("  - {name: a, input: x, expected_output: '(', match: regex}", "invalid regex"),
        ("  - {name: a, input: x, rubric: 5}", "rubric must be"),
        ("  - {name: a}", "missing 'input'"),
    ],
)
def test_suite_validation_errors(tmp_path, case, message):
    path = write(tmp_path / "s.yaml", suite_yaml(case))
    with pytest.raises(SuiteError, match=re.escape(message)):
        load_suite(path)


def test_suite_rejects_unknown_top_level_and_agent_keys(tmp_path):
    with pytest.raises(SuiteError, match="allowed keys: name, description, agent, cases"):
        load_suite(write(tmp_path / "a.yaml", "name: s\ncase: []\n"))
    with pytest.raises(SuiteError, match="did you mean 'tools'"):
        load_suite(write(tmp_path / "b.yaml", "name: s\nagent: {tool: [calculator]}\ncases: []\n"))
    with pytest.raises(SuiteError, match="invalid YAML"):
        load_suite(write(tmp_path / "c.yaml", "name: [unclosed\n"))


def test_match_is_case_insensitive_and_metrics_apply(tmp_path):
    path = write(
        tmp_path / "s.yaml",
        suite_yaml("  - {name: a, input: 'What is 2 + 2?', expected_output: '5', match: Contains}"),
    )
    suite = load_suite(path)
    assert suite.cases[0].match == "contains"
    report = EvalRunner("mock").run_suite_sync(suite)
    run_ = report.runs[0]
    assert not run_.passed and [m.name for m in run_.metrics] == ["contains"]
    with pytest.raises(SuiteError):
        EvalCase("x", "q", expected_output="1", match="fuzzy")


def test_cases_without_checks_fail_instead_of_passing_silently():
    suite = EvalSuite(
        "s",
        [EvalCase("nothing", "What is 2 + 2?"), EvalCase("judge_only", "hi", rubric={"tone": 1})],
    )
    report = EvalRunner("mock").run_suite_sync(suite)
    by = {r.case.name: r for r in report.runs}
    assert not by["nothing"].passed and by["nothing"].score == 0.0
    assert by["nothing"].metrics[0].name == "no_checks"
    assert "--judge-model" in by["judge_only"].metrics[0].details


def test_discovery_lists_malformed_suites_but_skips_reports(tmp_path):
    from agentcore.server.evals import EvalManager

    d = tmp_path / "evals"
    write(d / "good.yaml", SUITE.read_text(encoding="utf-8"))
    write(d / "bad.yaml", suite_yaml("  - {name: a, input: x, match: fuzzy}"))
    write(d / "report.json", json.dumps({"summary": {}, "runs": []}))
    found = {s["path"].rsplit("/", 1)[-1]: s for s in EvalManager([str(d)], tmp_path).discover()}
    assert set(found) == {"good.yaml", "bad.yaml"}
    assert "invalid match" in found["bad.yaml"]["error"]


# --- M5: one-line CLI errors ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["chat", "--model", "bogus:x", "-p", "hi"], "unknown model spec 'bogus:x'"),
        (["chat", "--model", "openai:", "-p", "hi"], "needs a model name"),
        (["eval", "--suite", "missing.yaml", "--model", "mock"], "file not found: missing.yaml"),
        (["eval", "--suite", str(SUITE), "--replay", "nope.json"], "file not found: nope.json"),
        (["research", "topic", "--docs", "no-such-dir", "--model", "mock"], "no such file"),
    ],
)
def test_cli_reports_ordinary_mistakes_without_traceback(
    tmp_path, monkeypatch, capsys, argv, message
):
    monkeypatch.chdir(tmp_path)
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and message in err and "Traceback" not in err


def test_cli_errors_for_bad_yaml_unknown_tools_and_missing_modules(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "bad.yaml", "name: [unclosed\n")
    assert main(["eval", "--suite", "bad.yaml", "--model", "mock"]) == 2
    assert "invalid YAML" in capsys.readouterr().err

    write(tmp_path / "agentcore.toml", 'tools = ["calculator", "nope"]\n')
    assert main(["chat", "--model", "mock", "-p", "hi"]) == 2
    assert "unknown tool 'nope'" in capsys.readouterr().err

    write(tmp_path / "agentcore.toml", 'tool_modules = ["missing_tools.py"]\n')
    assert main(["chat", "--model", "mock", "-p", "hi"]) == 2
    assert "tool module not found" in capsys.readouterr().err


def test_cli_model_server_down_is_one_line(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    assert main(["chat", "--model", "ollama:qwen", "-p", "hi", "--tools", ""]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "Traceback" not in err


def test_cli_debug_flag_shows_traceback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="unknown model spec"):
        main(["--debug", "chat", "--model", "bogus:x", "-p", "hi"])
    with pytest.raises(ValueError, match="unknown model spec"):
        main(["chat", "--model", "bogus:x", "-p", "hi", "--debug"])


# --- M6 / m10: graph timeouts, concurrency, routing -------------------------------------------


def test_sync_node_timeout_is_enforced():
    def slow(state):
        time.sleep(1.5)
        return {"done": True}

    g = StateGraph("t").add_node("slow", slow, timeout=0.2)
    g.add_edge(START, "slow").add_edge("slow", END)
    t0 = time.perf_counter()
    result = g.compile().run_sync({})
    elapsed = time.perf_counter() - t0
    assert result.status == "failed" and elapsed < 1.2
    assert "timed out after 0.2s" in result.error


def test_async_node_timeout_has_a_useful_message():
    async def slow(state):
        await asyncio.sleep(2)

    g = StateGraph("t").add_node("slow", slow, timeout=0.1)
    g.add_edge(START, "slow").add_edge("slow", END)
    result = g.compile().run_sync({})
    assert result.status == "failed" and result.failed_node == "slow"
    assert result.error == "node 'slow' failed: TimeoutError: node 'slow' timed out after 0.1s"


def test_sync_fan_out_runs_concurrently():
    def worker(name):
        def fn(state):
            time.sleep(0.4)
            return {"seen": [name]}

        return fn

    from agentcore.graph import append

    g = StateGraph("fan", reducers={"seen": append})
    for n in ("a", "b", "c"):
        g.add_node(n, worker(n))
    g.add_node("start", lambda s: None)
    g.add_edge(START, "start").add_edge("start", ["a", "b", "c"]).add_edge(["a", "b", "c"], END)
    t0 = time.perf_counter()
    result = g.compile().run_sync({})
    elapsed = time.perf_counter() - t0
    assert result.status == "completed" and sorted(result.state["seen"]) == ["a", "b", "c"]
    assert elapsed < 1.0  # serial would be >= 1.2s


def test_conditional_edge_can_fan_out_and_unmapped_keys_fail_cleanly():
    from agentcore.graph import append

    g = StateGraph("route", reducers={"seen": append})
    g.add_node("router", lambda s: None)
    g.add_node("x", lambda s: {"seen": ["x"]})
    g.add_node("y", lambda s: {"seen": ["y"]})
    g.add_edge(START, "router")
    g.add_conditional_edges("router", lambda s: s["route"], {"both": ["x", "y"], "only_x": "x"})
    g.add_edge("x", END).add_edge("y", END)
    app = g.compile()
    both = app.run_sync({"route": "both"})
    assert both.status == "completed" and sorted(both.state["seen"]) == ["x", "y"]
    bad = app.run_sync({"route": "nowhere"})
    assert bad.status == "failed" and bad.failed_node == "router"
    assert "'nowhere'" in bad.error and "path_map" in bad.error
    assert 'router -.->|"both"| y' in app.to_mermaid()


def test_interrupt_works_in_sync_nodes_running_in_threads():
    from agentcore.graph import interrupt

    def ask(state):
        return {"answer": interrupt("name?")}

    g = StateGraph("ask").add_node("ask", ask)
    g.add_edge(START, "ask").add_edge("ask", END)
    app = g.compile()
    first = app.run_sync({}, thread_id="t1")
    assert first.status == "interrupted" and first.interrupt["payload"] == "name?"
    assert app.resume_sync("t1", "Ada").state["answer"] == "Ada"


# --- m1: model errors end the run with stop_reason="error" -----------------------------------


class FailingModel(ModelClient):
    provider = "failing"

    async def generate(self, messages, tools=None, *, temperature=0.0, max_tokens=None):
        raise ModelError("HTTP 500: upstream exploded")


def test_agent_returns_error_result_on_model_failure():
    result = Agent(FailingModel("x")).run_sync("hi")
    assert result.stop_reason == "error" and result.output == ""
    assert result.error == "ModelError: HTTP 500: upstream exploded"
    assert [e.type for e in result.events][-2:] == ["error", "run_end"]
    with pytest.raises(ModelError):
        Agent(FailingModel("x"), raise_on_error=True).run_sync("hi")
    # exhausted scripted models report the same way
    assert Agent(ScriptedModel([])).run_sync("hi").stop_reason == "error"


# --- m2: rubric forms and judge scope ---------------------------------------------------------


def test_rubric_list_form_and_mock_judge(tmp_path):
    path = write(
        tmp_path / "r.yaml",
        suite_yaml(
            "  - name: judged\n    input: 'What is 2 + 2?'\n    expected_output: '4'\n"
            "    rubric:\n      - {criterion: correctness, weight: 2}\n      - clarity\n"
            "  - {name: plain, input: 'What is 3 + 3?', expected_output: '6'}\n"
        ),
    )
    suite = load_suite(path)
    assert suite.cases[0].rubric == {"correctness": 2.0, "clarity": 1.0}
    report = EvalRunner("mock", judge=MockModel()).run_suite_sync(suite)
    by = {r.case.name: r for r in report.runs}
    judged = {m.name: m for m in by["judged"].metrics}["llm_judge"]
    assert judged.passed and judged.score == 1.0 and judged.breakdown["scores"]["clarity"] == 10
    assert "llm_judge" not in {m.name for m in by["plain"].metrics}  # no rubric: not judged
    everything = EvalRunner("mock", judge=MockModel(), judge_all=True).run_suite_sync(suite)
    assert all("llm_judge" in {m.name for m in r.metrics} for r in everything.runs)
    assert LLMAsJudge(MockModel(), [{"criterion": "a", "weight": 1}]).rubric == {"a": 1.0}


# --- m3 / m4: concurrency and --fail-under ----------------------------------------------------


def test_concurrency_must_be_positive(capsys):
    with pytest.raises(ValueError, match="concurrency"):
        EvalRunner("mock", concurrency=0)
    with pytest.raises(SystemExit) as exit_info:
        main(["eval", "--suite", str(SUITE), "--concurrency", "0"])
    assert exit_info.value.code == 2


def test_fail_under_sets_the_pass_rate_threshold(tmp_path, capsys):
    path = write(
        tmp_path / "half.yaml",
        suite_yaml(
            "  - {name: ok, input: 'What is 2 + 2?', expected_output: '4'}\n"
            "  - {name: bad, input: 'What is 2 + 2?', expected_output: '5'}\n"
        ),
    )
    base = ["eval", "--suite", str(path), "--model", "mock", "--no-trace"]
    assert main(base) == 1  # default 1.0: every case must pass
    assert "below --fail-under" in capsys.readouterr().err
    assert main([*base, "--fail-under", "0.5"]) == 0
    assert main([*base, "--fail-under", "2"]) == 2


# --- m5 / m6 / m7: tools ---------------------------------------------------------------------


def test_engine_hooks_accept_a_single_callable():
    seen = []
    engine = ExecutionEngine(
        ToolRegistry([calculator]),
        before=lambda name, kwargs: seen.append(("before", name)),
        after=lambda result: seen.append(("after", result.success)),
    )
    assert run(engine.execute("calculator", {"expression": "1+1"})).output == "2"
    assert seen == [("before", "calculator"), ("after", True)]


def test_explicit_zero_retries_is_respected():
    calls = {"n": 0}

    def flaky() -> str:
        """Always fails transiently."""
        calls["n"] += 1
        raise ToolTransientError("try again")

    policy = RetryPolicy(base_delay_s=0)
    never = ExecutionEngine(ToolRegistry([tool(retries=0)(flaky)]), retry_policy=policy)
    assert run(never.execute("flaky", {})).attempts == 1 and calls["n"] == 1
    default = ExecutionEngine(ToolRegistry([tool(flaky)]), retry_policy=policy)
    assert run(default.execute("flaky", {})).attempts == 3


def test_python_exec_timeout_is_a_failure():
    py = make_python_exec(SandboxConfig(timeout_seconds=1))
    res = run(
        ExecutionEngine(ToolRegistry([py])).execute("python_exec", {"code": "while True: pass"})
    )
    assert not res.success and res.error_type == "ToolTimeoutError" and res.attempts == 1
    assert "did not finish within 1s" in res.error


def test_builtin_python_exec_blocks_os_access_by_default():
    engine = ExecutionEngine(ToolRegistry(resolve_tools(["python_exec"])))
    blocked = run(engine.execute("python_exec", {"code": "import os\nos.system('echo hi')"}))
    assert blocked.success and "import of 'os' is not allowed" in blocked.output
    for code in ("import subprocess", "from shutil import rmtree", "import socket"):
        assert "not allowed" in run(engine.execute("python_exec", {"code": code})).output
    # the standard library's own imports (random -> os) still work
    ok = run(
        engine.execute("python_exec", {"code": "import random, json\nprint(random.randint(3, 3))"})
    )
    assert ok.output.strip() == "3"
    open_ = make_python_exec(SandboxConfig(blocked_imports=[]))
    res = run(
        ExecutionEngine(ToolRegistry([open_])).execute(
            "python_exec", {"code": "import os\nprint(os.sep in '/\\\\')"}
        )
    )
    assert res.output.strip() == "True"


# --- m8: RAG ----------------------------------------------------------------------------------


def test_rag_answers_without_a_model_and_reads_front_matter_and_mdx(tmp_path):
    write(
        tmp_path / "docs" / "guide.md",
        "---\ntitle: Install Guide\ndescription: how to install\n---\n# Heading\n\n"
        "AgentCore installs from GitHub with pip and git.\n",
    )
    write(
        tmp_path / "docs" / "deep" / "page.mdx",
        'import Tabs from "./tabs"\nexport const meta = {}\n\n# Page\n\n'
        '<Callout type="tip">The sandbox blocks network access by default.</Callout>\n'
        '<img src="x.png" alt="Diagram of the sandbox" />\n',
    )
    docs = load_path(tmp_path / "docs")
    by_name = {pathlib.Path(d.source).name: d for d in docs}
    guide, page = by_name["guide.md"], by_name["page.mdx"]
    assert guide.metadata["title"] == "Install Guide" and "title:" not in guide.content
    assert "\\" not in page.source and page.source.endswith("docs/deep/page.mdx")
    assert "import Tabs" not in page.content and "<Callout" not in page.content
    assert "blocks network access" in page.content and "Diagram of the sandbox" in page.content
    pipe = RAGPipeline()
    pipe.add_documents(docs)
    answer = pipe.answer_sync("Does the sandbox block network access?")
    assert "network access" in answer.text and answer.citations
    assert load_file(tmp_path / "docs" / "guide.md")[0].title == "Install Guide"


# --- m9: index filters and duplicate ids --------------------------------------------------------


@pytest.mark.parametrize("cls", [FlatIndex, HNSWIndex, IVFIndex, SQIndex, PQIndex])
def test_index_dict_filters_and_duplicate_ids(cls):
    kwargs = {"nlist": 2} if cls is IVFIndex else {"m": 2, "ksub": 4} if cls is PQIndex else {}
    rng = np.random.default_rng(0)
    vecs = rng.normal(size=(8, 4)).astype("float32")
    ids = ["a", "b", "c", "d", "e", "f", "g", "a"]  # "a" twice: the last one wins
    meta = [{"lang": "en" if i % 2 else "de", "n": i} for i in range(8)]
    idx = cls(4, **kwargs)
    idx.add(vecs, ids, meta)
    assert len(idx) == 7 and idx.metadata["a"]["n"] == 7
    hits = idx.search(vecs[7], k=10)
    assert [h.id for h in hits].count("a") == 1
    en = idx.search(vecs[0], k=10, filter={"lang": "en"})
    assert en and all(h.metadata["lang"] == "en" for h in en)
    some = idx.search(vecs[0], k=10, filter={"n": [1, 3]})
    assert {h.id for h in some} <= {"b", "d"}
    assert {h.id for h in idx.search(vecs[0], k=10, filter=lambda i, m: i == "c")} <= {"c"}


# --- m11: specialized agents and pipelines ------------------------------------------------------


def test_string_system_prompt_and_pipeline_failures():
    class Echo(SpecializedAgent):
        name = "echo"
        system_prompt = "You repeat things."

    out = run(Echo(MockModel()).run("What is 2 + 2?"))
    assert out.success and out.output == "The answer is 4."
    assert Echo(MockModel()).make_agent().config.system_prompt == "You repeat things."

    class Broken(SpecializedAgent):
        name = "broken"

        def make_agent(self):
            raise RuntimeError("no model configured")

    result = run(Pipeline([Broken(MockModel()), Echo(MockModel())]).run("hi"))
    assert not result.success and result.output == ""
    assert result.error == "broken failed: RuntimeError: no model configured"
    assert "echo" not in result.results


# --- m12: OpenAI-compatible errors --------------------------------------------------------------


@pytest.fixture
def oai_client(tmp_path):
    from fastapi.testclient import TestClient

    from agentcore.server import create_app

    return TestClient(
        create_app(model="mock", trace_dir=str(tmp_path / "t"), eval_dirs=[str(tmp_path)])
    )


def test_chat_completions_errors_are_openai_shaped(oai_client):
    def post(body):
        return oai_client.post("/v1/chat/completions", json=body)

    missing = post({"model": "mock"})
    assert missing.status_code == 400
    err = missing.json()["error"]
    assert set(err) == {"message", "type", "param", "code"} and err["param"] == "messages"
    assert err["type"] == "invalid_request_error"
    role = post({"messages": [{"role": "wizard", "content": "hi"}]})
    assert role.status_code == 400 and role.json()["error"]["param"] == "messages.0.role"
    many = post({"n": 2, "messages": [{"role": "user", "content": "hi"}]})
    assert many.status_code == 400 and many.json()["error"]["param"] == "n"
    ignored = post(
        {"tools": [{"type": "function"}], "messages": [{"role": "user", "content": "2+2"}]}
    )
    assert ignored.status_code == 200
    # other routes keep FastAPI's validation format
    assert "detail" in oai_client.post("/api/chat", json={}).json()


def test_chat_completions_upstream_failure_is_502(tmp_path):
    from fastapi.testclient import TestClient

    from agentcore.server import create_app

    client = TestClient(create_app(model=FailingModel("x"), trace_dir=str(tmp_path / "t")))
    body = {"messages": [{"role": "user", "content": "hi"}]}
    resp = client.post("/v1/chat/completions", json=body)
    assert resp.status_code == 502 and resp.json()["error"]["type"] == "server_error"
    with client.stream("POST", "/v1/chat/completions", json={**body, "stream": True}) as s:
        text = "".join(s.iter_text())
    error_line = next(line for line in text.splitlines() if '"error"' in line)
    payload = json.loads(error_line[len("data: ") :])
    assert payload["error"]["type"] == "server_error"
    assert "upstream exploded" in payload["error"]["message"]


def test_streamed_http_errors_are_decoded_text():
    import httpx

    from agentcore.runtime.providers import OpenAICompatibleClient
    from agentcore.types import Message

    transport = httpx.MockTransport(lambda req: httpx.Response(500, text="model overloaded"))
    client = OpenAICompatibleClient("x", base_url="http://test", transport=transport)

    async def consume():
        async for _ in client.stream([Message.user("hi")]):
            pass

    with pytest.raises(ModelError) as info:
        run(consume())
    assert str(info.value) == "HTTP 500: model overloaded"


# --- m13 / m15 / m16: config, ports and suite names --------------------------------------------


def test_serve_reports_the_actual_port_and_custom_tools(tmp_path, monkeypatch):
    import uvicorn
    from fastapi.testclient import TestClient

    write(
        tmp_path / "tools.py",
        "from agentcore import tool\nfrom agentcore.tools import calculator\n\n"
        "@tool\ndef shout(text: str) -> str:\n    '''Shout.\n\n    Args:\n        text: x\n    '''\n"
        "    return text.upper()\n",
    )
    write(tmp_path / "agentcore.toml", 'tool_modules = ["tools.py"]\nmodel = "mock"\n')
    monkeypatch.chdir(tmp_path)
    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update(app=app, **kw))
    assert main(["serve", "--port", "8862", "--trace-dir", str(tmp_path / "t")]) == 0
    cfg = TestClient(captured["app"]).get("/api/config").json()
    assert captured["port"] == 8862 and cfg["server"]["port"] == 8862
    assert cfg["custom_tools"] == ["shout"]  # the re-exported calculator is a built-in
    tools = {t["name"]: t for t in TestClient(captured["app"]).get("/api/tools").json()}
    assert tools["calculator"]["timeout"] == 5 and tools["calculator"]["source"] == "builtin"


def test_server_section_keys_are_validated(tmp_path):
    with pytest.raises(ConfigError, match="did you mean 'port'"):
        load_config(write(tmp_path / "a.toml", "[server]\nprot = 9000\n"))
    with pytest.raises(ConfigError, match="between 1 and 65535"):
        load_config(write(tmp_path / "b.toml", "[server]\nport = 0\n"))


def test_duplicate_suite_names_are_ambiguous_and_404_hides_paths(tmp_path):
    from fastapi.testclient import TestClient

    from agentcore.server import create_app

    d = tmp_path / "evals"
    write(d / "one.yaml", SUITE.read_text(encoding="utf-8"))
    write(d / "nested" / "two.yaml", SUITE.read_text(encoding="utf-8"))
    client = TestClient(create_app(model="mock", trace_dir=str(tmp_path / "t"), eval_dirs=[str(d)]))
    suites = client.get("/api/evals/suites").json()
    assert all(s["duplicate_name"] for s in suites)
    amb = client.post("/api/evals/runs", json={"suite": "calculator-basic"})
    assert amb.status_code == 409 and "run one by its path" in amb.json()["detail"]
    assert client.post("/api/evals/runs", json={"suite": suites[0]["path"]}).status_code == 202
    missing = client.post("/api/evals/runs", json={"suite": "nope"})
    assert missing.status_code == 404 and str(tmp_path) not in missing.json()["detail"]
    assert tmp_path.as_posix() not in missing.json()["detail"]


# --- m17: observability -------------------------------------------------------------------------


def test_eval_metrics_use_a_bounded_agent_label():
    EvalRunner("mock").run_suite_sync(load_suite(SUITE))
    text = get_metrics().export_prometheus()
    assert 'agentcore_agent_runs_total{agent="eval"} 5' in text
    assert "eval:multiply_add" not in text


def test_cli_eval_writes_eval_traces(tmp_path, capsys):
    traces = tmp_path / "traces"
    md = tmp_path / "out" / "report.md"
    args = ["eval", "--suite", str(SUITE), "--model", "mock", "--trace-dir", str(traces)]
    assert main([*args, "--markdown", str(md)]) == 0
    assert f"markdown report written to {md}" in capsys.readouterr().out
    from agentcore.obs.storage import JSONLTraceStore

    names = {s.name for s in JSONLTraceStore(str(traces)).list(None)}
    assert "agent.run:eval:multiply_add" in names


def test_otel_trace_ids_match_agentcore_trace_ids():
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from agentcore.obs.tracing import InMemoryExporter, Tracer

    provider = TracerProvider()
    otel_spans = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(otel_spans))
    ours = InMemoryExporter()
    tracer = Tracer([ours])
    tracer._otel_tracer = provider.get_tracer("test")
    with tracer.span("root") as root, tracer.span("child") as child:
        pass
    assert child.trace_id == root.trace_id
    finished = {s.name: s for s in otel_spans.get_finished_spans()}
    assert format(finished["root"].context.trace_id, "032x") == root.trace_id
    assert finished["child"].attributes["agentcore.trace_id"] == root.trace_id


# --- m18: mock model ----------------------------------------------------------------------------


def test_mock_lookup_miss_and_reflection():
    @tool
    def lookup_fact(query: str) -> str:
        """Look up a fact.

        Args:
            query: What to look up.
        """
        return "No matching fact found."

    out = Agent(MockModel(), tools=[lookup_fact]).run_sync("Look up the moon's mass").output
    assert out == "I could not find an answer with lookup_fact: No matching fact found."
    reflective = Agent(MockModel(), tools=[calculator], reflect_every=1).run_sync("What is 5*5?")
    assert reflective.output == "The answer is 25." and reflective.stop_reason == "final"


# --- m19 / d3: cosmetics --------------------------------------------------------------------------


def test_cosmetics(tmp_path, capsys):
    from agentcore.server.evals import STARTER_SUITE_YAML

    assert current_time.name == "current_time"
    assert "dashboard" not in STARTER_SUITE_YAML and "web app" in STARTER_SUITE_YAML
    with pytest.raises(SystemExit) as info:
        main(["traces", "--dir", str(tmp_path), "list", "--limit", "0"])
    assert info.value.code == 2 and "must be >= 1" in capsys.readouterr().err


def test_chat_verbose_stream_puts_the_summary_on_its_own_line(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["chat", "--model", "mock", "--stream", "-v", "-p", "What is 6 * 7?"]) == 0
    captured = capsys.readouterr()
    assert captured.out.endswith("The answer is 42.\n")
    assert captured.err.rstrip().splitlines()[-1].startswith("  [final,")


def test_eval_run_elapsed_is_set_after_completion(tmp_path):
    from fastapi.testclient import TestClient

    from agentcore.server import create_app

    client = TestClient(
        create_app(model="mock", trace_dir=str(tmp_path / "t"), eval_dirs=[str(SUITE.parent)])
    )
    with client:
        job = client.post("/api/evals/runs", json={"suite": "calculator-basic"}).json()
        for _ in range(100):
            data = client.get(f"/api/evals/runs/{job['id']}").json()
            if data["status"] == "completed":
                break
            time.sleep(0.05)
    assert data["status"] == "completed" and data["done"] == data["total"] == 5
    assert isinstance(data["elapsed_s"], float) and data["elapsed_s"] >= 0


def test_explore_stats_follow_the_query(tmp_path):
    from fastapi.testclient import TestClient

    from agentcore.server import create_app

    client = TestClient(create_app(model="mock", trace_dir=str(tmp_path / "t")))
    for q in ("What is 1 + 1?", "What is 2 + 2?"):
        client.post("/v1/agent", json={"input": q})
    client.post("/api/tools/calculator/invoke", json={"arguments": {"expression": "1+1"}})
    everything = client.get("/api/traces/explore").json()
    tools = client.get("/api/traces/explore", params={"query": "kind:tool"}).json()
    assert everything["stats"]["count"] == 3
    assert tools["total"] == tools["stats"]["count"] == 1
