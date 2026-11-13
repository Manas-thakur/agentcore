---
title: "New project: agentcore init"
description: Scaffold a runnable agent project with a custom tool, an eval suite and a config file, then grow it.
---

`agentcore init` creates a small project that runs offline with the `mock` model and is wired into
every AgentCore command: the CLI chat, the eval runner and the web app.

```bash
agentcore init my-agent
cd my-agent
python agent.py --model mock "What is the capital of France?"
```

```text
The answer is Paris.
[final, 2 steps, 132 tokens, trace e095d0ec00d44f048066a8d8b8b8c933]
```

Options: `agentcore init [DIRECTORY] [--name NAME] [--force]`. The directory defaults to the
current one, the name to the directory name; existing files are never overwritten unless you pass
`--force`.

## What you get

| File | Purpose |
|---|---|
| `agent.py` | The agent, a sample `@tool` (`lookup_fact`), a `TOOLS` list and a small CLI |
| `evals/basic.yaml` | Eval suite with expected outputs, tool calls and a trajectory |
| `agentcore.toml` | Default model, enabled tools, tool modules, trace and eval directories, server settings |
| `.env.example` | Environment variables for real models and the server API key |
| `README.md`, `.gitignore` | Notes and ignores for `.agentcore/`, `.env`, virtualenvs |

The generated `agent.py` (abridged):

```python
from agentcore import Agent, create_model, tool
from agentcore.tools import calculator

FACTS = {"capital of france": "Paris", ...}


@tool(category="knowledge")
def lookup_fact(query: str) -> str:
    """Look up a fact in this project's small knowledge base.

    Args:
        query: What to look up, e.g. "capital of France".
    """
    ...


# Tools exported to `agentcore chat|eval|serve` via `tool_modules` in agentcore.toml.
TOOLS = [calculator, lookup_fact]


def build_agent(model: str | None = None) -> Agent:
    return Agent(create_model(model), tools=TOOLS, system_prompt=SYSTEM_PROMPT, max_steps=6)
```

And `agentcore.toml`:

```toml
model = "mock"                                   # mock | auto | ollama:<m> | openai:<m>
tools = ["calculator", "current_time", "lookup_fact"]
tool_modules = ["agent.py"]                      # files that define @tool functions
trace_dir = ".agentcore/traces"
eval_dirs = ["evals"]

[server]
host = "127.0.0.1"
port = 8000
cors_origins = []
max_body_kb = 1024
```

Because `tool_modules` points at `agent.py`, the custom `lookup_fact` tool is available to
`agentcore chat`, `agentcore eval`, `agentcore serve` and `agentcore tools`. If a module defines a
`TOOLS` list, only those tools are exported; otherwise every module-level `@tool` is.

## Run the evals

```bash
agentcore eval --suite evals/basic.yaml --model mock
```

```text
  [PASS] capital                      score=1.00 steps=2 contains=1.00 tool_calls=1.00
  [PASS] arithmetic                   score=1.00 steps=2 contains=1.00 tool_calls=1.00
  [PASS] speed_of_light               score=1.00 steps=2 contains=1.00 trajectory=1.00
Result: 3/3 passed (100%), mean score 1.00, 537 tokens
```

Gate CI on it: by default every case must pass (`--fail-under 1.0`; use e.g. `--fail-under 0.9`
to tolerate some failures). Or keep a baseline and fail on regressions; the first command writes
it, and the second fails with exit 2 if the baseline file is missing:

```bash
agentcore eval --suite evals/basic.yaml --model mock --baseline eval-baseline.json --save-baseline
agentcore eval --suite evals/basic.yaml --model mock --baseline eval-baseline.json
```

## Open the web app

```bash
agentcore serve --model mock
```

The Evals page lists `evals/basic.yaml` (from `eval_dirs`), the Tools page shows `lookup_fact`
with its generated schema and a try-it form, and every chat writes traces to `.agentcore/traces`.

## Next steps

- Add tools to `agent.py`. Type hints and the docstring become the JSON Schema; arguments are
  validated and coerced before your function runs ([Tools](/agentcore/docs/modules/tools/)).
- Add eval cases: expected outputs (`contains`, `exact`, `regex`), expected tool calls with
  arguments, ordered trajectories, step budgets, or an LLM-as-judge rubric
  ([Eval](/agentcore/docs/modules/eval/)).
- Switch to a real model: `--model ollama:qwen2.5:7b` or `--model openai:gpt-4o-mini`
  ([Models](/agentcore/docs/models/)), and add it to `models` in `agentcore.toml` so the web app's
  model picker lists it.
- Check your setup at any time with `agentcore doctor` (add `--ping` to send one tiny request to
  the model).
