---
title: Troubleshooting and FAQ
description: Common problems with models, the web app, auth and evals, and answers to frequent questions.
---

Start with `agentcore doctor` (add `--model <spec> --ping` to test a model). It checks the Python
version, extras, the config file, the trace directory, tool modules, eval directories, and Ollama /
OpenAI-compatible reachability, and says what to fix.

## Models

**The agent answers "[mock] I can't answer ... because I'm the offline mock model".**
You are on the offline `mock` model, which is rule-based: it handles arithmetic, simple tool calls
and extractive RAG answers. Use a real model: `--model ollama:qwen2.5:7b` or
`--model openai:<name>` ([Models](/agentcore/docs/models/)). The web app shows a notice while the mock
model is in use.

**`auto` keeps using the mock model.**
`auto` uses Ollama only when it is reachable at `OLLAMA_HOST` and `AGENTCORE_OLLAMA_MODEL`
(default `qwen2.5:7b`) is pulled. Run `ollama pull qwen2.5:7b` or set the variable to a model you
have; `agentcore doctor` shows which one it found.

**The model never calls tools.**
Use a model with native tool calling (for example `qwen2.5`, `llama3.1` and newer on Ollama). Check
that the tools are enabled: `agentcore tools`, the Run settings panel, or `GET /api/tools`.

**`ModelError: ... connection refused`.**
The server in `OLLAMA_HOST` or `OPENAI_BASE_URL` is not running or not reachable from where
AgentCore runs (inside Docker, `localhost` is the container; use the service name, as
`docker-compose.yml` does with `http://ollama:11434`).

## Web app

**`agentcore serve` says the server extra is missing.**
Install it: `pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"`.

**The page says the web app is not built.**
You are running from a source checkout whose `src/agentcore/server/static/` is empty. Run
`pnpm --dir web install && pnpm --dir web build` (Node 20+, pnpm 10), or install a release.

**Streaming replies arrive all at once behind a proxy.**
Turn off response buffering for the app (`proxy_buffering off;` in nginx). See
[Deployment](/agentcore/docs/deployment/#reverse-proxy).

**The browser keeps asking for an API key.**
The key you entered does not match `AGENTCORE_API_KEY`. Fix it in Settings, or with "Forget key".

**Charts and the trace list are empty.**
They read the trace directory the server was started with (`trace_dir`, shown in Settings). Runs
made from another directory write traces elsewhere; point both at the same `trace_dir` or
`AGENTCORE_TRACE_DIR`.

## Evals

**My suite does not appear in the web app.**
Suites are discovered in `eval_dirs` (default `evals/` and `examples/evals/`, relative to where the
server runs). Files that fail to load are listed as "invalid" with the error in their tooltip; files
without cases (reports, cassettes) are skipped. Use **Rescan** after adding files.

**A custom tool in my suite is unknown.**
List the module that defines it in `tool_modules` in `agentcore.toml`.

**Replay fails after I changed the suite.**
A cassette stores the model responses of a recording run. When prompts or tools change, record it
again with `--record`.

## FAQ

**Does it need a GPU or an API key?**
No. Everything, including the tests and CI, runs on the offline mock model. A GPU only matters for
the local model you choose to run with Ollama or vLLM.

**Is it a framework I build on, or code to read?**
Both. Every module is a normal Python package with tests, and the code is written to be read: the
loop, the schema generation, the indexes and the graph engine are each a few hundred lines.

**Can several people use one server?**
It is designed as a single-user, local-first tool: one API key, file-based state, no accounts. Run
one instance per user or team behind your own access control.

**Does the web app send data anywhere?**
No. It talks only to the server that served it, and loads no scripts, fonts or analytics from other
hosts.

**Which Python versions are supported?**
3.10, 3.11 and 3.12 are tested in CI.
