"""Showcase app: the autonomous technical researcher.

Searches a local corpus (``--docs``) and/or the web (``--web``), writes a cited markdown
report, and saves the full execution trace and a cost breakdown next to it::

    agentcore research "How does HNSW work?" --docs examples/data --out report.md
    # -> report.md, report.trace.json, report.cost.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agentcore.agents.specialists import ResearcherAgent
from agentcore.obs.cost import CostTracker
from agentcore.obs.tracing import InMemoryExporter, get_tracer
from agentcore.runtime.model_client import ModelClient
from agentcore.runtime.providers import create_model


@dataclass
class ResearchArtifacts:
    report_path: Path
    trace_path: Path
    cost_path: Path
    sources: int
    success: bool


async def research(
    topic: str,
    *,
    model: ModelClient | str | None = None,
    docs: str | Path | None = None,
    web: bool = False,
    out: str | Path = "report.md",
    max_steps: int = 8,
) -> ResearchArtifacts:
    if docs is None and not web:
        raise ValueError("give a local corpus with docs=... and/or enable web=True")
    knowledge_base = None
    if docs is not None:
        from agentcore.rag.generation import RAGPipeline

        knowledge_base = RAGPipeline()
        if knowledge_base.ingest(docs) == 0:
            raise ValueError(f"no supported documents found in {docs}")

    mdl = create_model(model)
    costs = CostTracker()
    capture = InMemoryExporter()
    tracer = get_tracer()
    tracer.add_exporter(capture)
    try:
        agent = ResearcherAgent(
            mdl, knowledge_base=knowledge_base, web=web, max_steps=max_steps, cost_tracker=costs
        )
        output = await agent.run(topic)
    finally:
        tracer.exporters.remove(capture)

    report = ResearcherAgent.render_report(topic, output, mdl.model_id)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    trace_path = out.with_suffix(".trace.json")
    trace_path.write_text(
        json.dumps(
            {
                "topic": topic,
                "model": mdl.model_id,
                "success": output.success,
                "error": output.error,
                "result": output.result.to_dict() if output.result else None,
                "spans": [s.to_dict() for s in capture.spans],
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    cost_path = out.with_suffix(".cost.json")
    cost_path.write_text(
        json.dumps({**costs.summary(), "entries": [e.to_dict() for e in costs.entries]}, indent=2),
        encoding="utf-8",
    )
    return ResearchArtifacts(
        out, trace_path, cost_path, len(output.data.get("sources", [])), output.success
    )
