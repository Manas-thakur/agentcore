"""Eval suites for the web UI: discovery, background runs with progress, history and baselines."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentcore.eval import EvalRun, EvalRunner, compare, load_suite
from agentcore.eval.suite import EvalSuite, SuiteError, read_suite_file

SUITE_SUFFIXES = (".yaml", ".yml", ".json")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "suite"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _is_history_file(path: Path, history_root: Path) -> bool:
    """``<state>/evals/<suite>/runs/<id>.json`` or ``<state>/evals/<suite>/baseline.json``."""
    if path.parent.name == "runs":
        return path.parent.parent.parent == history_root
    return path.name == "baseline.json" and path.parent.parent == history_root


def _elapsed(started_at: str | None, finished_at: str | None) -> float | None:
    """Seconds from start to finish (or to now while the run is still going)."""
    try:
        start = datetime.fromisoformat(started_at).timestamp() if started_at else None
        end = datetime.fromisoformat(finished_at).timestamp() if finished_at else time.time()
    except ValueError:
        return None
    return None if start is None else round(max(end - start, 0.0), 1)


@dataclass
class EvalJob:
    id: str
    suite: str
    suite_path: str
    model: str
    total: int
    status: str = "queued"  # queued | running | completed | failed
    done: int = 0
    passed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=_now_iso)
    finished_at: str | None = None
    error: str | None = None
    report: dict[str, Any] | None = None
    task: asyncio.Task[Any] | None = field(default=None, repr=False)

    def to_dict(self, *, full: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "suite": self.suite,
            "suite_path": self.suite_path,
            "model": self.model,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "passed": self.passed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "summary": (self.report or {}).get("summary"),
        }
        if full:
            data["results"] = (self.report or {}).get("runs", self.results)
        return data


class EvalDirError(OSError):
    """The eval directory cannot be written (e.g. permission denied in a container)."""


class AmbiguousSuiteError(ValueError):
    """Several suite files share the requested name."""


STARTER_SUITE_YAML = """# Starter eval suite created from the AgentCore web app.
#
#   agentcore eval --suite evals/starter.yaml --model mock
#
# Each case checks the final answer and, where given, the tool calls the agent made.
# Add your own cases below; see `agentcore init` for a full project template.
name: starter
description: Arithmetic that must go through the calculator tool. Passes offline with the mock model.
agent:
  system_prompt: >-
    You are a careful math assistant. Always use the calculator tool for arithmetic,
    then state the final numeric answer.
  tools: [calculator]
  max_steps: 4

cases:
  - name: multiply_add
    input: "What is 17 * 23 + 4?"
    expected_output: "395"
    expected_tool_calls:
      - tool: calculator
        args: {expression: "17 * 23 + 4"}
    tags: [arithmetic]

  - name: parentheses
    input: "Compute (12 + 8) * 3 - 5."
    expected_output: "55"
    expected_tool_calls: [calculator]
    tags: [arithmetic]

  - name: power
    input: "What is 2 ** 10?"
    expected_output: "1024"
    expected_trajectory: [calculator]
    tags: [arithmetic]
"""


class EvalManager:
    def __init__(
        self,
        dirs: list[str],
        state_dir: str | Path,
        *,
        default_model: str | None = None,
        tools: dict[str, Any] | None = None,
        concurrency: int = 4,
    ):
        self.dirs = list(dirs)
        self.root = Path(state_dir) / "evals"
        self.default_model = default_model
        self.tools = dict(tools or {})
        self.concurrency = concurrency
        self.jobs: dict[str, EvalJob] = {}

    # --- discovery ----------------------------------------------------------------------
    def discover(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[Path] = set()
        history_root = self.root.resolve()
        for d in self.dirs:
            root = Path(d)
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() not in SUITE_SUFFIXES or not path.is_file():
                    continue
                rp = path.resolve()
                if rp in seen or _is_history_file(rp, history_root):
                    continue  # already listed, or eval history stored next to the suites
                seen.add(rp)
                info: dict[str, Any] = {"path": _display_path(path), "dir": _display_path(root)}
                try:
                    data = read_suite_file(path)
                    if not isinstance(data, dict) or "cases" not in data:
                        continue  # e.g. a JSON report or cassette that happens to live here
                    suite = EvalSuite.from_dict(data, info["path"])
                except (OSError, SuiteError) as exc:  # malformed files are listed, not fatal
                    info.update(name=path.stem, error=str(exc), cases=0)
                    out.append(info)
                    continue
                if not suite.cases:
                    continue
                info.update(
                    name=suite.name,
                    description=suite.description,
                    cases=len(suite.cases),
                    tools=suite.agent.tools,
                    model=suite.agent.model,
                    tags=sorted({t for c in suite.cases for t in c.tags}),
                    case_names=[c.name for c in suite.cases],
                )
                info["last_run"] = next(iter(self.history(suite.name, limit=1)), None)
                info["baseline"] = self.baseline_id(suite.name)
                out.append(info)
        names = [s["name"] for s in out if not s.get("error")]
        for s in out:
            if not s.get("error") and names.count(s["name"]) > 1:
                s["duplicate_name"] = True  # run it by path; the name is ambiguous
        return out

    def create_starter(self) -> dict[str, Any]:
        """Write a small calculator suite into the first eval directory.

        Gives people without the repository's ``examples/`` a suite to run from the web
        app straight away. Never overwrites a file. Raises :class:`EvalDirError` when the
        directory is not writable (e.g. a read-only container working directory).
        """
        if not self.dirs:
            raise ValueError("No eval directories are configured")
        target = Path(self.dirs[0]) / "starter.yaml"
        if target.exists():
            raise FileExistsError(f"{_display_path(target)} already exists")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as fh:
                fh.write(STARTER_SUITE_YAML)
        except FileExistsError:
            raise FileExistsError(f"{_display_path(target)} already exists") from None
        except OSError as exc:
            reason = (exc.strerror or type(exc).__name__).lower()
            raise EvalDirError(
                f"cannot write to {_display_path(target.parent)}: {reason}; set eval_dirs in "
                "agentcore.toml (or AGENTCORE_EVAL_DIRS) to a writable folder"
            ) from exc
        return {"path": _display_path(target), "name": load_suite(target).name}

    def _find_suite(self, ref: str) -> Path:
        suites = [s for s in self.discover() if not s.get("error")]
        for s in suites:
            if ref == s["path"]:
                return Path(s["path"])
        named = [s for s in suites if ref == s["name"]]
        if len(named) > 1:
            paths = ", ".join(s["path"] for s in named)
            raise AmbiguousSuiteError(
                f"suite name {ref!r} is used by several files ({paths}); run one by its path"
            )
        if named:
            return Path(named[0]["path"])
        broken = [s for s in self.discover() if s.get("error") and ref in (s["path"], s["name"])]
        if broken:
            raise SuiteError(broken[0]["error"])
        raise KeyError(f"eval suite {ref!r} not found; GET /api/evals/suites lists the suites")

    # --- running ------------------------------------------------------------------------
    def start(
        self, suite_ref: str, model: str | None = None, tags: list[str] | None = None
    ) -> EvalJob:
        path = self._find_suite(suite_ref)
        suite: EvalSuite = load_suite(path)
        if tags:
            suite = suite.filter(tags=tags)
        spec = model or suite.agent.model or self.default_model or "auto"
        runner = EvalRunner(spec, concurrency=self.concurrency, tools=self.tools)
        job = EvalJob(
            id=f"ev_{datetime.now().strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:6]}",
            suite=suite.name,
            suite_path=_display_path(path),
            model=spec,
            total=len(suite.cases),
        )
        self.jobs[job.id] = job

        def on_result(run: EvalRun) -> None:
            job.done += 1
            job.passed += int(run.passed)
            job.results.append(run.to_dict())

        async def execute() -> None:
            job.status = "running"
            try:
                report = await runner.run_suite(suite, on_result=on_result)
                job.model = report.model
                job.report = report.to_dict()
                job.status = "completed"
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.finished_at = _now_iso()
                self._persist(job)

        job.task = asyncio.get_running_loop().create_task(execute())
        return job

    async def wait(self, job_id: str, timeout: float = 60.0) -> EvalJob:
        job = self.jobs[job_id]
        if job.task is not None:
            await asyncio.wait_for(asyncio.shield(job.task), timeout)
        return job

    # --- storage ------------------------------------------------------------------------
    def _suite_dir(self, suite_name: str) -> Path:
        return self.root / slugify(suite_name)

    def _persist(self, job: EvalJob) -> None:
        d = self._suite_dir(job.suite) / "runs"
        d.mkdir(parents=True, exist_ok=True)
        data = job.to_dict(full=False)
        data["report"] = job.report
        (d / f"{job.id}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _load_run(self, run_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            return None
        for path in self.root.glob(f"*/runs/{run_id}.json"):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return None

    def history(self, suite_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        pattern = f"{slugify(suite_name)}/runs/*.json" if suite_name else "*/runs/*.json"
        files = sorted(self.root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        out = []
        for path in files[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            data.pop("report", None)
            data["is_baseline"] = data.get("id") == self.baseline_id(data.get("suite", ""))
            out.append(data)
        return out

    def baseline_id(self, suite_name: str) -> str | None:
        f = self._suite_dir(suite_name) / "baseline.json"
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("run_id")
        except (OSError, ValueError):
            return None

    def set_baseline(self, run_id: str) -> dict[str, Any]:
        run = self._load_run(run_id)
        if run is None or run.get("status") != "completed":
            raise KeyError(f"completed eval run {run_id!r} not found")
        d = self._suite_dir(run["suite"])
        d.mkdir(parents=True, exist_ok=True)
        (d / "baseline.json").write_text(
            json.dumps({"run_id": run_id, "set_at": _now_iso()}), encoding="utf-8"
        )
        return {"suite": run["suite"], "baseline": run_id}

    def matrix(self, suite_ref: str, limit: int = 8) -> dict[str, Any]:
        """Cases x the last ``limit`` completed runs of a suite (oldest column first).

        A cell is ``regressed`` when the case passed in the previous column and fails now,
        or its score dropped; ``baseline_regressed`` compares against the baseline run."""
        name, case_order = suite_ref, []
        for s in self.discover():
            if suite_ref in (s.get("path"), s.get("name")) and not s.get("error"):
                name, case_order = s["name"], list(s.get("case_names") or [])
                break
        runs: list[dict[str, Any]] = []
        files = sorted(
            self._suite_dir(name).glob("runs/*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("status") == "completed" and data.get("report"):
                runs.append(data)
            if len(runs) >= limit:
                break
        runs.sort(key=lambda r: (r.get("started_at") or "", r.get("id") or ""))
        base_id = self.baseline_id(name)
        base_cases: dict[str, dict[str, Any]] = {}
        base = next((r for r in runs if r["id"] == base_id), None) or (
            self._load_run(base_id) if base_id else None
        )
        if base and base.get("report"):
            base_cases = {r["case"]: r for r in base["report"].get("runs", [])}
        by_run = [{r["case"]: r for r in run["report"].get("runs", [])} for run in runs]
        for results in by_run:
            for case in results:
                if case not in case_order:
                    case_order.append(case)
        rows = []
        regressions = 0
        for case in case_order:
            cells: list[dict[str, Any] | None] = []
            prev: dict[str, Any] | None = None
            tags: list[str] = []
            for run, results in zip(runs, by_run):
                r = results.get(case)
                if r is None:
                    cells.append(None)
                    continue
                tags = r.get("tags") or tags
                regressed = prev is not None and (
                    (prev["passed"] and not r["passed"]) or r["score"] < prev["score"] - 1e-3
                )
                b = base_cases.get(case)
                cell = {
                    "run_id": run["id"],
                    "passed": r["passed"],
                    "score": r["score"],
                    "duration_ms": r.get("duration_ms"),
                    "steps": r.get("steps"),
                    "error": r.get("error"),
                    "failing": [m["name"] for m in r.get("metrics", []) if not m.get("passed")],
                    "regressed": bool(regressed),
                    "baseline_regressed": bool(
                        b and run["id"] != base_id and b["passed"] and not r["passed"]
                    ),
                }
                regressions += int(cell["regressed"])
                cells.append(cell)
                prev = r
            rows.append({"case": case, "tags": tags, "cells": cells})
        return {
            "suite": name,
            "baseline": base_id,
            "runs": [
                {
                    "id": r["id"],
                    "started_at": r.get("started_at"),
                    "model": r.get("model"),
                    "summary": (r.get("report") or {}).get("summary"),
                    "is_baseline": r["id"] == base_id,
                }
                for r in runs
            ],
            "cases": rows,
            "regressions": regressions,
        }

    def get(self, run_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(run_id)
        if job is not None and job.status in ("queued", "running"):
            data = job.to_dict()
        else:
            stored = self._load_run(run_id)
            if stored is None:
                return None
            data = dict(stored)
            report = data.pop("report", None) or {}
            data["summary"] = report.get("summary")
            data["results"] = report.get("runs", [])
            data["report"] = report
        data["baseline"] = None
        data["diff"] = None
        suite = data.get("suite", "")
        base_id = self.baseline_id(suite)
        data["is_baseline"] = base_id == run_id
        if base_id and base_id != run_id and data.get("status") == "completed":
            base = self._load_run(base_id)
            if base and base.get("report"):
                current = data.get("report") or {
                    "summary": data.get("summary"),
                    "runs": data["results"],
                }
                diff = compare(base["report"], current)
                data["diff"] = diff.to_dict()
                data["baseline"] = {
                    "id": base_id,
                    "started_at": base.get("started_at"),
                    "model": base.get("model"),
                    "summary": base["report"].get("summary"),
                    "cases": {
                        r["case"]: {
                            "passed": r["passed"],
                            "score": r["score"],
                            "metrics": {m["name"]: m["score"] for m in r.get("metrics", [])},
                        }
                        for r in base["report"].get("runs", [])
                    },
                }
        data.pop("report", None)
        data["elapsed_s"] = _elapsed(data.get("started_at"), data.get("finished_at"))
        return data
