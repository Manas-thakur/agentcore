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
| `agent` | How to build the agent: `model`, `tools` (built-in or from `tool_modules`), `system_prompt`, `max_steps`, `temperature` |
| `cases[].input` | The task |
| `expected_output` + `match` | `contains` (default), `exact` or `regex` against the final answer |
| `expected_tool_calls` | Tool names, or `{tool, args, match: subset\|exact\|any, min_count, max_count}` |
| `expected_trajectory` | Ordered list of tool names the agent must call |
| `max_steps` | Step budget for the case (scored as `step_budget`) |
| `rubric` | Criteria and weights for the LLM judge (`--judge-model`) |
| `tags` | Filter with `--tags` |

Metrics are chosen per case from what it specifies: `exact_match` / `contains` / `regex`,
`tool_calls`, `trajectory`, `step_budget` and `llm_judge`. A case passes when every metric passes;
its score is the mean.

## Running from the CLI

```bash
agentcore eval --suite examples/evals/calculator_suite.yaml --model mock
agentcore eval --suite S --model ollama:qwen2.5:7b --judge-model ollama:qwen2.5:7b
agentcore eval --suite S --model mock --output report.json --markdown report.md --fail-under 0.9
```

The [CLI reference](/agentcore/docs/reference/cli/#agentcore-eval) lists every flag. The exit code is 1 on
a failing case, a pass rate under `--fail-under`, or a regression against `--baseline`.

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
replay_from, strict_replay, tools)` accepts your own agent factory and metrics, and
`run_suite(suite, on_result=fn)` reports progress per case.

## Baselines and regressions

`compare(baseline, current, threshold=0.05)` returns an `EvalDiff` with `new_failures`, `fixed`,
per-metric `regressions` and `improvements`, `new_cases` and `has_regressions`. On the CLI:

```bash
agentcore eval --suite S --model mock --baseline base.json --save-baseline   # write the baseline
agentcore eval --suite S --model mock --baseline base.json                   # compare; exit 1 on regressions
```

## In the web app

The Evals page discovers suites in `eval_dirs`, runs them in the background with live progress,
keeps every run, lets you mark a baseline, and shows a **results matrix** of cases x recent runs
with regressions outlined. See [Web app](/agentcore/docs/web-app/#evals). Each case's agent run is
also a trace (`kind:eval` in the trace explorer).
