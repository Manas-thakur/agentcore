"""Eval suites and cases, loadable from YAML or JSON.

Suites are validated strictly when loaded: unknown keys, missing case names, invalid
``match`` values, malformed tool-call expectations and rubrics raise :class:`SuiteError`
with a message that says where the problem is and which keys are allowed.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

OUTPUT_MATCH_MODES = ("exact", "contains", "regex")
TOOL_MATCH_MODES = ("exact", "subset", "any")

SUITE_KEYS = ("name", "description", "agent", "cases")
AGENT_KEYS = ("system_prompt", "tools", "max_steps", "model", "temperature")
CASE_KEYS = (
    "name",
    "input",
    "expected_output",
    "match",
    "expected_tool_calls",
    "expected_trajectory",
    "rubric",
    "max_steps",
    "tags",
    "metadata",
)
TOOL_CALL_KEYS = ("tool", "name", "args", "arguments", "match", "min_count", "max_count")


class SuiteError(ValueError):
    """An eval suite file (or dict) is malformed."""


def _check_keys(d: Mapping[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = [k for k in d if k not in allowed]
    if not unknown:
        return
    hints = []
    for k in unknown:
        close = difflib.get_close_matches(str(k), allowed, n=1)
        hints.append(f"{k!r}" + (f" (did you mean {close[0]!r}?)" if close else ""))
    raise SuiteError(
        f"{where}: unknown key{'s' if len(unknown) > 1 else ''} {', '.join(hints)}; "
        f"allowed keys: {', '.join(allowed)}"
    )


def _str_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list) and all(isinstance(v, (str, int, float)) for v in value):
        return [str(v) for v in value]
    raise SuiteError(f"{where} must be a list of strings")


def _int(value: Any, where: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SuiteError(f"{where} must be an integer >= {minimum}, got {value!r}")
    return value


def normalize_match(value: Any, where: str = "match") -> str:
    """``exact`` | ``contains`` | ``regex`` (case-insensitive); anything else is an error."""
    mode = str(value).strip().lower()
    if mode not in OUTPUT_MATCH_MODES:
        raise SuiteError(
            f"{where}: invalid match {value!r}; use one of {', '.join(OUTPUT_MATCH_MODES)}"
        )
    return mode


def normalize_rubric(rubric: Any, where: str = "rubric") -> dict[str, float] | None:
    """Accept ``{criterion: weight}``, ``[{criterion, weight}]`` or ``[criterion, ...]``."""
    if rubric is None:
        return None
    out: dict[str, float] = {}
    if isinstance(rubric, Mapping):
        items = list(rubric.items())
    elif isinstance(rubric, list):
        items = []
        for i, entry in enumerate(rubric):
            if isinstance(entry, str):
                items.append((entry, 1.0))
            elif isinstance(entry, Mapping):
                _check_keys(entry, ("criterion", "weight"), f"{where}[{i}]")
                if "criterion" not in entry:
                    raise SuiteError(f"{where}[{i}] needs a 'criterion'")
                items.append((entry["criterion"], entry.get("weight", 1.0)))
            else:
                raise SuiteError(
                    f"{where}[{i}] must be a criterion name or {{criterion, weight}}, got {entry!r}"
                )
    else:
        raise SuiteError(
            f"{where} must be a mapping {{criterion: weight}} or a list of "
            f"{{criterion, weight}} entries, got {type(rubric).__name__}"
        )
    for criterion, weight in items:
        if not isinstance(criterion, str) or not criterion.strip():
            raise SuiteError(f"{where}: criterion names must be non-empty strings")
        try:
            w = float(weight)
        except (TypeError, ValueError):
            raise SuiteError(f"{where}: weight of {criterion!r} must be a number") from None
        if w < 0:
            raise SuiteError(f"{where}: weight of {criterion!r} must be >= 0")
        out[criterion.strip()] = w
    if not out:
        raise SuiteError(f"{where} is empty")
    return out


@dataclass
class ToolCallExpectation:
    """Expect a tool call. ``match``: ``exact`` | ``subset`` (default) | ``any`` (name only)."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    match: str = "subset"
    min_count: int = 1
    max_count: int | None = None

    def __post_init__(self) -> None:
        mode = str(self.match).strip().lower()
        if mode not in TOOL_MATCH_MODES:
            raise SuiteError(
                f"tool call {self.tool!r}: invalid match {self.match!r}; "
                f"use one of {', '.join(TOOL_MATCH_MODES)}"
            )
        self.match = mode

    @classmethod
    def from_dict(
        cls, d: Mapping[str, Any] | str, where: str = "expected_tool_calls"
    ) -> ToolCallExpectation:
        if isinstance(d, str):
            return cls(tool=d, match="any")
        if not isinstance(d, Mapping):
            raise SuiteError(f"{where} must be a tool name or a mapping, got {d!r}")
        _check_keys(d, TOOL_CALL_KEYS, where)
        tool = d.get("tool") or d.get("name")
        if not isinstance(tool, str) or not tool:
            raise SuiteError(f"{where} needs a 'tool' (the tool name)")
        args = d.get("args") if d.get("args") is not None else d.get("arguments")
        if args is not None and not isinstance(args, Mapping):
            raise SuiteError(f"{where}.args must be a mapping of argument names to values")
        max_count = d.get("max_count")
        return cls(
            tool=tool,
            args=dict(args or {}),
            match=d.get("match", "subset" if args else "any"),
            min_count=_int(d.get("min_count", 1), f"{where}.min_count"),
            max_count=None if max_count is None else _int(max_count, f"{where}.max_count"),
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

    def __post_init__(self) -> None:
        where = f"case {self.name!r}"
        self.match = normalize_match(self.match, where)
        if self.match == "regex" and self.expected_output is not None:
            try:
                re.compile(self.expected_output)
            except re.error as exc:
                raise SuiteError(
                    f"{where}: invalid regex {self.expected_output!r}: {exc}"
                ) from None
        self.rubric = normalize_rubric(self.rubric, f"{where}: rubric")

    @property
    def has_checks(self) -> bool:
        """Whether any metric applies without a judge model."""
        return bool(
            self.expected_output is not None
            or self.expected_tool_calls
            or self.expected_trajectory
            or self.max_steps is not None
        )

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], where: str = "case") -> EvalCase:
        if not isinstance(d, Mapping):
            raise SuiteError(f"{where} must be a mapping with at least 'name' and 'input'")
        name = d.get("name")
        if name is not None:
            where = f"{where} ({name!r})"
        _check_keys(d, CASE_KEYS, where)
        if not isinstance(name, (str, int)) or str(name).strip() == "":
            raise SuiteError(f"{where}: every case needs a 'name'")
        if d.get("input") is None:
            raise SuiteError(f"{where}: missing 'input'")
        calls = d.get("expected_tool_calls") or []
        if not isinstance(calls, list):
            calls = [calls]
        max_steps = d.get("max_steps")
        metadata = d.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise SuiteError(f"{where}: metadata must be a mapping")
        match = normalize_match(d.get("match", "contains"), where)
        expected = None if d.get("expected_output") is None else str(d["expected_output"])
        if match == "regex" and expected is not None:
            try:
                re.compile(expected)
            except re.error as exc:
                raise SuiteError(f"{where}: invalid regex {expected!r}: {exc}") from None
        return cls(
            name=str(name),
            input=str(d["input"]),
            expected_output=expected,
            match=match,
            expected_tool_calls=[
                ToolCallExpectation.from_dict(x, f"{where}: expected_tool_calls[{i}]")
                for i, x in enumerate(calls)
            ],
            expected_trajectory=_str_list(
                d.get("expected_trajectory"), f"{where}: expected_trajectory"
            ),
            rubric=normalize_rubric(d.get("rubric"), f"{where}: rubric"),
            max_steps=None if max_steps is None else _int(max_steps, f"{where}: max_steps", 1),
            tags=_str_list(d.get("tags"), f"{where}: tags"),
            metadata=dict(metadata),
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
    def from_dict(cls, d: Mapping[str, Any] | None) -> AgentSpec:
        d = d or {}
        if not isinstance(d, Mapping):
            raise SuiteError("agent must be a mapping")
        _check_keys(d, AGENT_KEYS, "agent")
        try:
            temperature = float(d.get("temperature", 0.0))
        except (TypeError, ValueError):
            raise SuiteError("agent.temperature must be a number") from None
        return cls(
            system_prompt=d.get("system_prompt"),
            tools=_str_list(d.get("tools"), "agent.tools"),
            max_steps=_int(d.get("max_steps", 8), "agent.max_steps", 1),
            model=None if d.get("model") is None else str(d["model"]),
            temperature=temperature,
        )


@dataclass
class EvalSuite:
    name: str
    cases: list[EvalCase]
    description: str = ""
    agent: AgentSpec = field(default_factory=AgentSpec)
    path: str | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], path: str | None = None) -> EvalSuite:
        prefix = f"{path}: " if path else ""
        try:
            if not isinstance(d, Mapping):
                raise SuiteError(
                    "an eval suite must be a mapping with 'name', 'agent' and 'cases' keys"
                )
            _check_keys(d, SUITE_KEYS, "suite")
            raw_cases = d.get("cases") or []
            if not isinstance(raw_cases, list):
                raise SuiteError("'cases' must be a list")
            cases = [EvalCase.from_dict(c, f"cases[{i}]") for i, c in enumerate(raw_cases)]
            names = [c.name for c in cases]
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                raise SuiteError(f"eval case names must be unique; duplicated: {dupes}")
            return cls(
                name=str(d.get("name") or (Path(path).stem if path else "suite")),
                description=str(d.get("description") or ""),
                cases=cases,
                agent=AgentSpec.from_dict(d.get("agent")),
                path=path,
            )
        except SuiteError as exc:
            raise SuiteError(f"{prefix}{exc}") from None

    def filter(self, tags: list[str] | None = None, names: list[str] | None = None) -> EvalSuite:
        cases = [
            c
            for c in self.cases
            if (not tags or set(tags) & set(c.tags)) and (not names or c.name in names)
        ]
        return EvalSuite(self.name, cases, self.description, self.agent, self.path)


def read_suite_file(path: str | Path) -> Any:
    """Parse a YAML/JSON file without validating it. Raises :class:`SuiteError` on bad syntax."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    try:
        return json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        detail = " ".join(str(exc).split())
        raise SuiteError(
            f"{p}: invalid {'JSON' if p.suffix.lower() == '.json' else 'YAML'}: {detail}"
        ) from None


def load_suite(path: str | Path) -> EvalSuite:
    """Load and validate a suite. Raises ``FileNotFoundError`` or :class:`SuiteError`."""
    return EvalSuite.from_dict(read_suite_file(path), str(path))
