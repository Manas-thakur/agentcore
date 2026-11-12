"""Trajectories: the ordered steps an agent took, recorded from agent events."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentcore.runtime.agent import AgentEvent


@dataclass
class Step:
    type: str  # thought | tool_call | tool_result | reflection | output
    content: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    success: bool | None = None
    step: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Trajectory:
    steps: list[Step] = field(default_factory=list)
    output: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_calls(self) -> list[Step]:
        return [s for s in self.steps if s.type == "tool_call"]

    @property
    def tool_names(self) -> list[str]:
        return [s.tool_name or "" for s in self.tool_calls]

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "output": self.output,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trajectory:
        return cls([Step(**s) for s in d.get("steps", [])], d.get("output"), d.get("metadata", {}))

    def to_mermaid(self) -> str:
        """Sequence diagram of the trajectory."""
        lines = ["sequenceDiagram", "    participant A as Agent", "    participant T as Tools"]
        for s in self.steps:
            if s.type == "tool_call":
                args = json.dumps(s.arguments or {})[:60].replace('"', "'")
                lines.append(f"    A->>T: {s.tool_name}({args})")
            elif s.type == "tool_result":
                ok = "ok" if s.success else "error"
                lines.append(f"    T-->>A: {ok}: {(s.content or '')[:50]}".replace("\n", " "))
            elif s.type == "reflection":
                lines.append(
                    f"    Note over A: reflection: {(s.content or '')[:50]}".replace("\n", " ")
                )
            elif s.type == "output":
                lines.append(
                    f"    Note over A: answer: {(s.content or '')[:60]}".replace("\n", " ")
                )
        return "\n".join(lines)


class TrajectoryRecorder:
    """Agent callback that turns events into a :class:`Trajectory`.

    Usage: ``agent.run(task, callbacks=[recorder])`` or ``agent.on(recorder)``.
    """

    def __init__(self) -> None:
        self.trajectory = Trajectory()

    def __call__(self, event: AgentEvent) -> None:
        d = event.data
        steps = self.trajectory.steps
        if event.type == "model_response":
            if d.get("content") and d.get("tool_calls"):
                steps.append(Step("thought", content=d["content"], step=event.step))
            for tc in d.get("tool_calls", []):
                steps.append(
                    Step(
                        "tool_call",
                        tool_name=tc["name"],
                        arguments=tc["arguments"],
                        step=event.step,
                    )
                )
        elif event.type == "tool_end":
            steps.append(
                Step(
                    "tool_result",
                    content=d.get("output"),
                    tool_name=d.get("name"),
                    success=d.get("success"),
                    step=event.step,
                )
            )
        elif event.type == "reflection":
            steps.append(Step("reflection", content=d.get("content"), step=event.step))
        elif event.type == "final":
            steps.append(Step("output", content=d.get("output"), step=event.step))
            self.trajectory.output = d.get("output")

    def get_trajectory(self) -> Trajectory:
        return self.trajectory

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.trajectory.to_dict(), indent=2), encoding="utf-8")
