"""A state-graph workflow: parallel fan-out, join, conditional loop, human approval and saga.

python examples/workflow_graph.py               # auto-approves the human step
python examples/workflow_graph.py --interactive # asks you on the terminal
python examples/workflow_graph.py --fail        # make 'publish' fail -> compensation
"""

from __future__ import annotations

import argparse
import asyncio

from agentcore.graph import END, START, StateGraph, append, interrupt


def build(fail_publish: bool) -> StateGraph:
    g = StateGraph("content-pipeline", reducers={"sources": append, "log": append})

    def plan(state):
        return {
            "topic": state["topic"].strip(),
            "log": "plan",
            "revision": state.get("revision", 0),
        }

    async def search_papers(state):
        await asyncio.sleep(0.05)  # pretend I/O; runs concurrently with search_web
        return {"sources": [f"paper about {state['topic']}"], "log": "search_papers"}

    async def search_web(state):
        await asyncio.sleep(0.05)
        return {"sources": [f"blog post about {state['topic']}"], "log": "search_web"}

    def draft(state):
        text = f"Draft #{state['revision'] + 1} on {state['topic']} using {len(state['sources'])} sources."
        return {"draft": text, "revision": state["revision"] + 1, "log": "draft"}

    def review(state):
        # quality improves with each revision; two revisions are needed to pass
        return {"quality": 0.5 + 0.25 * state["revision"], "log": "review"}

    def approve(state):
        decision = interrupt({"question": "Publish this draft?", "draft": state["draft"]})
        return {"approved": bool(decision), "log": f"approve={decision}"}

    def reserve_slot(state):
        return {"slot": "2026-01-01T09:00", "log": "reserve_slot"}

    def release_slot(state):
        print(f"  [compensate] releasing publishing slot {state.get('slot')}")
        return {"slot": None}

    def publish(state):
        if fail_publish:
            raise RuntimeError("CMS is down")
        return {"published": True, "log": "publish"}

    g.add_node("plan", plan)
    g.add_node("search_papers", search_papers)
    g.add_node("search_web", search_web)
    g.add_node("draft", draft)
    g.add_node("review", review)
    g.add_node("approve", approve)
    g.add_node("reserve_slot", reserve_slot, compensate=release_slot)
    g.add_node("publish", publish, retries=1)

    g.add_edge(START, "plan")
    g.add_edge("plan", ["search_papers", "search_web"])  # fan-out (parallel)
    g.add_edge(["search_papers", "search_web"], "draft")  # join (waits for both)
    g.add_edge("draft", "review")
    g.add_conditional_edges(
        "review",
        lambda s: "good" if s["quality"] >= 1.0 else "revise",
        {"good": "approve", "revise": "draft"},
    )
    g.add_conditional_edges(
        "approve", lambda s: "yes" if s["approved"] else "no", {"yes": "reserve_slot", "no": END}
    )
    g.add_edge("reserve_slot", "publish")
    g.add_edge("publish", END)
    return g


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--topic", default="vector databases")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--fail", action="store_true", help="simulate a failure in 'publish'")
    parser.add_argument("--model", default=None, help="unused; accepted for CLI symmetry")
    args = parser.parse_args()

    graph = build(args.fail)
    app = graph.compile()
    print("Mermaid diagram:\n")
    print(graph.to_mermaid())
    print()

    result = app.run_sync({"topic": args.topic})
    while result.status == "interrupted":
        payload = result.interrupt["payload"]
        print(f"[interrupt] {payload['question']}\n  {payload['draft']}")
        if args.interactive:
            answer = input("  approve? [y/N] ").strip().lower() in ("y", "yes")
        else:
            answer = True
            print("  (auto-approving; use --interactive to answer yourself)")
        result = app.resume_sync(result.thread_id, answer)

    print(f"\nstatus: {result.status} after {result.steps} super-steps")
    print(f"execution order: {' -> '.join(result.history)}")
    if result.status == "failed":
        print(f"error: {result.error}")
        print(f"compensated: {result.compensated}")
    else:
        print(
            f"final state: published={result.state.get('published')} draft={result.state['draft']!r}"
        )


if __name__ == "__main__":
    main()
