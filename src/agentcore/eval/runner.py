"""Run eval suites against an agent and produce a report."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentcore.eval.metrics import DEFAULT_METRICS, EvalMetric, LLMAsJudge, MetricResult
from agentcore.eval.replay import Cassette, RecordingModel
from agentcore.eval.suite import EvalCase, EvalSuite
from agentcore.eval.trajectory import Trajectory, TrajectoryRecorder
from agentcore.runtime.agent import Agent
from agentcore.runtime.model_client import ModelClient
from agentcore.runtime.providers import create_model
from agentcore.types import Usage

AgentFactory = Callable[[ModelClient, EvalCase, EvalSuite], Agent]


@dataclass
class EvalRun:
    case: EvalCase
    output: str | None = None
    trajectory: Trajectory = field(default_factory=Trajectory)
    metrics: list[MetricResult] = field(default_factory=list)
    steps: int = 0
    stop_reason: str = ""
    usage: Usage = field(default_factory=Usage)
    duration_ms: float = 0.0
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(m.passed for m in self.metrics)

    @property
    def score(self) -> float:
        if self.error is not None:
            return 0.0
        return sum(m.score for m in self.metrics) / len(self.metrics) if self.metrics else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.name,
            "tags": self.case.tags,
            "input": self.case.input,
            "output": self.output,
            "passed": self.passed,
            "score": round(self.score, 4),
            "metrics": [m.to_dict() for m in self.metrics],
            "steps": self.steps,
            "stop_reason": self.stop_reason,
            "usage": self.usage.to_dict(),
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "trajectory": self.trajectory.to_dict(),
        }


@dataclass
class EvalReport:
    suite: str
    model: str
    runs: list[EvalRun]
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def summary(self) -> dict[str, Any]:
        n = len(self.runs)
        passed = sum(r.passed for r in self.runs)
        per_metric: dict[str, list[float]] = {}
        for r in self.runs:
            for m in r.metrics:
                per_metric.setdefault(m.name, []).append(m.score)
        return {
            "suite": self.suite,
            "model": self.model,
            "cases": n,
            "passed": passed,
            "failed": n - passed,
            "pass_rate": round(passed / n, 4) if n else 0.0,
            "mean_score": round(sum(r.score for r in self.runs) / n, 4) if n else 0.0,
            "metrics": {k: round(sum(v) / len(v), 4) for k, v in per_metric.items()},
            "total_tokens": sum(r.usage.total_tokens for r in self.runs),
            "duration_ms": round(sum(r.duration_ms for r in self.runs), 2),
        }

    def by_tag(self, tag: str) -> EvalReport:
        return EvalReport(
            self.suite, self.model, [r for r in self.runs if tag in r.case.tags], self.started_at
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "started_at": self.started_at,
            "runs": [r.to_dict() for r in self.runs],
        }

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def to_markdown(self) -> str:
        s = self.summary()
        lines = [
            f"## Eval: {s['suite']} ({s['model']})",
            "",
            f"**{s['passed']}/{s['cases']} passed** ({s['pass_rate']:.0%}) - mean score {s['mean_score']:.2f} - "
            f"{s['total_tokens']} tokens - {s['duration_ms'] / 1000:.2f}s",
            "",
            "| case | result | score | steps | metrics |",
            "|---|---|---|---|---|",
        ]
        for r in self.runs:
            metrics = ", ".join(f"{m.name}={m.score:.2f}" for m in r.metrics) or (r.error or "")
            lines.append(
                f"| {r.case.name} | {'PASS' if r.passed else 'FAIL'} | {r.score:.2f} | {r.steps} | {metrics} |"
            )
        failures = [r for r in self.runs if not r.passed]
        if failures:
            lines += ["", "### Failures", ""]
            for r in failures:
                lines.append(f"- **{r.case.name}**: {r.error or ''}")
                for m in r.metrics:
                    if not m.passed:
                        lines.append(f"  - {m.name}: {m.details}")
                lines.append(f"  - output: `{(r.output or '')[:200]}`")
        return "\n".join(lines) + "\n"

    def to_text(self) -> str:
        s = self.summary()
        out = [f"Suite {s['suite']} | model {s['model']}"]
        for r in self.runs:
            flag = "PASS" if r.passed else "FAIL"
            metrics = " ".join(f"{m.name}={m.score:.2f}" for m in r.metrics)
            out.append(
                f"  [{flag}] {r.case.name:<28} score={r.score:.2f} steps={r.steps} {metrics}"
            )
            if not r.passed:
                for m in r.metrics:
                    if not m.passed:
                        out.append(f"         - {m.name}: {m.details}")
                if r.error:
                    out.append(f"         - error: {r.error}")
                out.append(f"         - output: {(r.output or '')[:160]!r}")
        out.append(
            f"Result: {s['passed']}/{s['cases']} passed ({s['pass_rate']:.0%}), mean score {s['mean_score']:.2f}, "
            f"{s['total_tokens']} tokens"
        )
        return "\n".join(out)


def default_agent_factory(model: ModelClient, case: EvalCase, suite: EvalSuite) -> Agent:
    from agentcore.tools.builtins import builtin_tools

    spec = suite.agent
    tools = builtin_tools(spec.tools) if spec.tools else []
    kwargs: dict[str, Any] = {"max_steps": spec.max_steps, "temperature": spec.temperature}
    return Agent(
        model, tools=tools, system_prompt=spec.system_prompt, name=f"eval:{case.name}", **kwargs
    )


class EvalRunner:
    """Execute every case: fresh agent per case, record trajectory, compute metrics.

    * ``record_to``: wrap the model in a :class:`RecordingModel` and save a cassette.
    * ``replay_from``: ignore ``model`` and replay a cassette (deterministic, offline).
    """

    def __init__(
        self,
        model: ModelClient | str | Callable[[], ModelClient] | None = None,
        *,
        agent_factory: AgentFactory | None = None,
        metrics: list[EvalMetric] | None = None,
        judge: ModelClient | None = None,
        concurrency: int = 4,
        record_to: str | Path | None = None,
        replay_from: str | Path | None = None,
        strict_replay: bool = False,
    ):
        self._model = model
        self.agent_factory = agent_factory or default_agent_factory
        self.metrics = list(metrics) if metrics is not None else list(DEFAULT_METRICS)
        if judge is not None:
            self.metrics.append(LLMAsJudge(judge))
        self.concurrency = concurrency
        self.record_to = record_to
        self.cassette = Cassette.load(replay_from) if replay_from else None
        self.strict_replay = strict_replay
        self._recorded: dict[str, list[dict[str, Any]]] = {}
        self._resolved: ModelClient | Callable[[], ModelClient] | None = None

    def _resolve(self, suite: EvalSuite) -> ModelClient | Callable[[], ModelClient] | None:
        """Resolve the model spec once per suite (so ``auto`` probes Ollama only once)."""
        if self.cassette is not None:
            return None
        m = self._model if self._model is not None else suite.agent.model
        if isinstance(m, ModelClient) or (callable(m) and not isinstance(m, str)):
            return m
        return create_model(m)

    def _model_for(self, case: EvalCase, suite: EvalSuite) -> ModelClient:
        if self.cassette is not None:
            return self.cassette.model_for(case.name, self.strict_replay)
        resolved = self._resolved if self._resolved is not None else self._resolve(suite)
        model = resolved if isinstance(resolved, ModelClient) else resolved()  # type: ignore[misc]
        return RecordingModel(model) if self.record_to else model

    def model_label(self, suite: EvalSuite) -> str:
        if self.cassette is not None:
            return f"replay:{self.cassette.model}"
        resolved = self._resolved if self._resolved is not None else self._resolve(suite)
        return resolved.model_id if isinstance(resolved, ModelClient) else "custom"

    async def run_case(self, case: EvalCase, suite: EvalSuite) -> EvalRun:
        recorder = TrajectoryRecorder()
        run = EvalRun(case)
        start = time.perf_counter()
        model: ModelClient | None = None
        try:
            model = self._model_for(case, suite)
            agent = self.agent_factory(model, case, suite)
            result = await agent.run(case.input, callbacks=[recorder])
            run.output = result.output
            run.steps = result.steps
            run.stop_reason = result.stop_reason
            run.usage = result.usage
            run.error = result.error
        except Exception as exc:  # a crashing agent is a failed case, not a crashed suite
            run.error = f"{type(exc).__name__}: {exc}"
        run.duration_ms = (time.perf_counter() - start) * 1000
        run.trajectory = recorder.get_trajectory()
        if isinstance(model, RecordingModel):
            self._recorded[case.name] = model.records
        if run.error is None:
            run.metrics = [await m.evaluate(case, run) for m in self.metrics if m.applies_to(case)]
        return run

    async def run_suite(self, suite: EvalSuite) -> EvalReport:
        self._resolved = self._resolve(suite)
        sem = asyncio.Semaphore(self.concurrency)

        async def guarded(case: EvalCase) -> EvalRun:
            async with sem:
                return await self.run_case(case, suite)

        runs = await asyncio.gather(*(guarded(c) for c in suite.cases))
        label = self.model_label(suite)
        if self.record_to:
            Cassette(self._recorded, model=label).save(self.record_to)
        return EvalReport(suite.name, label, list(runs))

    def run_suite_sync(self, suite: EvalSuite) -> EvalReport:
        return asyncio.run(self.run_suite(suite))
