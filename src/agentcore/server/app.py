"""HTTP API (FastAPI, optional ``server`` extra) + a self-contained trace dashboard.

Endpoints:

* ``GET  /``                 - trace dashboard (static HTML, no build step)
* ``GET  /health``           - liveness + configured model
* ``GET  /v1/models``        - OpenAI-style model list
* ``POST /v1/agent``         - run the agent: ``{"input": "..."}`` or ``{"messages": [...]}``
* ``GET  /api/traces``       - recent traces (summaries)
* ``GET  /api/traces/{id}``  - all spans of one trace
* ``GET  /metrics``          - Prometheus text format
"""
# NOTE: no "from __future__ import annotations" here - FastAPI must resolve the
# locally-defined request models at runtime.

import time
import uuid
from importlib import resources
from typing import Any

from agentcore import __version__
from agentcore.obs.metrics import get_metrics
from agentcore.obs.storage import JSONLTraceStore
from agentcore.obs.tracing import configure_tracing
from agentcore.runtime.agent import Agent
from agentcore.runtime.providers import create_model
from agentcore.tools.builtins import builtin_tools
from agentcore.types import Message

DEFAULT_SERVER_TOOLS = ["calculator", "current_time"]


def dashboard_html() -> str:
    return (
        resources.files("agentcore.server")
        .joinpath("static/dashboard.html")
        .read_text(encoding="utf-8")
    )


def create_app(
    model: str | None = None,
    tools: list[str] | None = None,
    trace_dir: str = ".agentcore/traces",
    workspace: str = "workspace",
) -> Any:
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse, PlainTextResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover - depends on installed extras
        raise RuntimeError(
            "the server needs the 'server' extra: pip install 'agentcore[server]'"
        ) from exc

    configure_tracing(trace_dir)
    store = JSONLTraceStore(trace_dir)
    default_model = create_model(model, verbose=True)
    allowed_tools = list(tools or DEFAULT_SERVER_TOOLS)
    tool_objs = {t.name: t for t in builtin_tools(allowed_tools, workspace=workspace)}

    class ChatMessage(BaseModel):
        role: str
        content: str = ""

    class AgentRequest(BaseModel):
        input: str | None = None
        messages: list[ChatMessage] | None = None
        model: str | None = None
        tools: list[str] | None = Field(
            default=None, description="subset of the server's enabled tools"
        )
        system_prompt: str | None = None
        max_steps: int = Field(default=8, ge=1, le=50)

    app = FastAPI(
        title="AgentCore",
        version=__version__,
        description="AgentCore agent API and trace dashboard",
    )
    app.state.model = default_model
    app.state.store = store

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return dashboard_html()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "model": default_model.model_id,
            "tools": allowed_tools,
        }

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": default_model.model_id, "object": "model", "owned_by": "agentcore"}],
        }

    @app.post("/v1/agent")
    async def run_agent(req: AgentRequest) -> dict[str, Any]:
        if not req.input and not req.messages:
            raise HTTPException(400, "provide 'input' or 'messages'")
        names = req.tools if req.tools is not None else allowed_tools
        unknown = [n for n in names if n not in tool_objs]
        if unknown:
            raise HTTPException(
                400, f"tools not enabled on this server: {unknown}; enabled: {allowed_tools}"
            )
        try:
            mdl = create_model(req.model) if req.model else default_model
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        agent = Agent(
            mdl,
            tools=[tool_objs[n] for n in names],
            system_prompt=req.system_prompt,
            max_steps=req.max_steps,
            name="api",
        )
        task: str | list[Message]
        if req.messages:
            task = [Message(role=m.role, content=m.content) for m in req.messages]  # type: ignore[arg-type]
        else:
            task = req.input or ""
        try:
            result = await agent.run(task)
        except Exception as exc:
            raise HTTPException(502, f"agent failed: {type(exc).__name__}: {exc}") from exc
        return {
            "id": f"run_{uuid.uuid4().hex[:16]}",
            "object": "agent.run",
            "created": int(time.time()),
            "model": mdl.model_id,
            "output": result.output,
            "stop_reason": result.stop_reason,
            "steps": result.steps,
            "usage": result.usage.to_dict(),
            "tool_calls": [
                {
                    "name": r.tool_name,
                    "arguments": r.arguments,
                    "success": r.success,
                    "output": r.as_text(1000),
                }
                for r in result.tool_results
            ],
            "trace_id": result.trace_id,
            "duration_ms": round(result.duration_ms, 2),
        }

    @app.get("/api/traces")
    def list_traces(limit: int = 50) -> list[dict[str, Any]]:
        return [s.to_dict() for s in store.list(limit)]

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str) -> dict[str, Any]:
        resolved = store.resolve(trace_id)
        if resolved is None:
            raise HTTPException(404, f"trace {trace_id!r} not found")
        return {"trace_id": resolved, "spans": [s.to_dict() for s in store.load(resolved)]}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return get_metrics().export_prometheus()

    return app
