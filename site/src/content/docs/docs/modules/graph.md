---
title: Workflow graphs
description: A state-graph engine with conditional edges, parallel fan-out and joins, reducers, retries, checkpoints, human-in-the-loop interrupts, saga compensation and subgraphs.
---

`agentcore.graph` runs workflows as state graphs. Nodes are plain functions (sync or async) or
agents that read the shared state and return a partial update; edges decide what runs next.

```python
from agentcore.graph import END, START, StateGraph, append, interrupt

g = StateGraph("review", reducers={"notes": append})
g.add_node("search_a", lambda s: {"notes": "A"})
g.add_node("search_b", lambda s: {"notes": "B"})
g.add_node("approve", lambda s: {"ok": interrupt({"question": "Ship it?"}) == "yes"})
g.add_node("ship", lambda s: {"shipped": True}, compensate=lambda s: print("rollback"))
g.add_edge(START, ["search_a", "search_b"])  # parallel fan-out
g.add_edge(["search_a", "search_b"], "approve")  # join
g.add_conditional_edges("approve", lambda s: "yes" if s["ok"] else "no", {"yes": "ship", "no": END})
app = g.compile()

r = app.run_sync({})  # pauses at the human approval
print(r.status, r.interrupt["payload"])
r = app.resume_sync(r.thread_id, "yes")
print(r.status, r.state)
print(g.to_mermaid())
```

```text
interrupted {'question': 'Ship it?'}
completed {'notes': ['A', 'B'], 'ok': True, 'shipped': True}
flowchart TD
    START([start])
    END([end])
    search_a["search_a"]
    search_b["search_b"]
    approve["approve"]
    ship["ship"]
    START --> search_a
    START --> search_b
    search_a & search_b --> approve
    approve -.->|"yes"| ship
    approve -.->|"no"| END
```

## Building graphs

- `StateGraph(name, reducers)`: reducers say how updates to a key combine. `replace` is the
  default; `append`, `add` and `merge` are built in, and any `(old, new) -> value` function works.
  Reducers make parallel branches safe: both `search_a` and `search_b` append to `notes`.
- `add_node(name, fn, *, retries=0, retry_delay=0.0, timeout=None, compensate=None, fallback=None)`:
  retry a flaky node, give it a timeout, route to a `fallback` node when it keeps failing, and
  register a `compensate` function for rollback.
- `add_edge(source, target)`: either side can be a list. A list target fans out (the branches run
  concurrently); a list source is a join that waits for every branch.
- `add_conditional_edges(source, router, path_map)`: `router(state)` returns a key (or a node
  name); loops are allowed and bounded by `compile(max_steps=100)`.

## Running, checkpoints and human-in-the-loop

`compile(checkpointer=None, *, max_steps=100)` returns a `CompiledGraph`. `await app.run(inputs)`
or `app.run_sync(inputs)` returns a `GraphResult` with `status` (`completed`, `interrupted`,
`failed`), `state`, `thread_id`, `history`, `interrupts`, `error`, `failed_node`, `compensated`
and `duration_ms`.

Calling `interrupt(payload)` inside a node pauses the run and checkpoints it. Resume with
`app.resume_sync(thread_id, value)`; `interrupt()` then returns `value`. Checkpoints live in memory
by default; `FileCheckpointer(".agentcore/checkpoints")` writes them to disk so a run can be
resumed by another process.

## Saga compensation

If a node fails after earlier nodes with `compensate=` functions completed, those compensations
run in reverse order and are listed in `result.compensated`. Try it with
`python examples/workflow_graph.py --fail` in the repository.

## Subgraphs and diagrams

`compiled.as_node(input_keys, output_keys)` turns a compiled graph into a node of another graph.
`g.to_mermaid()` exports the graph as a Mermaid flowchart. Graph runs are traced as
`graph.run:<name>` with a `graph.node:<node>` span per node.
