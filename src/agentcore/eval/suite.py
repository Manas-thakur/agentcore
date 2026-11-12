"""Eval suites and cases, loadable from YAML or JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ToolCallExpectation:
    """Expect a tool call. ``match``: ``exact`` | ``subset`` (default) | ``any`` (name only)."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    match: str = "subset"
    min_count: int = 1
    max_count: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | str) -> ToolCallExpectation:
        if isinstance(d, str):
            return cls(tool=d, match="any")
        return cls(
            tool=d.get("tool") or d["name"],
            args=d.get("args") or d.get("arguments") or {},
            match=d.get("match", "subset" if (d.get("args") or d.get("arguments")) else "any"),
            min_count=d.get("min_count", 1),
            max_count=d.get("max_count"),
        )


@dataclass
class EvalCase:
    name: str
    input: str
    expected_output: str | None = None
    match: str = "contains"  # exact | contains | regex
    expected_tool_calls: list[ToolCallExpectation] = field(default_factory=list)
    expected_trajectory: list[str] = field(default_factory=list)  # ordered tool names
    rubric: dict[str, float] | None = None  # LLM-as-judge criteria -> weight
    max_steps: int | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvalCase:
        return cls(
            name=d["name"],
            input=d["input"],
            expected_output=None if d.get("expected_output") is None else str(d["expected_output"]),
            match=d.get("match", "contains"),
            expected_tool_calls=[
                ToolCallExpectation.from_dict(x) for x in d.get("expected_tool_calls") or []
            ],
            expected_trajectory=list(d.get("expected_trajectory") or []),
            rubric=d.get("rubric"),
            max_steps=d.get("max_steps"),
            tags=list(d.get("tags") or []),
            metadata=dict(d.get("metadata") or {}),
        )


@dataclass
class AgentSpec:
    """How to build the agent under test (overridable per run)."""

    system_prompt: str | None = None
    tools: list[str] = field(default_factory=list)
    max_steps: int = 8
    model: str | None = None
    temperature: float = 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> AgentSpec:
        d = d or {}
        return cls(
            system_prompt=d.get("system_prompt"),
            tools=list(d.get("tools") or []),
            max_steps=int(d.get("max_steps", 8)),
            model=d.get("model"),
            temperature=float(d.get("temperature", 0.0)),
        )


@dataclass
class EvalSuite:
    name: str
    cases: list[EvalCase]
    description: str = ""
    agent: AgentSpec = field(default_factory=AgentSpec)
    path: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any], path: str | None = None) -> EvalSuite:
        cases = [EvalCase.from_dict(c) for c in d.get("cases", [])]
        names = [c.name for c in cases]
        if len(names) != len(set(names)):
            raise ValueError("eval case names must be unique")
        return cls(
            name=d.get("name") or (Path(path).stem if path else "suite"),
            description=d.get("description", ""),
            cases=cases,
            agent=AgentSpec.from_dict(d.get("agent")),
            path=path,
        )

    def filter(self, tags: list[str] | None = None, names: list[str] | None = None) -> EvalSuite:
        cases = [
            c
            for c in self.cases
            if (not tags or set(tags) & set(c.tags)) and (not names or c.name in names)
        ]
        return EvalSuite(self.name, cases, self.description, self.agent, self.path)


def load_suite(path: str | Path) -> EvalSuite:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    data = json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)
    return EvalSuite.from_dict(data, str(p))
