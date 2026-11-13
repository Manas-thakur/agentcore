---
title: Ollama and OpenAI-compatible models
description: Use a local model through Ollama, OpenAI, or any OpenAI-compatible server such as vLLM, LM Studio, llama.cpp or Groq.
---

A model is selected with one string, everywhere: `--model` on the CLI, `model` in
`agentcore.toml`, `AGENTCORE_MODEL`, `agent.model` in an eval suite, `create_model()` in Python and
the model picker in the web app.

| Spec | Backend |
|---|---|
| `mock` | Offline deterministic mock (no server) |
| `auto` | Ollama if it is reachable and the model is pulled, otherwise `mock` (it prints which) |
| `ollama:<model>` | Ollama's native API |
| `openai:<model>` | OpenAI or any OpenAI-compatible `/v1/chat/completions` server |
| `vllm:<model>`, `lmstudio:<model>`, `groq:<model>` | Aliases of `openai:` |

Tool calling uses each backend's native tool-calling API, so pick a model that supports it.

## Ollama

```bash
ollama pull qwen2.5:7b
agentcore chat --model ollama:qwen2.5:7b
agentcore serve --model ollama:qwen2.5:7b
python examples/calculator_agent.py --model ollama:qwen2.5:7b "What is 2**20 - 1?"
```

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Where Ollama listens |
| `AGENTCORE_OLLAMA_MODEL` | `qwen2.5:7b` | The model `auto` tries |

`agentcore serve` lists the models Ollama has pulled in the web app's model picker (it asks Ollama
at most every 30 seconds and ignores it when it is not running).

## OpenAI

```bash
export OPENAI_API_KEY=sk-...
agentcore chat --model openai:gpt-4o-mini
```

## Other OpenAI-compatible servers

Set `OPENAI_BASE_URL` to the server's `/v1` URL (and `OPENAI_API_KEY` if it needs one):

```bash
# vLLM
export OPENAI_BASE_URL=http://localhost:8000/v1
agentcore chat --model openai:Qwen/Qwen2.5-7B-Instruct

# LM Studio
export OPENAI_BASE_URL=http://localhost:1234/v1
agentcore chat --model lmstudio:qwen2.5-7b-instruct

# llama.cpp server
export OPENAI_BASE_URL=http://localhost:8080/v1
agentcore chat --model openai:local
```

If you also run `agentcore serve` on port 8000, give one of them another port.

## Check reachability

```bash
agentcore doctor --model ollama:qwen2.5:7b --ping
```

`--ping` sends one tiny request so you know the model answers before you start an eval run.

## In Python

```python
from agentcore import Agent, create_model
from agentcore.runtime import OllamaClient, OpenAICompatibleClient

agent = Agent(create_model("ollama:qwen2.5:7b"))
client = OpenAICompatibleClient("my-model", base_url="http://localhost:8001/v1", api_key="")
```

## Costs

Token costs come from `agentcore.obs.PRICE_TABLE` (USD per million tokens) and are estimates. Local
models (`ollama:`, `vllm:`, `mock`) are counted as free. Pass your own table to `CostTracker` for
accurate accounting.

## Use AgentCore as a model

`agentcore serve` exposes the agent as an OpenAI-compatible model, so existing OpenAI clients can
talk to it (the agent runs the server's tools):

```python
from openai import OpenAI  # pip install openai

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="unused-unless-AGENTCORE_API_KEY-is-set")
for chunk in client.chat.completions.create(
    model="agentcore", messages=[{"role": "user", "content": "What is 17 * 23?"}], stream=True
):
    print(chunk.choices[0].delta.content or "", end="")
```

See [HTTP API](/agentcore/docs/reference/http-api/#post-v1chatcompletions).
