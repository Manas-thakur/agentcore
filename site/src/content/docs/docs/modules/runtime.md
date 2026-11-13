---
title: Runtime
description: The ReAct agent loop, model clients, streaming, events, memory tiers and context budgeting.
---

`agentcore.runtime` contains the agent loop and everything it needs: model clients for Ollama,
OpenAI-compatible servers and the offline mock, memory tiers and a context-window manager.

## Agents

```python
from agentcore import Agent, create_model, tool
from agentcore.runtime import SlidingWindowMemory
from agentcore.tools import calculator


@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get the current weather for a city.

    Args:
        city: City name, e.g. "Pune".
        unit: "celsius" or "fahrenheit".
    """
    return f"22 degrees {unit} and sunny in {city}"


agent = Agent(
    create_model("mock"),  # or "ollama:qwen2.5:7b", "openai:gpt-4o-mini"
    tools=[calculator, get_weather],
    memory=SlidingWindowMemory(max_turns=5),
    max_steps=8,
)
agent.on(lambda ev: print(ev.type, ev.data.get("name", "")))  # event callbacks
result = agent.run_sync("What is 17 * 23 + 4?")
print(result.output, result.stop_reason, result.usage.total_tokens)
```

```text
run_start
step_start
model_response
tool_start calculator
tool_end calculator
step_start
model_response
final
run_end
The answer is 395. final 174
```

`Agent(model, tools, *, system_prompt, config, memory, callbacks, reflection_hook, name, tracer,
cost_tracker, engine, **config_overrides)`. Keyword overrides set `AgentConfig` fields, for
example `max_steps` (default 10), `timeout_seconds`, `stuck_threshold` (identical tool calls
before the agent is nudged), `reflect_every`, `context_window`, `max_tool_output_tokens`,
`parallel_tool_calls`, `stream`, `temperature`, `max_tokens` and `trace_content`.

- `await agent.run(task)` is the async API; `agent.run_sync(task)` wraps it. A task is a string or
  a list of `Message`s.
- `AgentResult` has `output`, `stop_reason` (`final`, `max_steps`, `timeout` or `error`),
  `steps`, `usage`, `tool_results`, `tool_calls`, `trace_id`, `duration_ms`, `error`, the full
  `messages` and the recorded `events`.
- `agent.as_tool()` turns an agent into a tool for another agent.
- `reflect_every=N` adds periodic self-reflection; `reflection_hook=fn` lets you inject your own.
- `trace_content=False` stops model spans from recording prompts and responses.

## Streaming and events

```python
import asyncio

from agentcore import Agent, create_model
from agentcore.tools import calculator


async def main() -> None:
    agent = Agent(create_model("mock"), tools=[calculator], stream=True)
    async for ev in agent.stream("What is 2 ** 10?"):
        if ev.type == "token":
            print(ev.data["content"], end="", flush=True)
        elif ev.type == "tool_start":
            print(f"\n-> {ev.data['name']}({ev.data['arguments']})")
    print()


asyncio.run(main())
```

```text

-> calculator({'expression': '2 ** 10'})
The answer is 1024.
```

Event types: `run_start`, `step_start`, `token` (with `stream=True`), `model_response`,
`tool_start`, `tool_end`, `reflection`, `final`, `error`, `run_end`. The web app's `/api/chat` endpoint
forwards exactly these events over Server-Sent Events.

## Model clients

| Spec | Client | Notes |
|---|---|---|
| `mock` | `MockModel` | Deterministic, rule-based: calls the calculator for arithmetic, search tools for questions, answers from tool results. Streams word by word. |
| `ollama:<model>` | `OllamaClient` | Native Ollama API at `OLLAMA_HOST` (default `http://localhost:11434`) |
| `openai:<model>` | `OpenAICompatibleClient` | Any OpenAI-compatible server at `OPENAI_BASE_URL` with `OPENAI_API_KEY` |
| `vllm:`, `lmstudio:`, `groq:` | `OpenAICompatibleClient` | Aliases of `openai:` |
| `auto` | Ollama or `MockModel` | Ollama if reachable and `AGENTCORE_OLLAMA_MODEL` (default `qwen2.5:7b`) is pulled, otherwise mock |

`ScriptedModel([...])` replays fixed responses for unit tests. Every client reports token usage
and latency, and costs come from `agentcore.obs.PRICE_TABLE`.

## Memory

| Class | Keeps |
|---|---|
| `BufferMemory` | Messages up to a message or token budget |
| `SlidingWindowMemory(max_turns)` | The last N turns (a turn starts at each user message) |
| `SummarizingMemory(model)` | Recent turns plus a structured summary of older ones, written by the model |
| `LongTermMemory` | Vector recall with importance scores |
| `HybridMemory` | A sliding window plus long-term recall |

All memories support `save()` / `load()`. Chat sessions in the web app use
`SlidingWindowMemory(10)`.

## Context budgeting

Set `context_window=<tokens>` and the agent fits the message list into the budget with
`ContextManager` before each model call: it first compresses oversized tool outputs, then drops
the oldest turns (keeping tool-call / tool-result pairs together, the system prompt and the latest
user message). Token counts use
`tiktoken` when it is installed and a calibrated heuristic otherwise.
