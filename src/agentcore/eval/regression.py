"""Regression detection: compare an eval report against a stored baseline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentcore.eval.runner import EvalReport


@dataclass
class Change:
    case: str
    metric: str
    baseline: float
    current: float

    @property
    def delta(self) -> float:
        return self.current - self.baseline


@dataclass
class EvalDiff:
    regressions: list[Change] = field(default_factory=list)
    improvements: list[Change] = field(default_factory=list)
    new_failures: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    missing_cases: list[str] = field(default_factory=list)
    new_cases: list[str] = field(default_factory=list)
    baseline_pass_rate: float = 0.0
    current_pass_rate: float = 0.0

    @property
    def has_regressions(self) -> bool:
        return bool(self.regressions or self.new_failures)

    def to_dict(self) -> dict[str, Any]:
        def ch(c: Change) -> dict[str, Any]:
            return {
                "case": c.case,
                "metric": c.metric,
                "baseline": c.baseline,
                "current": c.current,
                "delta": round(c.delta, 4),
            }

        return {
            "has_regressions": self.has_regressions,
            "regressions": [ch(c) for c in self.regressions],
            "improvements": [ch(c) for c in self.improvements],
            "new_failures": list(self.new_failures),
            "fixed": list(self.fixed),
            "missing_cases": list(self.missing_cases),
            "new_cases": list(self.new_cases),
            "baseline_pass_rate": self.baseline_pass_rate,
            "current_pass_rate": self.current_pass_rate,
        }

    def to_markdown(self) -> str:
        lines = [
            "## Regression check",
            "",
            f"Pass rate: {self.baseline_pass_rate:.0%} -> {self.current_pass_rate:.0%}",
            "",
        ]
        if not self.has_regressions:
            lines.append("No regressions.")
        for name in self.new_failures:
            lines.append(f"- REGRESSION: `{name}` passed in the baseline and now fails")
        for c in self.regressions:
            lines.append(
                f"- REGRESSION: `{c.case}` {c.metric}: {c.baseline:.2f} -> {c.current:.2f} ({c.delta:+.2f})"
            )
        for c in self.improvements:
            lines.append(
                f"- improved: `{c.case}` {c.metric}: {c.baseline:.2f} -> {c.current:.2f} ({c.delta:+.2f})"
            )
        for name in self.fixed:
            lines.append(f"- fixed: `{name}` now passes")
        if self.new_cases:
            lines.append(f"- new cases: {', '.join(self.new_cases)}")
        if self.missing_cases:
            lines.append(f"- cases missing vs baseline: {', '.join(self.missing_cases)}")
        return "\n".join(lines) + "\n"


def _index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["case"]: r for r in report.get("runs", [])}


def compare(
    baseline: dict[str, Any] | EvalReport,
    current: dict[str, Any] | EvalReport,
    threshold: float = 0.05,
) -> EvalDiff:
    """Compare two reports (``EvalReport`` or their ``to_dict()`` JSON)."""
    b = baseline.to_dict() if isinstance(baseline, EvalReport) else baseline
    c = current.to_dict() if isinstance(current, EvalReport) else current
    bi, ci = _index(b), _index(c)
    diff = EvalDiff(
        baseline_pass_rate=b.get("summary", {}).get("pass_rate", 0.0),
        current_pass_rate=c.get("summary", {}).get("pass_rate", 0.0),
    )
    diff.missing_cases = sorted(set(bi) - set(ci))
    diff.new_cases = sorted(set(ci) - set(bi))
    for name in sorted(set(bi) & set(ci)):
        br, cr = bi[name], ci[name]
        if br["passed"] and not cr["passed"]:
            diff.new_failures.append(name)
        elif not br["passed"] and cr["passed"]:
            diff.fixed.append(name)
        bm = {m["name"]: m["score"] for m in br.get("metrics", [])}
        cm = {m["name"]: m["score"] for m in cr.get("metrics", [])}
        for metric in sorted(set(bm) & set(cm)):
            change = Change(name, metric, bm[metric], cm[metric])
            if change.delta < -threshold:
                diff.regressions.append(change)
            elif change.delta > threshold:
                diff.improvements.append(change)
    return diff


def load_report(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
