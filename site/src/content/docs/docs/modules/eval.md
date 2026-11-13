---
title: Eval
description: YAML eval suites, trajectory and tool-call matching, LLM-as-judge, record/replay cassettes, baselines and regression gates.
---

`agentcore.eval` makes non-deterministic agents testable. A **suite** describes cases and what to
expect; the **runner** builds a fresh agent per case, records its trajectory and scores it; a
**cassette** records model responses so the same run replays deterministically; **compare**
diffs a run against a baseline.

## Suites

```yaml
# examples/evals/calculator_suite.yaml (excerpt)
name: calculator-basic
description: Arithmetic questions that must be answered with the calculator tool.
agent:
  system_prompt: >-
    You are a careful math assistant. Always use the calculator tool for arithmetic,
    then state the final numeric answer.
  tools: [calculator]
  max_steps: 5

cases:
  - name: multiply_add
    input: "What is 17 * 23 + 4?"
    expected_output: "395"            # match: contains (default) | exact | regex
    expected_tool_calls:
      - tool: calculator
        args: {expression: "17 * 23 + 4"}
    max_steps: 3
    tags: [arithmetic]

  - name: power
    input: "What is 2 ** 16?"
    expected_output: "65536"
    expected_trajectory: [calculator]  # ordered tool names
    tags: [arithmetic]

  - name: division_regex
    input: "What is 22 / 7 rounded result?"
    expected_output: "3\\.14\\d*"
    match: regex
    expected_tool_calls: [calculator]  # name only
    tags: [arithmetic, float]
```

| Field | Meaning |
|---|---|
| `name` | Suite name (default: the file name). Runs and history are grouped by it |
| `description` | Free text |
| `agent` | How to build the agent: `model`, `tools` (built-in or from `tool_modules`), `system_prompt`, `max_steps`, `temperature` |
| `cases[].name` | **Required**, unique within the suite |
| `cases[].input` | **Required**: the task |
| `expected_output` + `match` | `contains` (default), `exact` or `regex` (case-insensitive: `Contains` works) against the final answer. `contains` accepts `a \|\| b` for either |
| `expected_tool_calls` | Tool names, or `{tool, args, match: subset\|exact\|any, min_count, max_count}` |
| `expected_trajectory` | Ordered list of tool names the agent must call |
| `max_steps` | Step budget for the case (scored as `step_budget`) |
| `rubric` | Criteria and weights for the LLM judge (`--judge-model`), see below |
| `tags` | Filter with `--tags` |
| `metadata` | Free-form mapping kept with the case |

Metrics are chosen per case from what it specifies: `exact_match` / `contains` / `regex`,
`tool_calls`, `trajectory`, `step_budget` and `llm_judge`. A case passes when every metric passes;
its score is the mean. **A case that checks nothing fails** with a `no_checks` metric (score 0)
instead of passing silently; that includes a rubric-only case run without `--judge-model`.

### Suite files

Suites are validated when they are loaded (`load_suite`, `agentcore eval`, the web app). These
are errors, reported with the case and the allowed keys, for example
`cases[0] ('capital'): unknown key 'expectd_output' (did you mean 'expected_output'?); allowed keys: ...`:

- unknown keys at the top level (`name`, `description`, `agent`, `cases`), in `agent`, in a case
  or in an `expected_tool_calls` entry (`tool`/`name`, `args`/`arguments`, `match`, `min_count`,
  `max_count`);
- a case without `name` or `input`, or duplicate case names;
- a `match` other than `exact`, `contains`, `regex` (or `exact`, `subset`, `any` for tool calls),
  an invalid regular expression, a malformed rubric;
- invalid YAML or JSON.

In the web app a malformed suite is listed with its error instead of being runnable.

### Rubrics and the judge

A rubric is a mapping of criterion to weight, a list of `{criterion, weight}` entries (weight
defaults to 1) or a plain list of criteria:

```yaml
rubric: {correctness: 0.7, clarity: 0.3}
# or
rubric:
  - {criterion: correctness, weight: 2}
  - clarity
```

The judge scores each criterion from 0 to 10; the `llm_judge` score is the weighted mean / 10 and
passes at 0.7. `--judge-model` judges **only the cases that define a rubric**; add `--judge-all`
(Python: `EvalRunner(..., judge=model, judge_all=True)`) to also judge the other cases with the
default rubric (correctness 0.6, completeness 0.2, clarity 0.2). `--judge-model mock` answers
with valid JSON: 10 per criterion when the answer contains the reference (`expected_output`), 2
otherwise.

## Running from the CLI

```bash
agentcore eval --suite examples/evals/calculator_suite.yaml --model mock
agentcore eval --suite S --model ollama:qwen2.5:7b --judge-model ollama:qwen2.5:7b
agentcore eval --suite S --model mock --output report.json --markdown report.md --fail-under 0.9
```

The [CLI reference](/agentcore/docs/reference/cli/#agentcore-eval) lists every flag. Exit codes: 0 when
the pass rate is at least `--fail-under` (default `1.0`, so every case must pass) and there is no
regression against `--baseline`; 1 otherwise; 2 for usage errors such as an invalid suite or a
`--baseline` file that does not exist. `agentcore eval` writes a trace per case to the trace
directory (`--no-trace` to skip), like runs started from the web app.

## Running from Python, with a cassette

```python
from agentcore.eval import EvalRunner, compare, load_suite

suite = load_suite("examples/evals/calculator_suite.yaml")
report = EvalRunner("mock", record_to="cassette.json").run_suite_sync(suite)
print(report.to_markdown())

replayed = EvalRunner(replay_from="cassette.json").run_suite_sync(suite)  # no model needed
print(compare(report, replayed).has_regressions)  # False
```

```text
## Eval: calculator-basic (mock)

**5/5 passed** (100%) - mean score 1.00 - 607 tokens - 0.04s

| case | result | score | steps | metrics |
|---|---|---|---|---|
| multiply_add | PASS | 1.00 | 2 | contains=1.00, tool_calls=1.00, step_budget=1.00 |
| parentheses | PASS | 1.00 | 2 | contains=1.00, tool_calls=1.00 |
| power | PASS | 1.00 | 2 | contains=1.00, trajectory=1.00 |
| division_regex | PASS | 1.00 | 2 | regex=1.00, tool_calls=1.00 |
| modulo | PASS | 1.00 | 2 | contains=1.00, tool_calls=1.00 |

False
```

Record once against a real model (`--record cassette.json`), commit the cassette, and replay it in
CI (`--replay cassette.json`; add `--strict-replay` to also check that every request matches the
recorded one). `EvalRunner(model, *, agent_factory, metrics, judge, concurrency=4, record_to,
replay_from, strict_replay, tools, judge_all=False)` accepts your own agent factory and metrics
(`concurrency` must be >= 1), and `run_suite(suite, on_result=fn)` reports progress per case.

## Baselines and regressions

`compare(baseline, current, threshold=0.05)` returns an `EvalDiff` with `new_failures`, `fixed`,
per-metric `regressions` and `improvements`, `new_cases` and `has_regressions`. On the CLI:

```bash
agentcore eval --suite S --model mock --baseline base.json --save-baseline   # write the baseline
agentcore eval --suite S --model mock --baseline base.json                   # compare; exit 1 on regressions
```

Comparing against a `--baseline` that does not exist is an error (exit 2), so a typo in CI cannot
silently disable the regression gate.

## In the web app

The Evals page discovers suites in `eval_dirs`, runs them in the background with live progress,
keeps every run, lets you mark a baseline, and shows a **results matrix** of cases x recent runs
with regressions outlined. See [Web app](/agentcore/docs/web-app/#evals). Each case's agent run is
also a trace (`kind:eval` in the trace explorer). When two suite files use the same `name`, both
are listed (with `duplicate_name: true`) and must be run by path; running by the shared name
returns 409.
