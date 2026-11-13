---
title: CLI reference
description: Every agentcore command and flag, taken from the CLI's own --help output.
---

```text
agentcore [-h] [--version] [--config CONFIG] {run,chat,eval,traces,serve,research,tools,init,doctor} ...
```

| Global option | Meaning |
|---|---|
| `--version` | Print the version and exit |
| `--config CONFIG` | Path to `agentcore.toml` (default: `./agentcore.toml` if present). Goes **before** the subcommand. |

Wherever a command takes `--model`, the value is `mock | auto | ollama:<model> | openai:<model>`
(default: `$AGENTCORE_MODEL` or `auto`). See [Models](/agentcore/docs/models/).

## `agentcore init`

Scaffold a new agent project that runs offline with `--model mock`.

```text
agentcore init [-h] [--name NAME] [--force] [directory]
```

| Argument | Meaning |
|---|---|
| `directory` | Target directory (default: current directory) |
| `--name NAME` | Project name (default: directory name) |
| `--force` | Overwrite existing files |

## `agentcore doctor`

Check the environment, config and model reachability. Exits 1 when a check fails.

```text
agentcore doctor [-h] [--model MODEL] [--ping] [--timeout TIMEOUT]
```

| Option | Meaning |
|---|---|
| `--model MODEL` | Model to check |
| `--ping` | Also send one tiny request to the model |
| `--timeout TIMEOUT` | Seconds per network check (default 3.0) |

## `agentcore run`

Run a Python script (for example an example) with the given arguments.

```text
agentcore run [-h] script ...
```

## `agentcore chat`

Chat with a tool-using agent: interactive, or one-shot with `-p`.

```text
agentcore chat [-h] [--model MODEL] [--tools TOOLS] [--system SYSTEM] [-p PROMPT] [--stream]
               [--max-steps MAX_STEPS] [--memory-turns MEMORY_TURNS] [--workspace WORKSPACE]
               [--trace-dir TRACE_DIR] [-v]
```

| Option | Meaning |
|---|---|
| `--model MODEL` | Model spec |
| `--tools TOOLS` | Comma-separated tools (`''` for none; default: config or `calculator,current_time`) |
| `--system SYSTEM` | System prompt |
| `-p`, `--prompt PROMPT` | Ask one question and exit |
| `--stream` | Stream tokens |
| `--max-steps MAX_STEPS` | Upper bound on model calls per turn (default 8) |
| `--memory-turns MEMORY_TURNS` | Turns kept in the sliding-window memory (default 6) |
| `--workspace WORKSPACE` | Directory for the file tools |
| `--trace-dir TRACE_DIR` | Where traces are written |
| `-v`, `--verbose` | Print every step |

## `agentcore eval`

Run an eval suite (YAML or JSON). Exits 1 on failures, regressions or a pass rate under
`--fail-under`.

```text
agentcore eval [-h] --suite SUITE [--model MODEL] [--judge-model JUDGE_MODEL] [--output OUTPUT]
               [--markdown MARKDOWN] [--baseline BASELINE] [--save-baseline]
               [--threshold THRESHOLD] [--record RECORD] [--replay REPLAY] [--strict-replay]
               [--tags TAGS] [--concurrency CONCURRENCY] [--fail-under FAIL_UNDER]
```

| Option | Meaning |
|---|---|
| `--suite SUITE` | Suite file (required) |
| `--model MODEL` | Model spec; overrides the suite's model |
| `--judge-model JUDGE_MODEL` | Enable LLM-as-judge with this model |
| `--output OUTPUT` | Write the JSON report here |
| `--markdown MARKDOWN` | Write a markdown report here |
| `--baseline BASELINE` | Compare against (or with `--save-baseline`, write) this JSON |
| `--save-baseline` | Write the baseline instead of comparing |
| `--threshold THRESHOLD` | Score drop that counts as a regression (default 0.05) |
| `--record RECORD` | Record model responses to a cassette file |
| `--replay REPLAY` | Replay model responses from a cassette (offline, deterministic) |
| `--strict-replay` | Also check that each request matches the recorded one (fingerprint) |
| `--tags TAGS` | Only run cases with these comma-separated tags |
| `--concurrency CONCURRENCY` | Cases run in parallel (default 4) |
| `--fail-under FAIL_UNDER` | Exit 1 if the pass rate is below this |

## `agentcore traces`

Inspect locally stored traces.

```text
agentcore traces [-h] [--dir DIR] {list,show} ...
agentcore traces list [-h] [--limit LIMIT]
agentcore traces show [-h] [--json] trace_id
```

| Option | Meaning |
|---|---|
| `--dir DIR` | Trace directory (default: config or env). Goes before `list` / `show`. |
| `list --limit LIMIT` | Number of traces (default 20) |
| `show trace_id` | Trace id or unique prefix; prints the span tree |
| `show --json` | Print the spans as JSON |

## `agentcore serve`

Start the web app + HTTP API (needs the `server` extra).

```text
agentcore serve [-h] [--host HOST] [--port PORT] [--model MODEL] [--tools TOOLS]
                [--trace-dir TRACE_DIR] [--cors-origins CORS_ORIGINS] [--log-level LOG_LEVEL]
```

| Option | Meaning |
|---|---|
| `--host HOST` | Default: config or `127.0.0.1` |
| `--port PORT` | Default: config or `8000` |
| `--model MODEL` | Default model for chat, the API and evals |
| `--tools TOOLS` | Comma-separated tools to enable (default: config or `calculator,current_time`) |
| `--trace-dir TRACE_DIR` | Trace directory |
| `--cors-origins CORS_ORIGINS` | Comma-separated allowed CORS origins (default: none) |
| `--log-level LOG_LEVEL` | uvicorn log level (default `info`) |

## `agentcore research`

Research a topic and write a cited report (`report.md`, `report.trace.json`, `report.cost.json`).

```text
agentcore research [-h] [--docs DOCS] [--web] [--model MODEL] [--out OUT] [--max-steps MAX_STEPS]
                   [--trace-dir TRACE_DIR] topic
```

| Option | Meaning |
|---|---|
| `topic` | What to research |
| `--docs DOCS` | Local corpus (file or directory) |
| `--web` | Also search the web (DuckDuckGo) |
| `--out OUT` | Report path (default `report.md`) |
| `--max-steps MAX_STEPS` | Default 8 |
| `--trace-dir TRACE_DIR` | Trace directory |

## `agentcore tools`

List built-in and configured custom tools.

```text
agentcore tools [-h] [--schema] [--workspace WORKSPACE]
```

| Option | Meaning |
|---|---|
| `--schema` | Print the JSON Schemas |
| `--workspace WORKSPACE` | Root for the file tools (default `workspace`) |
