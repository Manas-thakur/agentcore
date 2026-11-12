"""Multi-agent collaboration: Planner -> (Researcher | Coder) -> Reviewer over the A2A bus.

python examples/multi_agent.py --model mock
python examples/multi_agent.py --model ollama:qwen2.5:7b "Explain HNSW and compute 16 * 2 + 1"
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from agentcore import create_model
from agentcore.agents import CoderAgent, ManagerWorker, PlannerAgent, ResearcherAgent, ReviewerAgent
from agentcore.obs import CostTracker, configure_tracing
from agentcore.rag import RAGPipeline

HERE = Path(__file__).parent


async def run(goal: str, model_spec: str) -> None:
    model = create_model(model_spec, verbose=True)
    costs = CostTracker()
    kb = RAGPipeline()
    kb.ingest(HERE / "data")

    team = ManagerWorker(
        planner=PlannerAgent(model, cost_tracker=costs),
        workers={
            "researcher": ResearcherAgent(model, knowledge_base=kb, cost_tracker=costs),
            "coder": CoderAgent(model, cost_tracker=costs),
            "reviewer": ReviewerAgent(model, cost_tracker=costs),
        },
    )
    result = await team.run(goal)

    print(f"Plan ({result.plan.method}):")
    for t in result.plan.tasks:
        deps = f" after {t.depends_on}" if t.depends_on else ""
        print(f"  {t.id} [{t.assignee}] {t.description}{deps}")
    print("\nA2A messages:")
    for m in result.messages:
        print(
            f"  {m['type']:<8} {m['sender']:>10} -> {m['recipient']:<10} corr={m['correlation_id']}"
        )
    print("\n" + result.output)
    print(f"cost: {costs.summary()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "goal",
        nargs="?",
        default="Research how HNSW search works and compute 2**10 * 3, then review the results",
    )
    parser.add_argument("--model", default="auto")
    args = parser.parse_args()
    configure_tracing(".agentcore/traces")
    asyncio.run(run(args.goal, args.model))


if __name__ == "__main__":
    main()
