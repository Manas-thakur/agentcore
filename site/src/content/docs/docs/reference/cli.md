---
title: CLI reference
description: Every agentcore command and flag, taken from the CLI's own --help output.
---

```text
agentcore [-h] [--version] [--debug] [--config CONFIG] {run,chat,eval,traces,serve,research,tools,init,doctor} ...
```

| Global option | Meaning |
|---|---|
| `--version` | Print the version and exit |
| `--debug` | Show full Python tracebacks instead of one-line errors (also accepted after the subcommand; or set `AGENTCORE_DEBUG=1`) |
| `--config CONFIG` | Path to `agentcore.toml` (default: `./agentcore.toml` if present). Goes **before** the subcommand. |

### Errors and exit codes

Ordinary mistakes print one line, `error: <what went wrong>`, and exit with code **2**: an unknown
or incomplete model spec (`bogus:x`, `openai:`), a model server that is down or returns an error,
a missing suite, cassette or `--docs` path, invalid YAML/JSON, a malformed eval suite, an
unknown tool or missing tool module in `agentcore.toml`, and invalid flag values. Add `--debug`
to see the traceback. `agentcore run` is the exception: errors in your script keep their
traceback. Exit code **1** means the command ran but the result is a failure (failed eval cases
below `--fail-under`, an eval regression, failed `doctor` checks).

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
agentcore chat [-h] [--debug] [--model MODEL] [--tools TOOLS] [--system SYSTEM] [-p PROMPT] [--stream]
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
| `-v`, `--verbose` | Print every step (tool calls and the final `[stop_reason, steps, tokens]` line go to stderr) |

With `-p`, a failed model call (server down, HTTP error) prints `error: ...` and exits 2.

## `agentcore eval`

Run an eval suite (YAML or JSON). The suite is validated first (see
[Eval suites](/agentcore/docs/modules/eval/#suite-files)).

```text
agentcore eval [-h] [--debug] --suite SUITE [--model MODEL] [--judge-model JUDGE_MODEL]
               [--judge-all] [--output OUTPUT] [--markdown MARKDOWN] [--baseline BASELINE]
               [--save-baseline] [--threshold THRESHOLD] [--record RECORD] [--replay REPLAY]
               [--strict-replay] [--tags TAGS] [--concurrency CONCURRENCY]
               [--fail-under FAIL_UNDER] [--trace-dir TRACE_DIR] [--no-trace]
```

| Option | Meaning |
|---|---|
| `--suite SUITE` | Suite file (required) |
| `--model MODEL` | Model spec; overrides the suite's model |
| `--judge-model JUDGE_MODEL` | LLM-as-judge model. Judges only the cases that define a `rubric` |
| `--judge-all` | With `--judge-model`, also judge cases without a rubric (default rubric: correctness 0.6, completeness 0.2, clarity 0.2) |
| `--output OUTPUT` | Write the JSON report here |
| `--markdown MARKDOWN` | Write a markdown report here (the path is printed) |
| `--baseline BASELINE` | Compare against this JSON report. The file **must exist**: a missing baseline is an error (exit 2), not a skipped check |
| `--save-baseline` | Write this run as the baseline (to `--baseline`, default `eval-baseline.json`) instead of comparing |
| `--threshold THRESHOLD` | Score drop that counts as a regression (default 0.05) |
| `--record RECORD` | Record model responses to a cassette file |
| `--replay REPLAY` | Replay model responses from a cassette (offline, deterministic) |
| `--strict-replay` | Also check that each request matches the recorded one (fingerprint) |
| `--tags TAGS` | Only run cases with these comma-separated tags (no matching case is an error) |
| `--concurrency CONCURRENCY` | Cases run in parallel, an integer >= 1 (default 4) |
| `--fail-under FAIL_UNDER` | Minimum pass rate, 0 to 1 (default `1.0`: every case must pass) |
| `--trace-dir TRACE_DIR` | Where eval traces are written (default: config). They show up in the web app as `kind:eval` |
| `--no-trace` | Do not write traces |

Exit codes: **0** when the pass rate (passed cases / cases) is at least `--fail-under` and the
baseline comparison (if any) finds no regression; **1** when the pass rate is below
`--fail-under` or a regression is found; **2** for usage errors (missing suite or baseline,
invalid suite, bad flag values). With the default `--fail-under 1.0` a single failing case exits
1; `--fail-under 0.9` tolerates up to 10% failing cases.

```bash
agentcore eval --suite evals/basic.yaml --baseline eval-baseline.json --save-baseline  # once
agentcore eval --suite evals/basic.yaml --baseline eval-baseline.json                  # in CI
```

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
| `list --limit LIMIT` | Number of traces, an integer >= 1 (default 20) |
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
| `--port PORT` | Default: config or `8000`. `/api/config` reports the host and port actually served |
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
| `--docs DOCS` | Local corpus (file or directory; must exist). Markdown, MDX, HTML, text and JSONL files are read |
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
