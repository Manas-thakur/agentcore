from __future__ import annotations

import json

from agentcore.eval import (
    Contains,
    EvalCase,
    EvalRun,
    EvalRunner,
    EvalSuite,
    ExactMatch,
    LLMAsJudge,
    RegexMatch,
    ToolCallExpectation,
    ToolCallMatch,
    Trajectory,
    TrajectoryMatch,
    TrajectoryRecorder,
    compare,
    load_suite,
)
from agentcore.eval.trajectory import Step
from agentcore.runtime import Agent, MockModel, ScriptedModel
from agentcore.tools import calculator
from agentcore.types import Message, ToolCall
from tests.conftest import EXAMPLES, run

SUITE = EXAMPLES / "evals" / "calculator_suite.yaml"


def make_run(output: str, tools: list[tuple[str, dict]] = ()) -> EvalRun:
    traj = Trajectory([Step("tool_call", tool_name=n, arguments=a) for n, a in tools], output)
    return EvalRun(EvalCase("c", "q"), output=output, trajectory=traj, steps=2, stop_reason="final")


def test_load_suite_yaml():
    suite = load_suite(SUITE)
    assert suite.name == "calculator-basic" and len(suite.cases) == 5
    assert suite.agent.tools == ["calculator"]
    case = suite.cases[0]
    assert case.expected_tool_calls[0] == ToolCallExpectation(
        "calculator", {"expression": "17 * 23 + 4"}, "subset"
    )
    assert suite.cases[1].expected_tool_calls[0].match == "any"
    assert len(suite.filter(tags=["float"]).cases) == 1


def test_output_metrics():
    case = EvalCase("c", "q", expected_output="395", match="contains")
    assert run(Contains().evaluate(case, make_run("The answer is 395."))).passed
    assert not run(Contains().evaluate(case, make_run("It is 394"))).passed
    exact = EvalCase("c", "q", expected_output="Paris", match="exact")
    assert run(ExactMatch().evaluate(exact, make_run("paris."))).passed
    rx = EvalCase("c", "q", expected_output=r"3\.14\d*", match="regex")
    assert run(RegexMatch().evaluate(rx, make_run("about 3.1428"))).passed
    alt = EvalCase("c", "q", expected_output="yes || correct")
    assert run(Contains().evaluate(alt, make_run("That is correct"))).passed


def test_tool_call_and_trajectory_metrics():
    case = EvalCase(
        "c",
        "q",
        expected_tool_calls=[
            ToolCallExpectation("search", {"query": "hnsw"}),
            ToolCallExpectation("calculator", match="any", max_count=1),
        ],
        expected_trajectory=["search", "calculator"],
    )
    good = make_run(
        "x", [("search", {"query": "HNSW", "k": 3}), ("calculator", {"expression": "1"})]
    )
    res = run(ToolCallMatch().evaluate(case, good))
    assert res.score == 1.0 and res.passed
    bad = make_run("x", [("calculator", {}), ("calculator", {})])
    res = run(ToolCallMatch().evaluate(case, bad))
    assert res.score == 0.0 and not res.passed
    assert run(TrajectoryMatch().evaluate(case, good)).score == 1.0
    partial = run(TrajectoryMatch().evaluate(case, make_run("x", [("calculator", {})])))
    assert partial.score == 0.5


def test_llm_as_judge():
    judge = ScriptedModel(
        [
            'Sure: {"scores": {"correctness": 9, "clarity": 7}, "reasoning": "mostly right"}',
            "garbage",
        ]
    )
    metric = LLMAsJudge(judge, rubric={"correctness": 0.5, "clarity": 0.5}, threshold=0.7)
    case = EvalCase("c", "What is 2+2?", expected_output="4")
    res = run(metric.evaluate(case, make_run("4")))
    assert res.score == 0.8 and res.passed and res.breakdown["scores"]["correctness"] == 9
    prompt = judge.calls[0]["messages"][0].content
    assert "Reference answer:\n4" in prompt and "- correctness" in prompt
    res = run(metric.evaluate(case, make_run("4")))
    assert not res.passed and "unparseable" in res.details


def test_trajectory_recorder():
    rec = TrajectoryRecorder()
    model = ScriptedModel(
        [Message.assistant("thinking", [ToolCall("calculator", {"expression": "2*3"})]), "6"]
    )
    Agent(model, tools=[calculator]).run_sync("2*3", callbacks=[rec])
    traj = rec.get_trajectory()
    assert [s.type for s in traj.steps] == ["thought", "tool_call", "tool_result", "output"]
    assert traj.tool_names == ["calculator"] and traj.output == "6"
    assert "A->>T: calculator" in traj.to_mermaid()
    assert Trajectory.from_dict(json.loads(json.dumps(traj.to_dict()))).tool_names == ["calculator"]


def test_runner_on_example_suite_with_mock():
    report = EvalRunner("mock").run_suite_sync(load_suite(SUITE))
    s = report.summary()
    assert s["cases"] == 5 and s["passed"] == 5 and s["pass_rate"] == 1.0
    assert set(s["metrics"]) >= {"contains", "tool_calls", "trajectory", "regex", "step_budget"}
    md = report.to_markdown()
    assert "| multiply_add | PASS |" in md and "5/5 passed" in md


def test_runner_reports_failures_and_crashes():
    suite = EvalSuite(
        "s",
        [
            EvalCase("wrong", "What is 2 + 2?", expected_output="5"),
            EvalCase("boom", "hello"),
        ],
    )

    def factory(model, case, suite):
        if case.name == "boom":
            raise RuntimeError("factory exploded")
        return Agent(model, tools=[calculator])

    report = EvalRunner(MockModel, agent_factory=factory).run_suite_sync(suite)
    by = {r.case.name: r for r in report.runs}
    assert not by["wrong"].passed and by["wrong"].metrics[0].score == 0.0
    assert not by["boom"].passed and "factory exploded" in by["boom"].error
    assert report.summary()["failed"] == 2
    assert "### Failures" in report.to_markdown()


def test_record_and_replay_are_deterministic(tmp_path):
    suite = load_suite(SUITE)
    cassette = tmp_path / "cassette.json"
    recorded = EvalRunner("mock", record_to=cassette).run_suite_sync(suite)
    assert cassette.exists()
    data = json.loads(cassette.read_text())
    assert set(data["cases"]) == {c.name for c in suite.cases}
    replayed = EvalRunner(replay_from=cassette, strict_replay=True).run_suite_sync(suite)
    assert replayed.model.startswith("replay:")
    assert [r.output for r in replayed.runs] == [r.output for r in recorded.runs]
    assert replayed.summary()["pass_rate"] == 1.0


def test_regression_detection():
    suite = load_suite(SUITE)
    baseline = EvalRunner("mock").run_suite_sync(suite)

    # degrade the agent: drop the calculator tool so expectations break
    def no_tools(model, case, suite):
        return Agent(model, tools=[])

    current = EvalRunner("mock", agent_factory=no_tools).run_suite_sync(suite)
    diff = compare(baseline.to_dict(), current, threshold=0.05)
    assert diff.has_regressions
    assert "multiply_add" in diff.new_failures
    assert any(c.metric == "tool_calls" for c in diff.regressions)
    assert "REGRESSION" in diff.to_markdown()
    same = compare(baseline, baseline)
    assert not same.has_regressions and "No regressions." in same.to_markdown()
