"""Multi-agent collaboration patterns over the A2A bus: manager-worker, pipeline, peer review."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from agentcore.agents.a2a import A2AMessage, A2AMessageType, MessageBus
from agentcore.agents.base import AgentOutput, SpecializedAgent
from agentcore.agents.specialists import Plan, PlannerAgent, ReviewerAgent, ReviewResult
from agentcore.obs.tracing import get_tracer
from agentcore.types import Usage


def _from_reply(reply: A2AMessage, agent: str, task: str) -> AgentOutput:
    p = reply.payload
    if reply.type == A2AMessageType.ERROR:
        return AgentOutput(agent, task, "", success=False, error=p.get("error"))
    return AgentOutput(
        agent=p.get("agent", agent),
        task=p.get("task", task),
        output=p.get("output", ""),
        data=p.get("data", {}),
        success=p.get("success", True),
        usage=Usage.from_dict(p.get("usage")),
        error=p.get("error"),
    )


@dataclass
class TeamResult:
    goal: str
    output: str
    plan: Plan | None = None
    results: dict[str, AgentOutput] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(r.success for r in self.results.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "output": self.output,
            "plan": self.plan.to_dict() if self.plan else None,
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "messages": self.messages,
        }


class ManagerWorker:
    """The planner decomposes the goal; workers execute tasks (parallel where independent)
    via A2A requests; dependency outputs flow in as context; results are synthesized."""

    def __init__(
        self,
        planner: PlannerAgent,
        workers: dict[str, SpecializedAgent],
        bus: MessageBus | None = None,
    ):
        self.planner = planner
        self.workers = workers
        self.bus = bus or MessageBus()
        self.planner.agents = {name: getattr(w, "role", name) for name, w in workers.items()}
        for name, worker in workers.items():
            self.bus.register(name, worker)

    async def run(self, goal: str) -> TeamResult:
        with get_tracer().span("team.manager_worker", {"goal": goal[:300]}):
            plan = await self.planner.plan(goal)
            results: dict[str, AgentOutput] = {}
            for wave in plan.waves():

                async def do(task: Any) -> tuple[str, AgentOutput]:
                    context = {
                        f"{dep} ({results[dep].agent})": results[dep].output
                        for dep in task.depends_on
                        if dep in results
                    }
                    reply = await self.bus.request(
                        "manager",
                        task.assignee,
                        {"task": task.description, "context": context or None},
                    )
                    return task.id, _from_reply(reply, task.assignee, task.description)

                for task_id, out in await asyncio.gather(*(do(t) for t in wave)):
                    results[task_id] = out
            output = self.synthesize(goal, plan, results)
        return TeamResult(goal, output, plan, results, self.bus.transcript())

    @staticmethod
    def synthesize(goal: str, plan: Plan, results: dict[str, AgentOutput]) -> str:
        lines = [f"# {goal}", ""]
        for t in plan.tasks:
            r = results.get(t.id)
            status = "" if r is None or r.success else " (failed)"
            lines += [
                f"## {t.id}. {t.description} - {t.assignee}{status}",
                "",
                (r.output if r else "").strip(),
                "",
            ]
        return "\n".join(lines).strip() + "\n"


class Pipeline:
    """A -> B -> C: each agent receives the original task plus the previous agent's output."""

    def __init__(self, agents: list[SpecializedAgent], bus: MessageBus | None = None):
        self.agents = agents
        self.bus = bus or MessageBus()
        for a in agents:
            self.bus.register(a.name, a)

    async def run(self, task: str) -> TeamResult:
        results: dict[str, AgentOutput] = {}
        context: dict[str, Any] | None = None
        prev = "user"
        with get_tracer().span("team.pipeline", {"task": task[:300]}):
            for a in self.agents:
                reply = await self.bus.request(prev, a.name, {"task": task, "context": context})
                out = _from_reply(reply, a.name, task)
                results[a.name] = out
                context = {a.name: out.output}
                prev = a.name
        final = results[self.agents[-1].name].output if self.agents else ""
        return TeamResult(task, final, None, results, self.bus.transcript())


async def peer_review(
    worker: SpecializedAgent, reviewer: ReviewerAgent, task: str, max_rounds: int = 2
) -> tuple[AgentOutput, ReviewResult, int]:
    """Worker produces, reviewer critiques; on rejection the worker revises with the feedback."""
    out = await worker.run(task)
    review = await reviewer.review(task, out.output)
    rounds = 1
    while not review.approved and rounds < max_rounds:
        feedback = (
            "\n".join(f"- [{i.severity}] {i.description}" for i in review.issues) or review.summary
        )
        out = await worker.run(
            task, {"previous attempt": out.output, "reviewer feedback": feedback}
        )
        review = await reviewer.review(task, out.output)
        rounds += 1
    return out, review, rounds
