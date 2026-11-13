"""Researcher, Coder, Reviewer and Planner agents."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agentcore.agents.base import AgentOutput, SpecializedAgent, extract_json
from agentcore.runtime.agent import AgentResult
from agentcore.runtime.model_client import ModelClient
from agentcore.tools.builtins import make_http_get, make_python_exec, make_web_search
from agentcore.tools.decorator import Tool
from agentcore.tools.sandbox import SandboxConfig
from agentcore.types import Message

# --- Researcher -------------------------------------------------------------------------

_SOURCE_LINE = re.compile(r"^\[(\d+)\]\s+(.*?)\s+\(([^()]*)\)\s*$", re.M)


class ResearcherAgent(SpecializedAgent):
    """Searches a knowledge base (RAG) and/or the web, then writes a cited summary."""

    name = "researcher"
    role = (
        "You research topics thoroughly. Search before answering, run several searches for "
        "different aspects if needed, and cite sources by their title or URL. Never invent facts."
    )

    def __init__(
        self,
        model: ModelClient | str | None = None,
        *,
        knowledge_base: Any = None,
        web: bool = False,
        **kw: Any,
    ):
        super().__init__(model, **kw)
        self.knowledge_base = knowledge_base
        self.web = web

    def default_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        if self.knowledge_base is not None:
            tools.append(self.knowledge_base.as_tool("search_docs", k=4))
        if self.web:
            tools += [make_web_search(), make_http_get()]
        return tools

    @staticmethod
    def collect_sources(result: AgentResult) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        seen: set[str] = set()
        for r in result.tool_results:
            if not r.success:
                continue
            if isinstance(r.output, list):  # web_search results
                for item in r.output:
                    if isinstance(item, dict) and item.get("url") and item["url"] not in seen:
                        seen.add(item["url"])
                        sources.append({"title": item.get("title", ""), "location": item["url"]})
            elif isinstance(r.output, str):
                for _, title, loc in _SOURCE_LINE.findall(r.output):
                    if loc not in seen:
                        seen.add(loc)
                        sources.append({"title": title, "location": loc})
                if r.tool_name == "http_get":
                    url = r.arguments.get("url", "")
                    if url and url not in seen:
                        seen.add(url)
                        sources.append({"title": url, "location": url})
        return sources

    def postprocess(self, task: str, result: AgentResult) -> AgentOutput:
        sources = self.collect_sources(result)
        return AgentOutput(
            self.name, task, result.output, {"sources": sources}, usage=result.usage, result=result
        )

    @staticmethod
    def render_report(topic: str, output: AgentOutput, model: str = "") -> str:
        lines = [
            f"# Research Report: {topic}",
            "",
            f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            + (f" with `{model}`" if model else "")
            + "*",
            "",
            "## Summary",
            "",
            output.output.strip() or "_No findings._",
            "",
            "## Sources",
            "",
        ]
        sources = output.data.get("sources", [])
        lines += [f"{i}. {s['title']} - {s['location']}" for i, s in enumerate(sources, 1)] or [
            "_No sources._"
        ]
        return "\n".join(lines) + "\n"


# --- Coder -------------------------------------------------------------------------------

_CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


class CoderAgent(SpecializedAgent):
    """Writes Python, executes it in the sandbox to verify, and reports code + result."""

    name = "coder"
    role = (
        "You write correct, minimal Python 3 code. Always run your code with the python_exec "
        "tool (print the results) before answering. Final answer: the code in a ```python block "
        "followed by the verified output."
    )

    def __init__(
        self,
        model: ModelClient | str | None = None,
        *,
        sandbox: SandboxConfig | None = None,
        **kw: Any,
    ):
        super().__init__(model, **kw)
        self.sandbox = sandbox

    def default_tools(self) -> list[Tool]:
        return [make_python_exec(self.sandbox)]

    def postprocess(self, task: str, result: AgentResult) -> AgentOutput:
        runs = [r for r in result.tool_results if r.tool_name == "python_exec"]
        code = runs[-1].arguments.get("code", "") if runs else ""
        if not code:
            m = _CODE_BLOCK.search(result.output)
            code = m.group(1) if m else ""
        execution = runs[-1].as_text() if runs else ""
        output = result.output
        if code and "```" not in output:
            output = f"```python\n{code.strip()}\n```\n\nOutput:\n{execution}\n\n{output}"
        ok = bool(runs) and runs[-1].success and "Traceback" not in execution
        return AgentOutput(
            self.name,
            task,
            output,
            {"code": code, "execution": execution, "verified": ok},
            usage=result.usage,
            result=result,
        )


# --- Reviewer ------------------------------------------------------------------------------


@dataclass
class ReviewIssue:
    severity: str  # low | medium | high
    description: str


@dataclass
class ReviewResult:
    approved: bool
    score: float
    issues: list[ReviewIssue] = field(default_factory=list)
    summary: str = ""
    method: str = "llm"  # llm | heuristic

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "score": self.score,
            "issues": [i.__dict__ for i in self.issues],
            "summary": self.summary,
            "method": self.method,
        }


class ReviewerAgent(SpecializedAgent):
    """Critiques another agent's output; returns a structured :class:`ReviewResult`."""

    name = "reviewer"
    role = (
        "You are a strict reviewer. Check the work for correctness, completeness, unsupported "
        'claims and errors. Respond ONLY with JSON: {"approved": true|false, "score": 0.0-1.0, '
        '"issues": [{"severity": "low|medium|high", "description": "..."}], "summary": "..."}'
    )

    def __init__(
        self, model: ModelClient | str | None = None, *, threshold: float = 0.7, **kw: Any
    ):
        super().__init__(model, **kw)
        self.threshold = threshold

    @staticmethod
    def heuristic_review(content: str) -> ReviewResult:
        issues: list[ReviewIssue] = []
        text = content.strip()
        if not text:
            issues.append(ReviewIssue("high", "output is empty"))
        elif len(text) < 20:
            issues.append(ReviewIssue("medium", "output is very short"))
        if re.search(r"Traceback|\bERROR\b|exit code [1-9]", text):
            issues.append(ReviewIssue("high", "output contains an error"))
        if "could not find" in text.lower() or "don't know" in text.lower():
            issues.append(ReviewIssue("medium", "output admits missing information"))
        penalty = {"high": 0.5, "medium": 0.2, "low": 0.05}
        score = max(0.0, 1.0 - sum(penalty[i.severity] for i in issues))
        return ReviewResult(
            approved=not any(i.severity == "high" for i in issues) and score >= 0.7,
            score=score,
            issues=issues,
            summary="heuristic review (model did not return valid JSON)",
            method="heuristic",
        )

    def parse_review(self, text: str, reviewed: str) -> ReviewResult:
        data = extract_json(text)
        if isinstance(data, dict) and "approved" in data:
            issues = [
                ReviewIssue(str(i.get("severity", "medium")), str(i.get("description", "")))
                for i in data.get("issues", [])
                if isinstance(i, dict)
            ]
            score = float(data.get("score", 1.0 if data["approved"] else 0.0))
            return ReviewResult(
                bool(data["approved"]) and score >= self.threshold,
                score,
                issues,
                str(data.get("summary", "")),
            )
        return self.heuristic_review(reviewed)

    def build_task(self, task: str, context: dict[str, Any] | None) -> str:
        work = (context or {}).get("work") or (context or {}).get("output")
        if work is None and context:
            work = "\n\n".join(str(v) for v in context.values())
        return f"Task that was performed:\n{task}\n\nWork to review:\n{work or task}"

    async def review(self, task: str, work: str) -> ReviewResult:
        out = await self.run(task, {"work": work})
        return ReviewResult(
            **{
                **out.data["review"],
                "issues": [ReviewIssue(**i) for i in out.data["review"]["issues"]],
            }
        )

    async def run(self, task: str, context: dict[str, Any] | None = None) -> AgentOutput:
        work = str((context or {}).get("work") or (context or {}).get("output") or "")
        if context and not work:
            work = "\n\n".join(str(v) for v in context.values())
        resp = await self.model.generate(
            [
                Message.system(self.system_prompt_text()),
                Message.user(self.build_task(task, context)),
            ]
        )
        if self.cost_tracker is not None:
            self.cost_tracker.record(
                self.model.model_id,
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
                self.name,
            )
        review = self.parse_review(resp.content, work or task)
        verdict = "APPROVED" if review.approved else "CHANGES REQUESTED"
        lines = [f"{verdict} (score {review.score:.2f}) - {review.summary}".strip(" -")]
        lines += [f"- [{i.severity}] {i.description}" for i in review.issues]
        return AgentOutput(
            self.name, task, "\n".join(lines), {"review": review.to_dict()}, usage=resp.usage
        )


# --- Planner ---------------------------------------------------------------------------------


@dataclass
class PlanTask:
    id: str
    description: str
    assignee: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Plan:
    goal: str
    tasks: list[PlanTask]
    method: str = "llm"  # llm | heuristic

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "method": self.method, "tasks": [t.__dict__ for t in self.tasks]}

    def waves(self) -> list[list[PlanTask]]:
        """Group tasks into dependency levels (tasks in one wave can run in parallel)."""
        done: set[str] = set()
        remaining = list(self.tasks)
        waves: list[list[PlanTask]] = []
        while remaining:
            ready = [t for t in remaining if set(t.depends_on) <= done]
            if not ready:  # cycle or missing dependency: run the rest sequentially
                ready = [remaining[0]]
            waves.append(ready)
            done |= {t.id for t in ready}
            remaining = [t for t in remaining if t not in ready]
        return waves


_CODER_WORDS = re.compile(
    r"\b(compute|calculate|code|script|implement|program|python|simulate|plot)\b", re.I
)
_REVIEW_WORDS = re.compile(r"\b(review|verify|check|critique|validate|proofread)\b", re.I)
_SPLIT = re.compile(
    r"(?:;|\.\s+|\bthen\b|,?\s+and\s+(?=(?:research|find|explain|compute|calculate|write|code|review|check|"
    r"verify|summari[sz]e|compare|describe|list|implement)\b))",
    re.I,
)


class PlannerAgent(SpecializedAgent):
    """Decomposes a goal into tasks assigned to available agents."""

    name = "planner"
    role = "You break goals into a small number of concrete sub-tasks and assign each to the best agent."

    def __init__(
        self,
        model: ModelClient | str | None = None,
        *,
        agents: dict[str, str] | None = None,
        **kw: Any,
    ):
        super().__init__(model, **kw)
        self.agents = agents or {
            "researcher": ResearcherAgent.role,
            "coder": CoderAgent.role,
            "reviewer": "Reviews work for correctness.",
        }

    def system_prompt(self) -> str:
        roster = "\n".join(f"- {n}: {d}" for n, d in self.agents.items())
        return (
            f"{self.role}\nAvailable agents:\n{roster}\n\n"
            'Respond ONLY with JSON: {"tasks": [{"id": "t1", "description": "...", '
            '"assignee": "<agent name>", "depends_on": []}]}. Use 1-5 tasks.'
        )

    def heuristic_plan(self, goal: str) -> Plan:
        parts = [p.strip(" ,.") for p in _SPLIT.split(goal) if p and p.strip(" ,.")]
        tasks: list[PlanTask] = []
        for i, part in enumerate(parts or [goal], start=1):
            if _REVIEW_WORDS.search(part) and "reviewer" in self.agents:
                assignee = "reviewer"
            elif _CODER_WORDS.search(part) and "coder" in self.agents:
                assignee = "coder"
            else:
                assignee = "researcher" if "researcher" in self.agents else next(iter(self.agents))
            deps = [t.id for t in tasks] if assignee == "reviewer" else []
            tasks.append(PlanTask(f"t{i}", part, assignee, deps))
        return Plan(goal, tasks, method="heuristic")

    def parse_plan(self, goal: str, text: str) -> Plan:
        data = extract_json(text)
        raw = (
            data.get("tasks")
            if isinstance(data, dict)
            else data
            if isinstance(data, list)
            else None
        )
        if not raw:
            return self.heuristic_plan(goal)
        tasks = []
        for i, t in enumerate(raw, start=1):
            if not isinstance(t, dict) or not t.get("description"):
                continue
            assignee = (
                t.get("assignee") if t.get("assignee") in self.agents else next(iter(self.agents))
            )
            tasks.append(
                PlanTask(
                    str(t.get("id") or f"t{i}"),
                    str(t["description"]),
                    assignee,
                    [str(d) for d in t.get("depends_on") or []],
                )
            )
        return Plan(goal, tasks) if tasks else self.heuristic_plan(goal)

    async def plan(self, goal: str) -> Plan:
        resp = await self.model.generate(
            [Message.system(self.system_prompt_text()), Message.user(goal)]
        )
        if self.cost_tracker is not None:
            self.cost_tracker.record(
                self.model.model_id,
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
                self.name,
            )
        return self.parse_plan(goal, resp.content)

    async def run(self, task: str, context: dict[str, Any] | None = None) -> AgentOutput:
        plan = await self.plan(task)
        text = "\n".join(f"{t.id}. [{t.assignee}] {t.description}" for t in plan.tasks)
        return AgentOutput(self.name, task, text, {"plan": plan.to_dict()})
