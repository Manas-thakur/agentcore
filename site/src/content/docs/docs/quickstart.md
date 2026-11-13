---
title: Quickstart (offline)
description: Run an agent, an eval suite and the web app in a few minutes with the offline mock model. No model server or API key needed.
---

Every command on this page uses the deterministic **`mock`** model, so it works without Ollama,
an API key or a network connection. Install with the `server` extra first
([Installation](/agentcore/docs/installation/)):

```bash
pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"
```

## 1. Ask a question from the CLI

```bash
agentcore chat --model mock -p "What is 17 * 23 + 4?"
```

```text
The answer is 395.
```

The agent called the `calculator` tool and wrote a trace to `.agentcore/traces/`. Drop `-p` for an
interactive chat (`--stream` streams tokens, `-v` prints every step).

## 2. Write an agent in Python

```python
from agentcore import Agent, create_model, tool
from agentcore.tools import calculator


@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get the current weather for a city.

    Args:
        city: City name, e.g. "Pune".
        unit: "celsius" or "fahrenheit".
    """
    return f"22 degrees {unit} and sunny in {city}"


agent = Agent(create_model("mock"), tools=[calculator, get_weather], max_steps=8)
result = agent.run_sync("What is 17 * 23 + 4?")
print(result.output, result.stop_reason, result.usage.total_tokens)
# The answer is 395. final 174
```

`@tool` builds the JSON Schema from the type hints and the docstring. Swap `"mock"` for
`"ollama:qwen2.5:7b"` or `"openai:gpt-4o-mini"` to use a real model
([models guide](/agentcore/docs/models/)).

## 3. Run an eval suite

Clone the repository for the examples, or use the [starter project](/agentcore/docs/project/):

```bash
git clone https://github.com/Manas-thakur/agentcore.git && cd agentcore
agentcore eval --suite examples/evals/calculator_suite.yaml --model mock
```

```text
Suite calculator-basic | model mock
  [PASS] multiply_add                 score=1.00 steps=2 contains=1.00 tool_calls=1.00 step_budget=1.00
  [PASS] parentheses                  score=1.00 steps=2 contains=1.00 tool_calls=1.00
  [PASS] power                        score=1.00 steps=2 contains=1.00 trajectory=1.00
  [PASS] division_regex               score=1.00 steps=2 regex=1.00 tool_calls=1.00
  [PASS] modulo                       score=1.00 steps=2 contains=1.00 tool_calls=1.00
Result: 5/5 passed (100%), mean score 1.00, 607 tokens
```

The exit code is 1 when a case fails or (with `--baseline`) when a regression is found, so the
same command gates CI.

## 4. Open the web app

```bash
agentcore serve --model mock
```

Open `http://127.0.0.1:8000` in a browser. The **Playground** streams replies with a run summary you can
expand into every model call and tool call; **Traces** lists every run with a query language,
facets and a span tree; **Evals** runs suites from `./evals` and `./examples/evals` and compares
runs case by case; **Overview** charts runs, latency, tokens and cost. Press `Ctrl/Cmd+K` for the
command palette and `?` for keyboard shortcuts. The [web app guide](/agentcore/docs/web-app/) covers
every page.

## 5. Call it over HTTP

```bash
curl -s -X POST http://127.0.0.1:8000/v1/agent \
     -H "Content-Type: application/json" \
     -d '{"input": "What is 2 ** 10?"}'
```

Any OpenAI client works against `/v1/chat/completions`:

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions -H "Content-Type: application/json" \
     -d '{"model": "agentcore", "messages": [{"role": "user", "content": "What is 2 ** 10?"}]}'
```

## 6. Inspect traces from the terminal

```bash
agentcore traces list --limit 3
agentcore traces show <trace-id-prefix>
```

## More examples in the repository

```bash
agentcore run examples/calculator_agent.py --model mock         # tool-using ReAct agent
python examples/rag_qa.py --model mock "How does reciprocal rank fusion work?"
python examples/workflow_graph.py                               # fan-out/join, approval, compensation
python examples/multi_agent.py --model mock                     # planner -> researcher/coder -> reviewer
agentcore research "How does HNSW search work?" --docs examples/data --model mock
```
