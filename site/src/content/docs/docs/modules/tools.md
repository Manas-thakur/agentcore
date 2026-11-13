---
title: Tools
description: Turn typed Python functions into JSON-Schema tools with validation, retries, rate limits and a subprocess sandbox.
---

`agentcore.tools` turns ordinary Python functions into tools a model can call, validates the
arguments the model sends, and executes them with timeouts, retries and rate limits.

## `@tool`

```python
import asyncio
from dataclasses import dataclass
from typing import Literal

from agentcore.tools import ExecutionEngine, SandboxConfig, SubprocessSandbox, ToolRegistry, tool


@dataclass
class Point:
    x: float
    y: float = 0.0


@tool(timeout=5, retries=1, category="geometry")
def distance(a: Point, b: Point, metric: Literal["euclid", "manhattan"] = "euclid") -> float:
    """Distance between two points.

    Args:
        a: First point.
        b: Second point.
        metric: Distance metric.
    """
    if metric == "manhattan":
        return abs(a.x - b.x) + abs(a.y - b.y)
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


print(distance.parameters)  # JSON Schema: dataclass -> nested object, Literal -> enum
engine = ExecutionEngine(ToolRegistry([distance]))
res = asyncio.run(engine.execute("distance", {"a": {"x": "3"}, "b": {"x": 0, "y": 4}}))
print(res.success, res.output)  # True 5.0  ("3" was coerced to 3.0)

sandbox = SubprocessSandbox(SandboxConfig(timeout_seconds=5))
print(sandbox.run("print(sum(range(10)))").stdout)  # 45
```

The generated schema for `distance`:

```json
{
  "type": "object",
  "properties": {
    "a": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number", "default": 0.0}}, "required": ["x"], "description": "First point."},
    "b": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number", "default": 0.0}}, "required": ["x"], "description": "Second point."},
    "metric": {"enum": ["euclid", "manhattan"], "type": "string", "description": "Distance metric.", "default": "euclid"}
  },
  "required": ["a", "b"]
}
```

`tool(fn=None, *, name, description, category="general", timeout=30.0, retries=None,
strict=False, **metadata)`. `retries=None` (the default) uses the engine's
`RetryPolicy.max_retries` (2); `retries=0` disables retries for that tool; `retries=N` allows N
retries. Supported parameter types: `str`, `int`, `float`, `bool`, `list[...]`,
`dict[str, ...]`, `Optional`, `Union`, `Literal`, `Enum`, dataclasses, `TypedDict` and (with the
`pydantic` extra) pydantic models. Descriptions come from Google-, NumPy- or Sphinx-style
docstrings. Sync and async functions both work.

## Execution

`ExecutionEngine(registry, *, default_timeout=30.0, retry_policy, max_concurrency=8,
rate_limits, before, after)`:

- **Validation and coercion**: arguments are checked against the schema; `"3"` becomes `3.0` for a
  `float`, nested objects become dataclasses. Invalid input returns a `ToolValidationError` result
  the model can read and correct.
- **Timeouts and retries** per tool (`timeout`, `retries`) with an exponential-backoff
  `RetryPolicy` (by default it retries timeouts, rate-limit errors and `ToolTransientError`).
- **Rate limits** with token buckets (`rate_limits={"http_get": TokenBucket(...)}`).
- **Hooks**: `before` and `after` each take a single callable or a list of callables, sync or
  async. `before(name, kwargs)` runs after validation, before the tool; `after(result)` gets every
  `ToolResult`, e.g. for audit logs:

  ```python
  engine = ExecutionEngine(registry, before=lambda name, kwargs: print("->", name, kwargs),
                           after=[audit_log, metrics_hook])
  ```
- **Results**, not exceptions: `ToolResult(success, output, error, error_type, latency_ms,
  attempts)`. `result.as_text(n)` gives the size-bounded text the model sees.

## Sandbox

`SubprocessSandbox(SandboxConfig(...))` runs Python in an isolated interpreter in a temporary
directory with a timeout, POSIX resource limits (memory, CPU time), network access disabled (unless
`network_access=True`), an optional import allow-list (`allowed_imports`) and deny-list
(`blocked_imports`). Both lists apply to imports written in the sandboxed code; the standard
library's own imports keep working. This is best-effort isolation: use containers for untrusted,
multi-tenant code.

The built-in `python_exec` tool uses the sandbox with a deny-list of modules that reach the OS,
processes or the network (`os`, `subprocess`, `socket`, `shutil`, `ctypes`, `multiprocessing`,
`signal`, `importlib`, ...: `agentcore.tools.builtins.python_exec.DEFAULT_BLOCKED_IMPORTS`). Build
your own variant with `make_python_exec(SandboxConfig(...))`: `blocked_imports=[]` lifts the
deny-list, `allowed_imports=["math", "statistics"]` switches to an allow-list. Code that runs past
the sandbox timeout (10 s by default) is a failed call (`success=False`,
`error_type="ToolTimeoutError"`, with any output produced so far) and is not retried.

:::caution[Windows limitations]
Windows has no `resource` module, so `memory_limit_mb` and `cpu_time_seconds` are **not
enforced** there; only the wall-clock timeout, the network block and the import lists apply. The
import lists are a speed bump, not a security boundary (sandboxed code can still reach the OS
through objects it already has). On Windows, and for any untrusted code, run AgentCore in a
container (see [Deployment](/agentcore/docs/deployment/)).
:::

## Built-in tools

```bash
agentcore tools          # add --schema for the JSON Schemas
```

| Tool | Category | What it does |
|---|---|---|
| `calculator` | math | Evaluates arithmetic with an AST walker (no `eval`) |
| `current_time` | utilities | Current UTC date and time in ISO 8601 |
| `python_exec` | code | Runs Python in the subprocess sandbox |
| `http_get` | web | Fetches a URL and returns readable text |
| `web_search` | web | DuckDuckGo HTML search: title, url, snippet |
| `read_file`, `write_file`, `list_files` | filesystem | Workspace-scoped file access with path-traversal checks |

Only `calculator` and `current_time` are enabled in `agentcore serve` by default. Enable others
with `--tools` or `tools` in `agentcore.toml`, and think twice before exposing `python_exec`, the
web tools or the file tools on a network. The web app's Tools page asks for confirmation before
invoking a tool that runs code, writes files or makes network requests.

## Custom tools in the CLI and web app

List Python files or modules in `tool_modules` (in `agentcore.toml`); their `@tool` functions (or
the module's `TOOLS` list) become available to `agentcore chat`, `eval`, `serve` and `tools`. See
[New project](/agentcore/docs/project/).
