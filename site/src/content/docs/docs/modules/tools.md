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

`tool(fn=None, *, name, description, category="general", timeout=30.0, retries=0, strict=False,
**metadata)`. Supported parameter types: `str`, `int`, `float`, `bool`, `list[...]`,
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
  `RetryPolicy` (by default it retries timeouts and rate-limit errors).
- **Rate limits** with token buckets (`rate_limits={"http_get": TokenBucket(...)}`).
- **Hooks**: `before(name, args)` and `after(result)` callbacks, e.g. for audit logs.
- **Results**, not exceptions: `ToolResult(success, output, error, error_type, latency_ms,
  attempts)`. `result.as_text(n)` gives the size-bounded text the model sees.

## Sandbox

`SubprocessSandbox(SandboxConfig(...))` runs Python in an isolated interpreter in a temporary
directory with a timeout, POSIX resource limits (memory, CPU time), network access disabled (unless
`network_access=True`) and an optional import allow-list. `python_exec` uses it. This is best-effort isolation: use containers
for untrusted, multi-tenant code.

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
