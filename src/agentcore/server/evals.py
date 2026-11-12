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
from agentcore.eval.suite import EvalSuite

SUITE_SUFFIXES = (".yaml", ".yml", ".json")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "suite"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


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


STARTER_SUITE_YAML = """# Starter eval suite created from the AgentCore dashboard.
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
        for d in self.dirs:
            root = Path(d)
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() not in SUITE_SUFFIXES or not path.is_file():
                    continue
                rp = path.resolve()
                if rp in seen:
                    continue
                seen.add(rp)
                info: dict[str, Any] = {"path": _display_path(path), "dir": d}
                try:
                    suite = load_suite(path)
                except Exception as exc:  # malformed files are listed, not fatal
                    info.update(name=path.stem, error=f"{type(exc).__name__}: {exc}", cases=0)
                    out.append(info)
                    continue
                if not suite.cases:
                    continue  # e.g. a JSON report or cassette that happens to live here
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
        return out

    def create_starter(self) -> dict[str, Any]:
        """Write a small calculator suite into the first eval directory.

        Gives people who installed from PyPI (and so have no ``examples/``) a
        suite to run from the dashboard straight away. Never overwrites a file.
        """
        if not self.dirs:
            raise ValueError("No eval directories are configured")
        target = Path(self.dirs[0]) / "starter.yaml"
        if target.exists():
            raise FileExistsError(f"{_display_path(target)} already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(STARTER_SUITE_YAML, encoding="utf-8")
        return {"path": _display_path(target), "name": load_suite(target).name}

    def _find_suite(self, ref: str) -> Path:
        for s in self.discover():
            if ref in (s["path"], s["name"]) and not s.get("error"):
                return Path(s["path"])
        raise KeyError(f"eval suite {ref!r} not found in {self.dirs}")

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
        data["elapsed_s"] = None
        if job is not None and job.status in ("queued", "running"):
            try:
                started = datetime.fromisoformat(job.started_at)
                data["elapsed_s"] = round(time.time() - started.timestamp(), 1)
            except ValueError:
                pass
        return data
