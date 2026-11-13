---
title: Multi-agent
description: Specialist agents (researcher, coder, reviewer, planner), an in-process A2A message bus, and manager-worker, pipeline and peer-review patterns.
---

`agentcore.agents` coordinates several agents. Each **specialist** wraps an `Agent` with a role and
the tools it needs; a **message bus** routes structured messages between them; **patterns** wire
them into teams.

```python
import asyncio

from agentcore import create_model
from agentcore.agents import CoderAgent, ManagerWorker, PlannerAgent, ResearcherAgent, ReviewerAgent
from agentcore.rag import RAGPipeline

model = create_model("mock")
kb = RAGPipeline()
kb.ingest("examples/data")
team = ManagerWorker(
    PlannerAgent(model),
    {
        "researcher": ResearcherAgent(model, knowledge_base=kb),
        "coder": CoderAgent(model),
        "reviewer": ReviewerAgent(model),
    },
)
result = asyncio.run(team.run("Research HNSW and compute 2**10, then review the results"))
print(result.output)
```

With the mock model the output ends like this (the planner, coder and reviewer each contribute a
section):

```text
## t2. compute 2**10 - coder

    print(2**10)

Output:
1024

The answer is 1024.

## t3. review the results - reviewer

APPROVED (score 1.00) - heuristic review (model did not return valid JSON)
```

The last line shows a deliberate fallback: when a model does not return the reviewer's JSON
verdict, the reviewer falls back to a heuristic review instead of failing the team.

## Specialists

| Agent | Role |
|---|---|
| `PlannerAgent` | Breaks a goal into a few tasks, each assigned to an available agent, with dependencies |
| `ResearcherAgent` | Searches a knowledge base (a `RAGPipeline`) and/or the web, writes a cited summary |
| `CoderAgent` | Writes Python, runs it in the sandbox to verify it, reports the code and the result |
| `ReviewerAgent` | Critiques another agent's output and returns a structured `ReviewResult` |

Subclass `SpecializedAgent` for your own roles.

## The A2A message bus

`MessageBus` routes `A2AMessage`s by recipient: an agent name (direct), `"broadcast"` (everyone
except the sender) or `"topic:<name>"` (subscribers, see `subscribe()`). `await bus.request(...)`
sends a request and waits for the correlated response; `bus.transcript()` returns every message for
debugging. Deliveries are traced as `a2a.deliver` spans.

## Patterns

- `ManagerWorker(planner, workers, bus=None)`: the planner decomposes the goal, workers run the
  tasks (in parallel where they do not depend on each other), dependency outputs are passed in as
  context, and the results are combined.
- `Pipeline(agents, bus=None)`: A then B then C; each agent receives the original task plus the
  previous agent's output.
- `peer_review(worker, reviewer, task, max_rounds=2)`: the worker produces, the reviewer
  critiques, and on rejection the worker revises with the feedback.

In the trace explorer a team run is one trace; the nested specialist runs appear as subagents in
the span tree and in the span preview.
