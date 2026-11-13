"""Base class for specialized agents built on the runtime ``Agent``."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agentcore.obs.cost import CostTracker
from agentcore.runtime.agent import Agent, AgentResult
from agentcore.runtime.model_client import ModelClient
from agentcore.runtime.providers import create_model
from agentcore.tools.decorator import Tool
from agentcore.types import Usage


@dataclass
class AgentOutput:
    agent: str
    task: str
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    usage: Usage = field(default_factory=Usage)
    error: str | None = None
    result: AgentResult | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "task": self.task,
            "output": self.output,
            "data": self.data,
            "success": self.success,
            "usage": self.usage.to_dict(),
            "error": self.error,
        }


class SpecializedAgent:
    """A role (system prompt + tools + post-processing) on top of the ReAct loop."""

    name = "specialist"
    role = "A general-purpose specialist."

    def __init__(
        self,
        model: ModelClient | str | None = None,
        tools: list[Tool] | None = None,
        *,
        name: str | None = None,
        max_steps: int = 8,
        cost_tracker: CostTracker | None = None,
    ):
        self.model = create_model(model) if not isinstance(model, ModelClient) else model
        self.name = name or self.name
        self.max_steps = max_steps
        self.cost_tracker = cost_tracker
        self.extra_tools = list(tools or [])

    # extension points ---------------------------------------------------------------
    # Override ``system_prompt`` with a method, or set it to a string class attribute.
    def system_prompt(self) -> str:
        return f"You are the {self.name} agent. {self.role}"

    def system_prompt_text(self) -> str:
        """The system prompt, whether ``system_prompt`` is a method or a plain string."""
        sp: Any = self.system_prompt
        return str(sp() if callable(sp) else sp)

    def default_tools(self) -> list[Tool]:
        return []

    def build_task(self, task: str, context: dict[str, Any] | None) -> str:
        if not context:
            return task
        parts = [task, "", "Context from other agents:"]
        for key, value in context.items():
            text = value if isinstance(value, str) else json.dumps(value, default=str)
            parts.append(f"--- {key} ---\n{text[:4000]}")
        return "\n".join(parts)

    def postprocess(self, task: str, result: AgentResult) -> AgentOutput:
        return AgentOutput(self.name, task, result.output, usage=result.usage, result=result)

    # running --------------------------------------------------------------------------
    def make_agent(self) -> Agent:
        return Agent(
            self.model,
            tools=[*self.default_tools(), *self.extra_tools],
            system_prompt=self.system_prompt_text(),
            name=self.name,
            max_steps=self.max_steps,
            cost_tracker=self.cost_tracker,
        )

    async def run(self, task: str, context: dict[str, Any] | None = None) -> AgentOutput:
        try:
            result = await self.make_agent().run(self.build_task(task, context))
        except Exception as exc:
            return AgentOutput(
                self.name, task, "", success=False, error=f"{type(exc).__name__}: {exc}"
            )
        out = self.postprocess(task, result)
        if result.stop_reason != "final":
            out.success = False
            out.error = out.error or result.error or f"stopped: {result.stop_reason}"
        return out

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, model={self.model.model_id!r})"


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of model text (handles ```json fences)."""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidates = [fence.group(1)] if fence else []
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if m:
        candidates.append(m.group(1))
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None
