"""HTTP API (FastAPI, optional ``server`` extra) and the AgentCore web app.

Endpoints (see the README "HTTP API" section for request/response shapes):

* ``GET  /``                              - web app (React build in ``static/``; SPA routes such
                                            as ``/traces/<id>`` fall back to ``index.html``)
* ``GET  /health``                        - liveness, version, model, auth mode
* ``GET  /v1/models``                     - OpenAI-style model list
* ``POST /v1/agent``                      - run the agent once (optionally in a session)
* ``POST /v1/chat/completions``           - OpenAI-compatible chat completions (+ ``stream``)
* ``POST /api/chat``                      - streaming chat turn (Server-Sent Events)
* ``GET|POST /api/sessions``, ``GET|DELETE /api/sessions/{id}``, ``POST .../stop``
* ``GET  /api/traces``, ``/api/traces/facets``, ``/api/traces/{id}``, ``/api/traces/{id}/export``
* ``GET  /api/traces/explore``           - query language, facet counts, histogram (explorer)
* ``GET  /api/overview``                  - KPIs, time series, top tools
* ``GET  /api/tools``, ``POST /api/tools/{name}/invoke``
* ``GET  /api/evals/suites``, ``GET|POST /api/evals/runs``, ``GET /api/evals/runs/{id}``,
  ``POST /api/evals/runs/{id}/baseline``, ``GET /api/evals/matrix`` (cases x recent runs)
* ``GET  /api/config``                    - effective server configuration (no secrets)
* ``GET  /metrics``                       - Prometheus text format
"""
# NOTE: no "from __future__ import annotations" here - FastAPI must resolve the
# locally-defined request models at runtime.

import asyncio
import json
import mimetypes
import platform
import time
import uuid
from pathlib import Path
from typing import Any

from agentcore import __version__
from agentcore.config import (
    DEFAULT_SERVER_TOOLS,
    Config,
    apply_env,
    load_tool_modules,
    resolve_tools,
)
from agentcore.obs.cost import estimate_cost
from agentcore.obs.metrics import get_metrics
from agentcore.obs.storage import JSONLTraceStore
from agentcore.obs.tracing import configure_tracing, current_span, current_trace_id, get_tracer
from agentcore.runtime.agent import Agent, AgentEvent
from agentcore.runtime.model_client import ModelClient
from agentcore.runtime.providers import MockModel, create_model
from agentcore.tools.execution import ExecutionEngine
from agentcore.tools.registry import ToolRegistry
from agentcore.types import Message, ToolCall

STATIC_DIR = Path(__file__).resolve().parent / "static"
OAI_DEFAULT_NAMES = {"", "agentcore", "default"}

# Windows can map .js to text/plain via the registry, which breaks ES modules; fonts may be missing.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")


def dashboard_html() -> str:
    """The web app's HTML shell (``static/index.html`` built from ``web/`` by Vite)."""
    index = STATIC_DIR / "index.html"
    if not index.exists():  # pragma: no cover - only in a source checkout without a build
        return (
            "<!doctype html><title>AgentCore</title><h1>AgentCore</h1><p>The web app is not "
            "built. Run <code>pnpm --dir web install &amp;&amp; pnpm --dir web build</code>, or use "
            "the API at <a href='/docs'>/docs</a>.</p>"
        )
    return index.read_text(encoding="utf-8").replace("{{version}}", __version__)


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _oai_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for p in content:
        if isinstance(p, dict) and p.get("type") in ("text", "input_text"):
            parts.append(str(p.get("text", "")))
    return "\n".join(parts)


def _oai_messages(messages: list[Any]) -> list[Message]:
    out = []
    for m in messages:
        role = m.role if m.role in ("system", "user", "assistant", "tool") else "user"
        if m.role == "developer":
            role = "system"
        calls = []
        for tc in m.tool_calls or []:
            fn = tc.get("function", {})
            calls.append(
                ToolCall.from_dict(
                    {
                        "id": tc.get("id"),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments"),
                    }
                )
            )
        out.append(
            Message(
                role=role,  # type: ignore[arg-type]
                content=_oai_content(m.content),
                tool_calls=calls,
                tool_call_id=m.tool_call_id,
                name=m.name if role == "tool" else None,
            )
        )
    return out


def create_app(
    model: str | None = None,
    tools: list[str] | None = None,
    trace_dir: str | None = None,
    workspace: str | None = None,
    *,
    config: Config | None = None,
    api_key: str | None = None,
    cors_origins: list[str] | None = None,
    max_body_bytes: int | None = None,
    eval_dirs: list[str] | None = None,
    state_dir: str | None = None,
    extra_tools: dict[str, Any] | None = None,
    mock_stream_delay: float = 0.0,
) -> Any:
    try:
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import (
            HTMLResponse,
            JSONResponse,
            PlainTextResponse,
            Response,
            StreamingResponse,
        )
        from fastapi.staticfiles import StaticFiles

        from agentcore.server import schemas as S
    except ImportError as exc:  # pragma: no cover - depends on installed extras
        raise RuntimeError(
            "the server needs the 'server' extra: pip install 'agentcore[server]'"
        ) from exc
    from agentcore.server.analytics import (
        explore,
        facet_counts,
        filter_traces,
        overview,
        parse_time,
    )
    from agentcore.server.evals import EvalManager
    from agentcore.server.query import QueryError, parse_query
    from agentcore.server.security import SPA_ROUTES, APIKeyMiddleware, BodySizeLimitMiddleware
    from agentcore.server.sessions import SessionStore, valid_session_id

    # --- configuration (explicit arguments > config > env > defaults) -------------------------
    if config is None:
        config = Config()
        apply_env(config)
    cfg = config
    if model is not None:
        cfg.model = model
    if trace_dir is not None:
        cfg.trace_dir = trace_dir
    if workspace is not None:
        cfg.workspace = workspace
    if eval_dirs is not None:
        cfg.eval_dirs = list(eval_dirs)
    if state_dir is not None:
        cfg.data_dir = state_dir
    if api_key is not None:
        cfg.server.api_key = api_key or None
    if cors_origins is not None:
        cfg.server.cors_origins = list(cors_origins)
    if max_body_bytes is not None:
        cfg.server.max_body_bytes = max_body_bytes

    custom_tools = load_tool_modules(cfg.tool_modules) if cfg.tool_modules else {}
    custom_tools.update(extra_tools or {})
    enabled = list(tools or cfg.tools or [*DEFAULT_SERVER_TOOLS, *custom_tools])
    try:
        tool_objs = {
            t.name: t for t in resolve_tools(enabled, workspace=cfg.workspace, extra=custom_tools)
        }
    except KeyError as exc:
        raise ValueError(str(exc).strip('"')) from exc
    allowed_tools = list(tool_objs)

    configure_tracing(cfg.trace_dir)
    store = JSONLTraceStore(cfg.trace_dir)
    default_model = create_model(cfg.model, verbose=True)
    if isinstance(default_model, MockModel):
        default_model.stream_delay = mock_stream_delay
    sessions = SessionStore(Path(cfg.state_dir) / "sessions")
    evals = EvalManager(
        cfg.eval_dirs, cfg.state_dir, default_model=default_model.model_id, tools=custom_tools
    )
    model_cache: dict[str, ModelClient] = {}
    ollama_cache: dict[str, Any] = {"at": 0.0, "models": []}

    app = FastAPI(
        title="AgentCore",
        version=__version__,
        description="AgentCore agent API, OpenAI-compatible endpoint and web app",
    )
    app.state.model = default_model
    app.state.store = store
    app.state.sessions = sessions
    app.state.evals = evals
    app.state.config = cfg

    # Middleware: the last one added is the outermost. CORS wraps everything so that error
    # responses (401/413) still carry CORS headers.
    if cfg.server.api_key:
        app.add_middleware(APIKeyMiddleware, api_key=cfg.server.api_key)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=cfg.server.max_body_bytes)
    if cfg.server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.server.cors_origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key"],
            expose_headers=["X-Total-Count"],
            allow_credentials=False,
        )

    # --- helpers --------------------------------------------------------------------------
    def get_model(spec: str | None) -> ModelClient:
        if not spec or spec == default_model.model_id:
            return default_model
        if spec not in model_cache:
            try:
                m = create_model(spec)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if isinstance(m, MockModel):
                m.stream_delay = mock_stream_delay
            model_cache[spec] = m
        return model_cache[spec]

    def pick_tools(names: list[str] | None) -> list[Any]:
        chosen = allowed_tools if names is None else names
        unknown = [n for n in chosen if n not in tool_objs]
        if unknown:
            raise HTTPException(
                400, f"tools not enabled on this server: {unknown}; enabled: {allowed_tools}"
            )
        return [tool_objs[n] for n in chosen]

    def tool_call_summary(result: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": r.tool_name,
                "arguments": r.arguments,
                "success": r.success,
                "output": r.as_text(1000),
                "error": r.error,
                "latency_ms": round(r.latency_ms, 2),
            }
            for r in result.tool_results
        ]

    def get_session(session_id: str) -> Any:
        s = sessions.get(session_id) if valid_session_id(session_id) else None
        if s is None:
            raise HTTPException(404, f"session {session_id!r} not found")
        return s

    # --- shell, health, metadata ----------------------------------------------------------
    def shell() -> HTMLResponse:
        return HTMLResponse(dashboard_html(), headers={"Cache-Control": "no-cache"})

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        return shell()

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(
            (STATIC_DIR / "favicon.svg").read_bytes(),
            media_type="image/svg+xml",
            headers={"Cache-Control": "max-age=86400"},
        )

    class AppStatic(StaticFiles):
        """Hashed build assets are immutable; everything else is revalidated (ETag)."""

        async def get_response(self, path: str, scope: Any) -> Any:
            response = await super().get_response(path, scope)
            if path.replace("\\", "/").startswith("assets/") and response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-cache"
            return response

    app.mount("/static", AppStatic(directory=str(STATIC_DIR), check_dir=False), name="static")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "model": default_model.model_id,
            "tools": allowed_tools,
            "auth": bool(cfg.server.api_key),
        }

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return {
            **cfg.to_dict(),
            "version": __version__,
            "python": platform.python_version(),
            "default_model": default_model.model_id,
            "enabled_tools": allowed_tools,
            "custom_tools": sorted(custom_tools),
        }

    async def ollama_models() -> list[str]:
        if time.time() - ollama_cache["at"] < 30:
            return ollama_cache["models"]
        names: list[str] = []
        try:
            import httpx

            from agentcore.runtime.providers.ollama import ollama_host

            async with httpx.AsyncClient(timeout=0.4) as client:
                resp = await client.get(f"{ollama_host()}/api/tags")
                resp.raise_for_status()
                names = [f"ollama:{m['name']}" for m in resp.json().get("models", [])]
        except Exception:
            names = []
        ollama_cache.update(at=time.time(), models=names)
        return names

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        ids: list[str] = []
        for m in [default_model.model_id, *cfg.models, "mock", *(await ollama_models())]:
            if m and m not in ids:
                ids.append(m)
        now = int(time.time())
        return {
            "object": "list",
            "data": [
                {
                    "id": m,
                    "object": "model",
                    "created": now,
                    "owned_by": "agentcore",
                    "default": m == default_model.model_id,
                }
                for m in ids
            ],
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return get_metrics().export_prometheus()

    # --- one-shot agent run ---------------------------------------------------------------
    @app.post("/v1/agent")
    async def run_agent(req: S.AgentRequest) -> dict[str, Any]:
        if not req.input and not req.messages:
            raise HTTPException(400, "provide 'input' or 'messages'")
        tl = pick_tools(req.tools)
        mdl = get_model(req.model)
        session = None
        if req.session_id:
            if not req.input:
                raise HTTPException(400, "sessions take 'input' (history lives on the server)")
            try:
                session = sessions.get_or_create(req.session_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if session.busy:
                raise HTTPException(409, "this session is already running a turn")
        agent = Agent(
            mdl,
            tools=tl,
            system_prompt=req.system_prompt or cfg.system_prompt,
            max_steps=req.max_steps,
            memory=session.memory if session else None,
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
        if session is not None:
            now = time.time()
            if not session.turns:
                session.title = (req.input or "")[:60]
            session.turns.append({"role": "user", "content": req.input, "ts": now})
            session.turns.append(
                {
                    "role": "assistant",
                    "content": result.output,
                    "parts": [{"type": "text", "content": result.output}],
                    "trace_id": result.trace_id,
                    "status": "ok" if result.stop_reason == "final" else result.stop_reason,
                    "usage": result.usage.to_dict(),
                    "model": mdl.model_id,
                    "ts": now,
                }
            )
            sessions.save(session)
        return {
            "id": f"run_{uuid.uuid4().hex[:16]}",
            "object": "agent.run",
            "created": int(time.time()),
            "model": mdl.model_id,
            "output": result.output,
            "stop_reason": result.stop_reason,
            "steps": result.steps,
            "usage": result.usage.to_dict(),
            "tool_calls": tool_call_summary(result),
            "trace_id": result.trace_id,
            "session_id": session.id if session else None,
            "duration_ms": round(result.duration_ms, 2),
        }

    # --- streaming chat with sessions -----------------------------------------------------
    def run_in_background(
        agent: Agent, task: Any, span_attrs: dict[str, Any] | None = None
    ) -> tuple[asyncio.Task[Any], asyncio.Queue]:
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def push(ev: AgentEvent) -> None:
            if ev.type == "run_start":
                ev.data["trace_id"] = current_trace_id()
                root = current_span()
                if root is not None and span_attrs:
                    root.set_attributes(span_attrs)  # e.g. session.id, for trace filters
            await queue.put(ev)

        async def runner() -> Any:
            try:
                return await agent.run(task, callbacks=[push])
            finally:
                queue.put_nowait(None)

        return asyncio.create_task(runner()), queue

    @app.post("/api/chat")
    async def chat(req: S.ChatStreamRequest) -> StreamingResponse:
        try:
            session = sessions.get_or_create(req.session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if session.busy:
            raise HTTPException(409, "this session is already running a turn")
        mdl = get_model(req.model)
        tl = pick_tools(req.tools)
        system_prompt = req.system_prompt or cfg.system_prompt
        agent = Agent(
            mdl,
            tools=tl,
            system_prompt=system_prompt,
            max_steps=req.max_steps,
            memory=session.memory,
            stream=True,
            name="chat",
        )
        session.settings = {
            "model": mdl.model_id,
            "tools": [t.name for t in tl],
            "system_prompt": req.system_prompt,
            "max_steps": req.max_steps,
        }
        if not session.turns:
            session.title = " ".join(req.message.split())[:60] or "New chat"
        # What the model gets besides the new message (shown as "added to context" chips).
        context = {
            "tools": [t.name for t in tl],
            "system_prompt": "custom" if system_prompt else "default",
            "memory_messages": len(session.memory.get_messages()),
        }
        session.turns.append({"role": "user", "content": req.message, "ts": time.time()})
        task, queue = run_in_background(agent, req.message, {"session.id": session.id})
        session.task = task
        sessions.save(session)

        async def events() -> Any:
            turn: dict[str, Any] = {
                "role": "assistant",
                "content": "",
                "parts": [],
                "model": mdl.model_id,
                "status": "running",
                "context": context,
                "ts": time.time(),
            }
            parts: list[dict[str, Any]] = turn["parts"]
            yield sse(
                "session",
                {
                    "session_id": session.id,
                    "title": session.title,
                    "model": mdl.model_id,
                    "context": context,
                },
            )
            try:
                while True:
                    ev = await queue.get()
                    if ev is None:
                        break
                    data = {"step": ev.step, **ev.data}
                    if ev.type == "run_start":
                        turn["trace_id"] = ev.data.get("trace_id")
                    elif ev.type == "token":
                        last = parts[-1] if parts else None
                        if last and last["type"] == "text" and last.get("step") == ev.step:
                            last["content"] += ev.data["content"]
                        else:
                            parts.append(
                                {"type": "text", "step": ev.step, "content": ev.data["content"]}
                            )
                    elif ev.type == "model_response":
                        usage_d = ev.data.get("usage") or {}
                        parts.append(
                            {
                                "type": "model",
                                "step": ev.step,
                                "latency_ms": round(float(ev.data.get("latency_ms") or 0), 2),
                                "tokens": usage_d.get("total_tokens", 0),
                                "tool_calls": len(ev.data.get("tool_calls") or []),
                            }
                        )
                        has_text = any(
                            p["type"] == "text" and p.get("step") == ev.step for p in parts
                        )
                        if ev.data.get("content") and not has_text:
                            parts.append(
                                {"type": "text", "step": ev.step, "content": ev.data["content"]}
                            )
                    elif ev.type == "tool_start":
                        parts.append(
                            {
                                "type": "tool",
                                "id": ev.data["id"],
                                "name": ev.data["name"],
                                "arguments": ev.data["arguments"],
                                "step": ev.step,
                                "status": "running",
                            }
                        )
                    elif ev.type == "tool_end":
                        for p in parts:
                            if p["type"] == "tool" and p.get("id") == ev.data["id"]:
                                p.update(
                                    status="ok" if ev.data["success"] else "error",
                                    output=ev.data["output"],
                                    error=ev.data["error"],
                                    latency_ms=round(ev.data["latency_ms"], 2),
                                )
                    elif ev.type == "reflection":
                        parts.append(
                            {"type": "note", "step": ev.step, "content": ev.data["content"]}
                        )
                    elif ev.type == "final":
                        turn["content"] = ev.data["output"]
                    yield sse(ev.type, data)
                await asyncio.wait([task])
                if task.cancelled():
                    turn["status"] = "stopped"
                    yield sse("stopped", {"trace_id": turn.get("trace_id")})
                elif task.exception() is not None:
                    exc = task.exception()
                    turn["status"] = "error"
                    turn["error"] = f"{type(exc).__name__}: {exc}"
                    yield sse("error", {"message": turn["error"], "trace_id": turn.get("trace_id")})
                else:
                    result = task.result()
                    if result.stop_reason != "final":
                        turn["content"] = result.output
                        parts.append({"type": "note", "content": result.error or result.output})
                    usage = result.usage.to_dict()
                    cost = estimate_cost(
                        mdl.model_id, result.usage.prompt_tokens, result.usage.completion_tokens
                    )
                    turn.update(
                        status="ok" if result.stop_reason == "final" else result.stop_reason,
                        trace_id=result.trace_id,
                        usage=usage,
                        cost_usd=round(cost, 6),
                        steps=result.steps,
                        duration_ms=round(result.duration_ms, 2),
                    )
                    yield sse(
                        "done",
                        {
                            "session_id": session.id,
                            "trace_id": result.trace_id,
                            "output": result.output,
                            "stop_reason": result.stop_reason,
                            "steps": result.steps,
                            "usage": usage,
                            "cost_usd": round(cost, 6),
                            "duration_ms": round(result.duration_ms, 2),
                        },
                    )
            except asyncio.CancelledError:  # client went away: stop the agent too
                task.cancel()
                turn["status"] = "stopped"
                raise
            finally:
                if session.task is task:
                    session.task = None
                if not turn["content"]:
                    turn["content"] = "".join(p["content"] for p in parts if p["type"] == "text")
                session.turns.append(turn)
                sessions.save(session)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        return [s.summary() for s in sessions.list()]

    @app.post("/api/sessions", status_code=201)
    def create_session(req: S.SessionCreate | None = None) -> dict[str, Any]:
        s = sessions.create(title=req.title if req else None)
        sessions.save(s)
        return s.to_dict()

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str) -> dict[str, Any]:
        return get_session(session_id).to_dict()

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, Any]:
        get_session(session_id)
        sessions.delete(session_id)
        return {"deleted": session_id}

    @app.post("/api/sessions/{session_id}/stop")
    def stop_session(session_id: str) -> dict[str, Any]:
        s = get_session(session_id)
        if s.busy and s.task is not None:
            s.task.cancel()
            return {"stopped": True}
        return {"stopped": False}

    # --- OpenAI-compatible chat completions -----------------------------------------------
    def oai_error(status: int, message: str, code: str | None = None) -> JSONResponse:
        return JSONResponse(
            {"error": {"message": message, "type": "invalid_request_error", "code": code}},
            status_code=status,
        )

    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(req: S.ChatCompletionRequest) -> Any:
        try:
            mdl = default_model if req.model in OAI_DEFAULT_NAMES else get_model(req.model)
        except HTTPException:
            return oai_error(
                404,
                f"model {req.model!r} not found; use 'agentcore' (server default) or a spec "
                "like 'mock', 'ollama:<model>', 'openai:<model>'",
                "model_not_found",
            )
        messages = _oai_messages(req.messages)
        if not any(m.role == "user" for m in messages):
            return oai_error(400, "messages must include at least one user message")
        options: dict[str, Any] = {"temperature": req.temperature or 0.0}
        if req.max_tokens or req.max_completion_tokens:
            options["max_tokens"] = req.max_tokens or req.max_completion_tokens
        agent = Agent(
            mdl,
            tools=list(tool_objs.values()),
            system_prompt=cfg.system_prompt,
            max_steps=8,
            stream=req.stream,
            name="openai",
            **options,
        )
        cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        model_name = req.model or mdl.model_id

        if not req.stream:
            try:
                result = await agent.run(messages)
            except Exception as exc:
                return oai_error(502, f"agent failed: {type(exc).__name__}: {exc}")
            return {
                "id": cid,
                "object": "chat.completion",
                "created": created,
                "model": model_name,
                "system_fingerprint": f"agentcore-{__version__}",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": result.output},
                        "finish_reason": "stop" if result.stop_reason == "final" else "length",
                        "logprobs": None,
                    }
                ],
                "usage": result.usage.to_dict(),
                "agentcore": {
                    "trace_id": result.trace_id,
                    "steps": result.steps,
                    "stop_reason": result.stop_reason,
                    "tool_calls": tool_call_summary(result),
                },
            }

        task, queue = run_in_background(agent, messages)
        include_usage = bool(req.stream_options and req.stream_options.include_usage)

        def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
            payload = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "system_fingerprint": f"agentcore-{__version__}",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        async def stream() -> Any:
            yield chunk({"role": "assistant", "content": ""})
            streamed_final = False
            try:
                while True:
                    ev = await queue.get()
                    if ev is None:
                        break
                    if ev.type == "token" and ev.data.get("content"):
                        yield chunk({"content": ev.data["content"]})
                    elif ev.type == "model_response":
                        streamed_final = not ev.data.get("tool_calls")
                await asyncio.wait([task])
                if task.cancelled() or task.exception() is not None:
                    exc = None if task.cancelled() else task.exception()
                    err = {"message": f"agent failed: {exc}" if exc else "cancelled"}
                    yield f"data: {json.dumps({'error': err})}\n\n"
                else:
                    result = task.result()
                    if not streamed_final and result.output:
                        yield chunk({"content": result.output})
                    yield chunk({}, "stop" if result.stop_reason == "final" else "length")
                    if include_usage:
                        payload = {
                            "id": cid,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_name,
                            "choices": [],
                            "usage": result.usage.to_dict(),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                yield "data: [DONE]\n\n"
            except asyncio.CancelledError:
                task.cancel()
                raise

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- traces ---------------------------------------------------------------------------
    @app.get("/api/traces")
    def list_traces(
        limit: int = Query(50, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        q: str | None = None,
        status: str | None = None,
        model: str | None = None,
        kind: str | None = None,
        since: str | None = None,
        until: str | None = None,
        query: str | None = Query(None, max_length=2000, description="explorer query language"),
        sort: str = "time",
        order: str = "desc",
    ) -> Response:
        try:
            items = filter_traces(
                store,
                q=q,
                status=status,
                model=model,
                kind=kind,
                since=parse_time(since),
                until=parse_time(until),
                query=query,
                sort=sort,
                order=order,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        page = [s.to_dict() for s in items[offset : offset + limit]]
        return JSONResponse(page, headers={"X-Total-Count": str(len(items))})

    @app.get("/api/traces/facets")
    def trace_facets(query: str | None = Query(None, max_length=2000)) -> dict[str, Any]:
        items = store.list(None)
        try:
            tq = parse_query(query)
        except QueryError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "count": len(items),
            "models": sorted({s.model for s in items if s.model}),
            "names": sorted({s.name for s in items}),
            "facets": facet_counts(items, tq),
        }

    @app.get("/api/traces/explore")
    def trace_explore(
        query: str | None = Query(None, max_length=2000),
        since: str | None = None,
        until: str | None = None,
        sort: str = "time",
        order: str = "desc",
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        buckets: int = Query(48, ge=4, le=200),
    ) -> Any:
        """Rows, total, facet counts, histogram and percentiles for the trace explorer."""
        try:
            return explore(
                store,
                query=query,
                since=parse_time(since),
                until=parse_time(until),
                sort=sort,
                order=order,
                limit=limit,
                offset=offset,
                buckets=buckets,
            )
        except QueryError as exc:
            return JSONResponse(
                {"detail": str(exc), "position": exc.position, "type": "query_error"},
                status_code=400,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def load_trace(trace_id: str) -> tuple[str, list[Any]]:
        resolved = store.resolve(trace_id)
        if resolved is None:
            raise HTTPException(404, f"trace {trace_id!r} not found")
        return resolved, store.load(resolved)

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str) -> dict[str, Any]:
        resolved, spans = load_trace(trace_id)
        summary = store.summarize(resolved)
        return {
            "trace_id": resolved,
            "summary": summary.to_dict() if summary else None,
            "spans": [s.to_dict() for s in spans],
        }

    @app.get("/api/traces/{trace_id}/export")
    def export_trace(trace_id: str) -> Response:
        resolved, spans = load_trace(trace_id)
        summary = store.summarize(resolved)
        body = json.dumps(
            {
                "trace_id": resolved,
                "exported_by": f"agentcore {__version__}",
                "summary": summary.to_dict() if summary else None,
                "spans": [s.to_dict() for s in spans],
            },
            indent=2,
            ensure_ascii=False,
        )
        return Response(
            body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="trace-{resolved}.json"'},
        )

    @app.get("/api/overview")
    def get_overview(
        days: float = Query(7, gt=0, le=365), tz: int = Query(0, ge=-900, le=900)
    ) -> dict[str, Any]:
        return overview(store, days=days, tz_offset_min=tz)

    # --- tools ----------------------------------------------------------------------------
    @app.get("/api/tools")
    def list_tools() -> list[dict[str, Any]]:
        def source(name: str, t: Any) -> str:
            # A project's tool module may re-export built-ins (e.g. calculator);
            # only tools defined outside AgentCore count as custom.
            module = getattr(getattr(t, "fn", None), "__module__", "") or ""
            builtin = module.startswith("agentcore.")
            return "custom" if name in custom_tools and not builtin else "builtin"

        return [{**t.to_dict(), "source": source(name, t)} for name, t in tool_objs.items()]

    @app.post("/api/tools/{name}/invoke")
    async def invoke_tool(name: str, req: S.ToolInvokeRequest) -> dict[str, Any]:
        if name not in tool_objs:
            raise HTTPException(404, f"tool {name!r} is not enabled on this server")
        engine = ExecutionEngine(ToolRegistry([tool_objs[name]]))
        tracer = get_tracer()
        with tracer.span(
            "tool.invoke", {"tool.name": name, "task": json.dumps(req.arguments)[:500]}
        ) as root:
            with tracer.span(
                "tool.execute", {"tool.name": name, "tool.arguments": req.arguments}
            ) as span:
                result = await engine.execute(name, req.arguments)
                span.set_attributes(
                    {"tool.success": result.success, "latency.ms": round(result.latency_ms, 2)}
                )
                span.set_attribute("tool.output", result.as_text(500))
                if not result.success:
                    span.record_error(result.error or "tool failed")
            root.set_attribute("output", result.as_text(500))
            trace_id = root.trace_id
        get_metrics().counter(
            "agentcore_tool_calls_total", labels={"tool": name, "success": result.success}
        )
        return {**result.to_dict(), "text": result.as_text(4000), "trace_id": trace_id}

    # --- evals ----------------------------------------------------------------------------
    @app.get("/api/evals/suites")
    def eval_suites() -> list[dict[str, Any]]:
        return evals.discover()

    @app.post("/api/evals/starter", status_code=201)
    def create_starter_suite() -> dict[str, Any]:
        """Create ``starter.yaml`` in the first eval directory (never overwrites)."""
        try:
            return evals.create_starter()
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/evals/runs", status_code=202)
    async def start_eval(req: S.EvalRunRequest) -> dict[str, Any]:
        try:
            job = evals.start(req.suite, model=req.model, tags=req.tags)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip('"')) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return job.to_dict(full=False)

    @app.get("/api/evals/runs")
    def eval_runs(suite: str | None = None, limit: int = Query(50, ge=1, le=500)) -> list[Any]:
        active = [
            j.to_dict(full=False)
            for j in evals.jobs.values()
            if j.status in ("queued", "running") and (suite is None or j.suite == suite)
        ]
        return active + evals.history(suite, limit=limit)

    @app.get("/api/evals/matrix")
    def eval_matrix(suite: str, limit: int = Query(8, ge=1, le=30)) -> dict[str, Any]:
        """Cases (rows) x the most recent completed runs (columns) of one suite."""
        return evals.matrix(suite, limit=limit)

    @app.get("/api/evals/runs/{run_id}")
    def eval_run(run_id: str) -> dict[str, Any]:
        data = evals.get(run_id)
        if data is None:
            raise HTTPException(404, f"eval run {run_id!r} not found")
        return data

    @app.post("/api/evals/runs/{run_id}/baseline")
    def eval_baseline(run_id: str) -> dict[str, Any]:
        try:
            return evals.set_baseline(run_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip('"')) from exc

    # --- web app routes (client-side routing) -----------------------------------------------
    # Registered last so every API route wins. Deep links such as /traces/<id>?query=... and
    # /playground/<session> load the app shell; the browser router takes it from there.
    @app.get("/{section}", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/{section}/{rest:path}", response_class=HTMLResponse, include_in_schema=False)
    def spa(section: str, rest: str = "") -> HTMLResponse:
        if section not in SPA_ROUTES:
            raise HTTPException(404, "Not Found")
        return shell()

    return app
