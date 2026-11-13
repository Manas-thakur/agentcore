"""``agentcore init``: scaffold a new agent project that runs offline with ``--model mock``."""

from __future__ import annotations

import re
from pathlib import Path

AGENT_PY = '''"""{name}: a tool-using agent built with AgentCore.

Run it offline (no model server needed):

    python agent.py --model mock "What is the capital of France?"
    agentcore chat --model mock
    agentcore eval --suite evals/basic.yaml --model mock
    agentcore serve --model mock          # web app at http://127.0.0.1:8000

Switch to a real model with --model ollama:qwen2.5:7b or --model openai:gpt-4o-mini.
"""

from __future__ import annotations

import argparse

from agentcore import Agent, create_model, tool
from agentcore.obs import configure_tracing
from agentcore.tools import calculator

FACTS = {{
    "capital of france": "Paris",
    "speed of light": "299,792,458 metres per second",
    "boiling point of water": "100 degrees Celsius at sea level",
}}


@tool(category="knowledge")
def lookup_fact(query: str) -> str:
    """Look up a fact in this project's small knowledge base.

    Args:
        query: What to look up, e.g. "capital of France".
    """
    q = query.lower()
    for key, value in FACTS.items():
        if key in q:
            return value
    return "No matching fact found."


# Tools exported to `agentcore chat|eval|serve` via `tool_modules` in agentcore.toml.
TOOLS = [calculator, lookup_fact]

SYSTEM_PROMPT = (
    "You are a concise assistant. Use lookup_fact for factual questions and calculator for "
    "arithmetic, then answer in one sentence."
)


def build_agent(model: str | None = None) -> Agent:
    return Agent(
        create_model(model),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        max_steps=6,
        name="{slug}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", nargs="?", default="What is the capital of France?")
    parser.add_argument("--model", default=None, help="mock | auto | ollama:<m> | openai:<m>")
    args = parser.parse_args()
    configure_tracing(".agentcore/traces")
    result = build_agent(args.model).run_sync(args.question)
    print(result.output)
    print(
        f"[{{result.stop_reason}}, {{result.steps}} steps, {{result.usage.total_tokens}} tokens, "
        f"trace {{result.trace_id}}]"
    )


if __name__ == "__main__":
    main()
'''

BASIC_YAML = """# Eval suite for the starter agent.
#
#   agentcore eval --suite evals/basic.yaml --model mock
#
# Custom tools (lookup_fact) are found through `tool_modules` in agentcore.toml.
name: {slug}-basic
description: Smoke tests for the starter agent; passes offline with the mock model.
agent:
  tools: [calculator, lookup_fact]
  max_steps: 4

cases:
  - name: capital
    input: "What is the capital of France?"
    expected_output: "Paris"
    expected_tool_calls: [lookup_fact]
    tags: [facts]

  - name: arithmetic
    input: "What is 6 * 7?"
    expected_output: "42"
    expected_tool_calls:
      - tool: calculator
        args: {{expression: "6 * 7"}}
    tags: [math]

  - name: speed_of_light
    input: "Look up the speed of light."
    expected_output: "299,792,458"
    expected_trajectory: [lookup_fact]
    tags: [facts]
"""

CONFIG_TOML = """# AgentCore project configuration. CLI flags and AGENTCORE_* env vars take precedence.
model = "mock"                                   # mock | auto | ollama:<m> | openai:<m>
tools = ["calculator", "current_time", "lookup_fact"]
tool_modules = ["agent.py"]                      # files that define @tool functions
trace_dir = ".agentcore/traces"
eval_dirs = ["evals"]

[server]
host = "127.0.0.1"
port = 8000
cors_origins = []                                # e.g. ["http://localhost:5173"]
max_body_kb = 1024
"""

ENV_EXAMPLE = """# Copy to .env and fill in what you need (AgentCore reads the process environment;
# load it with your shell, direnv, or `set -a; . ./.env; set +a`).

# Default model when --model is not given: mock | auto | ollama:<m> | openai:<m>
AGENTCORE_MODEL=mock

# Ollama (https://ollama.com)
OLLAMA_HOST=http://localhost:11434

# OpenAI or any OpenAI-compatible server (vLLM, LM Studio, Groq, ...)
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1

# Protect `agentcore serve` with an API key (the web app asks for it once)
AGENTCORE_API_KEY=
"""

README_MD = """# {name}

A tool-using agent built with [AgentCore](https://github.com/Manas-thakur/agentcore).
Everything below runs offline with the deterministic `mock` model.

```bash
# AgentCore installs from GitHub (the `agentcore` package on PyPI is a different project)
pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"

python agent.py --model mock "What is the capital of France?"
agentcore eval --suite evals/basic.yaml --model mock
agentcore chat --model mock
agentcore serve --model mock        # web app at http://127.0.0.1:8000
agentcore doctor                    # check your environment and model reachability
```

## Layout

| File | Purpose |
|---|---|
| `agent.py` | The agent, a sample `@tool` (`lookup_fact`) and a small CLI |
| `evals/basic.yaml` | Eval suite: expected outputs, tool calls and trajectories |
| `agentcore.toml` | Default model, enabled tools, tool modules, trace and eval dirs |
| `.env.example` | Environment variables for real models and the server API key |

## Next steps

- Add tools to `agent.py` (type hints + docstring become the JSON Schema) and list them in
  `TOOLS`; they show up in `agentcore chat`, the eval runner and the web app.
- Point at a real model: `--model ollama:qwen2.5:7b` or `--model openai:gpt-4o-mini`.
- Add eval cases and gate CI on them: `agentcore eval --suite evals/basic.yaml --fail-under 1.0`.
"""

GITIGNORE = """.agentcore/
workspace/
.env
__pycache__/
.venv/
"""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"


def scaffold(target: str | Path, *, name: str | None = None, force: bool = False) -> list[Path]:
    """Create the project files in ``target``. Returns the written paths.

    Existing files are never overwritten unless ``force`` is set.
    """
    root = Path(target)
    title = name or root.resolve().name or "my-agent"
    slug = slugify(title)
    files = {
        "agent.py": AGENT_PY.format(name=title, slug=slug),
        "evals/basic.yaml": BASIC_YAML.format(slug=slug),
        "agentcore.toml": CONFIG_TOML,
        ".env.example": ENV_EXAMPLE,
        "README.md": README_MD.format(name=title),
        ".gitignore": GITIGNORE,
    }
    existing = [rel for rel in files if (root / rel).exists()]
    if existing and not force:
        raise FileExistsError(
            f"{root} already contains {', '.join(existing)}; use --force to overwrite"
        )
    written = []
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
