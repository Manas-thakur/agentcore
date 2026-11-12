"""Eval metrics: output matching, tool-call/trajectory matching, efficiency, LLM-as-judge."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentcore.eval.suite import EvalCase, ToolCallExpectation
from agentcore.runtime.model_client import ModelClient
from agentcore.types import Message

if TYPE_CHECKING:
    from agentcore.eval.runner import EvalRun


@dataclass
class MetricResult:
    name: str
    score: float
    passed: bool
    threshold: float = 1.0
    details: str = ""
    breakdown: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "passed": self.passed,
            "threshold": self.threshold,
            "details": self.details,
            "breakdown": self.breakdown,
        }


class EvalMetric(ABC):
    name = "metric"
    threshold = 1.0

    @abstractmethod
    async def evaluate(self, case: EvalCase, run: EvalRun) -> MetricResult: ...

    def applies_to(self, case: EvalCase) -> bool:
        return True

    def _result(self, score: float, details: str = "", **breakdown: Any) -> MetricResult:
        return MetricResult(
            self.name, score, score >= self.threshold, self.threshold, details, breakdown
        )


def _norm(text: str) -> str:
    return " ".join(text.lower().split()).strip(" .")


class ExactMatch(EvalMetric):
    name = "exact_match"

    def applies_to(self, case: EvalCase) -> bool:
        return case.expected_output is not None and case.match == "exact"

    async def evaluate(self, case: EvalCase, run: EvalRun) -> MetricResult:
        ok = _norm(run.output or "") == _norm(case.expected_output or "")
        return self._result(1.0 if ok else 0.0, f"expected {case.expected_output!r}")


class Contains(EvalMetric):
    """Expected text appears in the output (case/whitespace-insensitive). ``a || b`` = either."""

    name = "contains"

    def applies_to(self, case: EvalCase) -> bool:
        return case.expected_output is not None and case.match == "contains"

    async def evaluate(self, case: EvalCase, run: EvalRun) -> MetricResult:
        expected = case.expected_output or ""
        options = [o.strip() for o in expected.split("||")] if "||" in expected else [expected]
        out = _norm(run.output or "")
        ok = any(_norm(o) in out for o in options)
        return self._result(1.0 if ok else 0.0, f"expected output to contain {expected!r}")


class RegexMatch(EvalMetric):
    name = "regex"

    def applies_to(self, case: EvalCase) -> bool:
        return case.expected_output is not None and case.match == "regex"

    async def evaluate(self, case: EvalCase, run: EvalRun) -> MetricResult:
        ok = re.search(case.expected_output or "", run.output or "", re.I | re.S) is not None
        return self._result(1.0 if ok else 0.0, f"pattern {case.expected_output!r}")


def _args_match(expected: ToolCallExpectation, actual: dict[str, Any]) -> bool:
    if expected.match == "any":
        return True

    def eq(a: Any, b: Any) -> bool:
        if isinstance(a, str) and isinstance(b, str):
            return _norm(a).replace(" ", "") == _norm(b).replace(" ", "")
        return a == b

    if expected.match == "exact":
        return set(expected.args) == set(actual) and all(
            eq(v, actual[k]) for k, v in expected.args.items()
        )
    return all(k in actual and eq(v, actual[k]) for k, v in expected.args.items())


class ToolCallMatch(EvalMetric):
    """Fraction of expected tool calls that were made with matching arguments and counts."""

    name = "tool_calls"

    def applies_to(self, case: EvalCase) -> bool:
        return bool(case.expected_tool_calls)

    async def evaluate(self, case: EvalCase, run: EvalRun) -> MetricResult:
        calls = run.trajectory.tool_calls
        hits, notes = 0, []
        for exp in case.expected_tool_calls:
            n = sum(
                1 for c in calls if c.tool_name == exp.tool and _args_match(exp, c.arguments or {})
            )
            ok = n >= exp.min_count and (exp.max_count is None or n <= exp.max_count)
            hits += ok
            notes.append(f"{exp.tool}: {n} matching call(s){'' if ok else ' (FAIL)'}")
        score = hits / len(case.expected_tool_calls)
        return self._result(score, "; ".join(notes), actual=[c.tool_name for c in calls])


def _lcs(a: list[str], b: list[str]) -> int:
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            dp[i + 1][j + 1] = dp[i][j] + 1 if x == y else max(dp[i][j + 1], dp[i + 1][j])
    return dp[-1][-1]


class TrajectoryMatch(EvalMetric):
    """Ordered tool sequence similarity: LCS(expected, actual) / max(len(expected), len(actual))."""

    name = "trajectory"

    def applies_to(self, case: EvalCase) -> bool:
        return bool(case.expected_trajectory)

    async def evaluate(self, case: EvalCase, run: EvalRun) -> MetricResult:
        exp, act = case.expected_trajectory, run.trajectory.tool_names
        score = _lcs(exp, act) / max(len(exp), len(act), 1)
        return self._result(score, f"expected {exp}, got {act}")


class StepBudget(EvalMetric):
    """Passes if the agent finished within ``case.max_steps`` model calls."""

    name = "step_budget"

    def applies_to(self, case: EvalCase) -> bool:
        return case.max_steps is not None

    async def evaluate(self, case: EvalCase, run: EvalRun) -> MetricResult:
        ok = run.steps <= (case.max_steps or 0) and run.stop_reason == "final"
        return self._result(1.0 if ok else 0.0, f"{run.steps} steps (budget {case.max_steps})")


JUDGE_PROMPT = """You are an impartial judge grading an AI assistant's answer.

Task given to the assistant:
{task}

{reference}Assistant's answer:
{answer}

Score each criterion from 0 to 10:
{criteria}

Respond with ONLY a JSON object: {{"scores": {{"<criterion>": <0-10>, ...}}, "reasoning": "<one sentence>"}}"""


def parse_judge_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class LLMAsJudge(EvalMetric):
    """Rubric-based grading by a (separate) judge model. Score = weighted mean / 10."""

    name = "llm_judge"

    def __init__(
        self, judge: ModelClient, rubric: dict[str, float] | None = None, threshold: float = 0.7
    ):
        self.judge = judge
        self.rubric = rubric or {"correctness": 0.6, "completeness": 0.2, "clarity": 0.2}
        self.threshold = threshold

    def applies_to(self, case: EvalCase) -> bool:
        return bool(case.rubric) or self.rubric is not None

    async def evaluate(self, case: EvalCase, run: EvalRun) -> MetricResult:
        rubric = case.rubric or self.rubric
        reference = f"Reference answer:\n{case.expected_output}\n\n" if case.expected_output else ""
        prompt = JUDGE_PROMPT.format(
            task=case.input,
            reference=reference,
            answer=run.output or "(no answer)",
            criteria="\n".join(f"- {c}" for c in rubric),
        )
        resp = await self.judge.generate([Message.user(prompt)], temperature=0.0)
        data = parse_judge_json(resp.content)
        if not data or "scores" not in data:
            return MetricResult(
                self.name,
                0.0,
                False,
                self.threshold,
                f"unparseable judge output: {resp.content[:200]!r}",
            )
        scores = {k: float(data["scores"].get(k, 0)) for k in rubric}
        total_w = sum(rubric.values()) or 1.0
        score = sum(min(max(scores[k], 0), 10) / 10 * w for k, w in rubric.items()) / total_w
        return self._result(score, str(data.get("reasoning", "")), scores=scores)


DEFAULT_METRICS: list[EvalMetric] = [
    ExactMatch(),
    Contains(),
    RegexMatch(),
    ToolCallMatch(),
    TrajectoryMatch(),
    StepBudget(),
]
