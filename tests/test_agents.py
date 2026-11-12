from __future__ import annotations

import asyncio

from agentcore.agents import (
    A2AMessage,
    A2AMessageType,
    CoderAgent,
    ManagerWorker,
    MessageBus,
    Pipeline,
    PlannerAgent,
    ResearcherAgent,
    ReviewerAgent,
    SpecializedAgent,
    extract_json,
    peer_review,
)
from agentcore.rag import RAGPipeline
from agentcore.runtime import MockModel, ScriptedModel
from tests.conftest import EXAMPLES, run


def test_extract_json():
    assert extract_json('noise ```json\n{"a": 1}\n``` tail') == {"a": 1}
    assert extract_json('prefix {"b": [1, 2]} suffix') == {"b": [1, 2]}
    assert extract_json("no json") is None


def test_planner_parses_llm_json_and_falls_back():
    planner = PlannerAgent(
        ScriptedModel(
            [
                '{"tasks": [{"id": "a", "description": "find facts", "assignee": "researcher"},'
                ' {"id": "b", "description": "check", "assignee": "reviewer", "depends_on": ["a"]}]}'
            ]
        )
    )
    plan = run(planner.plan("goal"))
    assert plan.method == "llm" and [t.id for t in plan.tasks] == ["a", "b"]
    assert [[t.id for t in w] for w in plan.waves()] == [["a"], ["b"]]

    fallback = run(
        PlannerAgent(MockModel()).plan("Research HNSW and compute 2**10, then review the results")
    )
    assert fallback.method == "heuristic"
    assert [t.assignee for t in fallback.tasks] == ["researcher", "coder", "reviewer"]
    assert fallback.tasks[2].depends_on == ["t1", "t2"]


def test_reviewer_json_and_heuristic():
    reviewer = ReviewerAgent(
        ScriptedModel(
            [
                '{"approved": true, "score": 0.9, "issues": [{"severity": "low", "description": "typo"}], "summary": "good"}'
            ]
        )
    )
    review = run(reviewer.review("task", "some work output here"))
    assert review.approved and review.score == 0.9 and review.issues[0].description == "typo"
    heuristic = run(
        ReviewerAgent(MockModel()).review("task", "Traceback (most recent call last): boom")
    )
    assert not heuristic.approved and heuristic.method == "heuristic"
    ok = run(
        ReviewerAgent(MockModel()).review("task", "A complete and correct answer with detail.")
    )
    assert ok.approved


def test_researcher_with_knowledge_base():
    kb = RAGPipeline()
    kb.ingest(EXAMPLES / "data")
    out = run(ResearcherAgent(MockModel(), knowledge_base=kb).run("How does HNSW search work?"))
    assert out.success and "[1]" in out.output
    assert out.data["sources"] and "hnsw" in out.data["sources"][0]["location"].lower()
    report = ResearcherAgent.render_report("HNSW", out, "mock")
    assert report.startswith("# Research Report: HNSW") and "## Sources" in report


def test_coder_runs_code_in_sandbox():
    out = run(CoderAgent(MockModel()).run("compute 12 * 12"))
    assert out.success and out.data["verified"] and "144" in out.data["execution"]
    assert "```python" in out.output


def test_bus_request_broadcast_topics_and_errors():
    async def scenario():
        bus = MessageBus()
        received = []

        async def echo(msg: A2AMessage):
            received.append(("echo", msg.type))
            return {"echo": msg.payload["text"]}

        def listener(msg: A2AMessage):
            received.append(("listener", msg.type))

        def broken(msg: A2AMessage):
            raise ValueError("nope")

        bus.register("echo", echo, topics=["news"])
        bus.register("listener", listener, topics=["news"])
        bus.register("broken", broken)

        reply = await bus.request("me", "echo", {"text": "hi"})
        assert reply.type == A2AMessageType.RESPONSE and reply.payload == {"echo": "hi"}
        assert reply.sender == "echo" and reply.recipient == "me"

        err = await bus.request("me", "broken", {})
        assert err.type == A2AMessageType.ERROR and "nope" in err.payload["error"]
        missing = await bus.request("me", "ghost", {})
        assert missing.type == A2AMessageType.ERROR

        await bus.send(A2AMessage("me", "topic:news", A2AMessageType.EVENT, {"text": "x"}))
        await bus.send(A2AMessage("echo", "broadcast", A2AMessageType.STATUS_UPDATE, {"text": "y"}))
        await bus.drain()
        assert ("listener", A2AMessageType.EVENT) in received and (
            "echo",
            A2AMessageType.EVENT,
        ) in received
        assert ("listener", A2AMessageType.STATUS_UPDATE) in received
        assert ("echo", A2AMessageType.STATUS_UPDATE) not in received  # sender excluded
        assert len(bus.transcript()) >= 8

    run(scenario())


def test_manager_worker_end_to_end():
    kb = RAGPipeline()
    kb.ingest(EXAMPLES / "data")
    model = MockModel()
    team = ManagerWorker(
        PlannerAgent(model),
        {
            "researcher": ResearcherAgent(model, knowledge_base=kb),
            "coder": CoderAgent(model),
            "reviewer": ReviewerAgent(model),
        },
    )
    result = run(
        team.run("Explain reciprocal rank fusion and calculate 7 * 6, then review the results")
    )
    assert result.success and len(result.results) == 3
    assert "42" in result.results["t2"].output
    assert result.results["t3"].output.startswith("APPROVED")
    requests = [m for m in result.messages if m["type"] == "request"]
    assert {m["recipient"] for m in requests} == {"researcher", "coder", "reviewer"}
    assert "## t1." in result.output


def test_pipeline_and_peer_review():
    class Upper(SpecializedAgent):
        name = "upper"

        async def run(self, task, context=None):
            from agentcore.agents import AgentOutput

            prev = next(iter((context or {}).values()), task)
            return AgentOutput(self.name, task, str(prev).upper())

    class Exclaim(Upper):
        name = "exclaim"

        async def run(self, task, context=None):
            from agentcore.agents import AgentOutput

            return AgentOutput(self.name, task, next(iter(context.values())) + "!")

    result = run(Pipeline([Upper(MockModel()), Exclaim(MockModel())]).run("hello"))
    assert result.output == "HELLO!"

    worker = SpecializedAgent(
        ScriptedModel(["draft with Traceback error", "final clean answer that is long enough"])
    )
    reviewer = ReviewerAgent(MockModel())
    out, review, rounds = run(peer_review(worker, reviewer, "write something", max_rounds=3))
    assert rounds == 2 and review.approved and out.output.startswith("final")


def test_agents_run_concurrently_on_bus():
    async def scenario():
        bus = MessageBus()

        async def slow(msg):
            await asyncio.sleep(0.3)
            return {"ok": True}

        bus.register("a", slow)
        bus.register("b", slow)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.gather(bus.request("x", "a", {}), bus.request("x", "b", {}))
        return loop.time() - t0

    assert run(scenario()) < 0.55  # sequential would take >= 0.6 s
