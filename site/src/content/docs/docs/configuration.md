---
title: Configuration
description: agentcore.toml, environment variables and CLI flags, with their precedence and defaults.
---

Settings come from, highest priority first: **CLI flags**, **environment variables**,
**`agentcore.toml`**, then built-in defaults. `agentcore.toml` is read from the current directory
when present, or from `--config PATH` (given before the subcommand:
`agentcore --config ops/agentcore.toml serve`). Relative paths in the file resolve against the
file's directory.

## `agentcore.toml`

```toml
model = "mock"                                   # default model spec
models = ["ollama:qwen2.5:7b"]                   # extra entries for the web UI model picker
tools = ["calculator", "current_time", "lookup_fact"]
tool_modules = ["agent.py"]                      # .py files or modules defining @tool functions
trace_dir = ".agentcore/traces"
eval_dirs = ["evals"]
# data_dir = ".agentcore"                        # sessions + eval history (default: trace_dir/..)
# workspace = "workspace"                        # root for the file tools
# system_prompt = "You are ..."

[server]
host = "127.0.0.1"
port = 8000
cors_origins = []                                # e.g. ["http://localhost:5173"]
max_body_kb = 1024
```

Secrets never go in the file: an `api_key` key under `[server]` is rejected with an error. Use the
`AGENTCORE_API_KEY` environment variable instead.

The file is validated: unknown top-level keys and unknown `[server]` keys are errors (with a
suggestion, e.g. `unknown [server] keys: 'prot' (did you mean 'port'?)`), `port` must be an
integer from 1 to 65535 and `max_body_kb` a positive integer. Every command reports these as
`error: ...` and exits 2 (`agentcore doctor` lists them as a failed check).

## Reference

| Setting | `agentcore.toml` | Environment | CLI | Default |
|---|---|---|---|---|
| Default model | `model` | `AGENTCORE_MODEL` | `--model` | `auto` |
| Model picker entries | `models` | - | - | none |
| Enabled tools | `tools` | `AGENTCORE_TOOLS` (comma-separated) | `--tools` | `calculator,current_time` (+ custom tools) |
| Custom tool modules | `tool_modules` | - | - | none |
| Trace directory | `trace_dir` | `AGENTCORE_TRACE_DIR` | `--trace-dir` | `.agentcore/traces` |
| State directory (sessions, eval history) | `data_dir` | `AGENTCORE_DATA_DIR` | - | parent of the trace directory |
| Eval suite directories | `eval_dirs` | `AGENTCORE_EVAL_DIRS` | - | `evals`, `examples/evals` |
| File-tool workspace | `workspace` | - | `--workspace` (chat, tools) | `workspace` |
| Default system prompt | `system_prompt` | - | `--system` (chat) | built-in prompt |
| Server host / port | `[server] host`, `port` | - | `--host`, `--port` | `127.0.0.1`, `8000` |
| API key | never in the file | `AGENTCORE_API_KEY` | - | none (open) |
| CORS origins | `[server] cors_origins` | `AGENTCORE_CORS_ORIGINS` | `--cors-origins` | none |
| Max request body | `[server] max_body_kb` | `AGENTCORE_MAX_BODY_KB` | - | 1024 KB |
| Ollama model used by `auto` | - | `AGENTCORE_OLLAMA_MODEL` | - | `qwen2.5:7b` |
| Ollama URL | - | `OLLAMA_HOST` | - | `http://localhost:11434` |
| OpenAI-compatible key / URL | - | `OPENAI_API_KEY`, `OPENAI_BASE_URL` | - | -, `https://api.openai.com/v1` |
| Embedder for `create_embedder()` | - | `AGENTCORE_EMBEDDER` | - | `hash` |

`GET /api/config` (and the web app's Settings page) shows the effective configuration of a running
server, without secrets.

## `.env` files

AgentCore reads the process environment and does not load `.env` files itself. Load one with your
shell (`set -a; . ./.env; set +a`), `direnv`, docker compose `env_file`, or your process manager.
`agentcore init` writes a commented `.env.example`.
