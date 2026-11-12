"""The ReAct agent loop: plan (model call) -> act (tools) -> observe -> reflect."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from agentcore.obs.cost import CostTracker, estimate_cost
from agentcore.obs.metrics import get_metrics
from agentcore.obs.tracing import Tracer, current_trace_id, get_tracer
from agentcore.runtime.context import ContextManager, TokenBudget
from agentcore.runtime.memory import Memory
from agentcore.runtime.model_client import ModelClient
from agentcore.tools.execution import ExecutionEngine, ToolResult
from agentcore.tools.registry import ToolRegistry, ensure_registry
from agentcore.types import ChatResponse, DoneEvent, Message, TokenEvent, ToolCall, Usage

logger = logging.getLogger("agentcore.agent")

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, precise assistant. Use the available tools when they help you answer "
    "correctly; never guess results a tool can compute. When you have enough information, "
    "reply with the final answer directly and concisely."
)

REFLECTION_PROMPT = (
    "Pause and reflect before continuing. In 2-4 short sentences: what has been done so far, "
    "what is still missing to answer the task, and whether the approach should change."
)


@dataclass
class AgentConfig:
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_steps: int = 10
    temperature: float = 0.0
    max_tokens: int | None = None
    parallel_tool_calls: bool = True
    stream: bool = False
    reflect_every: int | None = None  # LLM self-reflection every N tool rounds
    stuck_threshold: int = 2  # identical tool calls repeated this often -> nudge
    timeout_seconds: float | None = None
    context_window: int | None = None  # enable ContextManager truncation when set
    max_tool_output_tokens: int = 2000
    trace_content: bool = True  # record model inputs/outputs (truncated) on model.generate spans


@dataclass
class AgentEvent:
    type: str  # run_start|step_start|token|model_response|tool_start|tool_end|reflection|final|error|run_end
    step: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "step": self.step,
            "data": self.data,
            "timestamp": self.timestamp,
        }


@dataclass
class AgentResult:
    output: str
    messages: list[Message]
    steps: int
    usage: Usage
    tool_results: list[ToolResult]
    stop_reason: str  # final | max_steps | timeout | error
    duration_ms: float = 0.0
    trace_id: str | None = None
    error: str | None = None
    events: list[AgentEvent] = field(default_factory=list)

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [tc for m in self.messages if m.role == "assistant" for tc in m.tool_calls]

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "steps": self.steps,
            "stop_reason": self.stop_reason,
            "usage": self.usage.to_dict(),
            "duration_ms": round(self.duration_ms, 2),
            "trace_id": self.trace_id,
            "error": self.error,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "tool_results": [r.to_dict() for r in self.tool_results],
            "messages": [m.to_dict() for m in self.messages],
        }


Callback = Callable[[AgentEvent], Any]
ReflectionHook = Callable[[list[Message], int], "str | None | Awaitable[str | None]"]


class Agent:
    """A tool-using ReAct agent with native tool calling.

    Example::

        agent = Agent(create_model("mock"), tools=[calculator])
        result = agent.run_sync("What is 17 * 23 + 4?")
    """

    def __init__(
        self,
        model: ModelClient | str | None = None,
        tools: ToolRegistry | Iterable[Any] | None = None,
        *,
        system_prompt: str | None = None,
        config: AgentConfig | None = None,
        memory: Memory | None = None,
        callbacks: list[Callback] | None = None,
        reflection_hook: ReflectionHook | None = None,
        name: str = "agent",
        tracer: Tracer | None = None,
        cost_tracker: CostTracker | None = None,
        engine: ExecutionEngine | None = None,
        **config_overrides: Any,
    ):
        from agentcore.runtime.providers import create_model

        self.model = create_model(model) if not isinstance(model, ModelClient) else model
        self.tools = ensure_registry(tools)
        self.config = config or AgentConfig()
        for k, v in config_overrides.items():
            if not hasattr(self.config, k):
                raise TypeError(f"unknown agent option {k!r}")
            setattr(self.config, k, v)
        if system_prompt is not None:
            self.config.system_prompt = system_prompt
        self.memory = memory
        self.callbacks: list[Callback] = list(callbacks or [])
        self.reflection_hook = reflection_hook
        self.name = name
        self._tracer = tracer
        self.cost_tracker = cost_tracker
        self.engine = engine or ExecutionEngine(self.tools)
        self.context_manager = (
            ContextManager(
                TokenBudget(
                    context_window=self.config.context_window,
                    reserve_output=self.config.max_tokens or 1024,
                    max_tool_output=self.config.max_tool_output_tokens,
                )
            )
            if self.config.context_window
            else None
        )

    @property
    def tracer(self) -> Tracer:
        return self._tracer or get_tracer()

    def on(self, callback: Callback) -> Callback:
        """Register an event callback (usable as a decorator)."""
        self.callbacks.append(callback)
        return callback

    # ---------------------------------------------------------------------------------
    async def _emit(self, event: AgentEvent, sink: list[AgentEvent], extra: list[Callback]) -> None:
        sink.append(event)
        for cb in [*self.callbacks, *extra]:
            try:
                res = cb(event)
                if inspect.isawaitable(res):
                    await res
            except Exception:  # callbacks must not break the loop
                logger.exception("agent callback failed")

    def _initial_messages(self, task: str | list[Message]) -> tuple[list[Message], str]:
        if isinstance(task, list):
            msgs = list(task)
            if not any(m.role == "system" for m in msgs):
                msgs.insert(0, Message.system(self.config.system_prompt))
            user_text = next((m.content for m in reversed(msgs) if m.role == "user"), "")
            return msgs, user_text
        history = self.memory.get_messages(task) if self.memory else []
        sys_msgs = [Message.system(self.config.system_prompt)]
        # memory may contribute extra system messages (summaries, recalled facts)
        extra_sys = [m for m in history if m.role == "system"]
        convo = [m for m in history if m.role != "system"]
        return sys_msgs + extra_sys + convo + [Message.user(task)], task

    async def _call_model(
        self,
        messages: list[Message],
        step: int,
        sink: list[AgentEvent],
        extra: list[Callback],
        use_tools: bool = True,
    ) -> ChatResponse:
        tool_specs = self.tools.to_openai() if (use_tools and len(self.tools)) else None
        if self.context_manager is not None:
            messages = self.context_manager.fit(messages, tool_specs)
        attrs = {"model": self.model.model_id, "step": step, "messages": len(messages)}
        with self.tracer.span("model.generate", attrs) as span:
            if self.config.stream:
                resp = None
                async for ev in self.model.stream(
                    messages,
                    tool_specs,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                ):
                    if isinstance(ev, TokenEvent):
                        await self._emit(
                            AgentEvent("token", step, {"content": ev.content}), sink, extra
                        )
                    elif isinstance(ev, DoneEvent):
                        resp = ev.response
                if resp is None:
                    raise RuntimeError("model stream ended without a DoneEvent")
            else:
                resp = await self.model.generate(
                    messages,
                    tool_specs,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
            cost = estimate_cost(
                self.model.model_id, resp.usage.prompt_tokens, resp.usage.completion_tokens
            )
            if self.config.trace_content:
                span.set_attributes(
                    {
                        "input.messages": _trace_messages(messages),
                        "output.content": resp.content[:TRACE_TEXT_LIMIT],
                        "output.tool_calls": [tc.to_dict() for tc in resp.tool_calls],
                    }
                )
            span.set_attributes(
                {
                    "tokens.prompt": resp.usage.prompt_tokens,
                    "tokens.completion": resp.usage.completion_tokens,
                    "tokens.total": resp.usage.total_tokens,
                    "cost.usd": cost,
                    "latency.ms": round(resp.latency_ms, 2),
                    "tool_calls": [tc.name for tc in resp.tool_calls],
                }
            )
        if self.cost_tracker is not None:
            self.cost_tracker.record(
                self.model.model_id,
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
                agent=self.name,
            )
        m = get_metrics()
        m.counter("agentcore_model_calls_total", labels={"model": self.model.model_id})
        m.counter(
            "agentcore_tokens_total", resp.usage.total_tokens, labels={"model": self.model.model_id}
        )
        m.histogram(
            "agentcore_model_latency_ms", resp.latency_ms, labels={"model": self.model.model_id}
        )
        return resp

    async def _run_tool(
        self, tc: ToolCall, step: int, sink: list[AgentEvent], extra: list[Callback]
    ) -> ToolResult:
        await self._emit(
            AgentEvent(
                "tool_start", step, {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            ),
            sink,
            extra,
        )
        with self.tracer.span(
            "tool.execute", {"tool.name": tc.name, "tool.arguments": tc.arguments}
        ) as span:
            result = await self.engine.execute(tc.name, tc.arguments, call_id=tc.id)
            span.set_attributes(
                {"tool.success": result.success, "latency.ms": round(result.latency_ms, 2)}
            )
            if not result.success:
                span.record_error(result.error or "tool failed")
            span.set_attribute("tool.output", result.as_text(500))
        get_metrics().counter(
            "agentcore_tool_calls_total", labels={"tool": tc.name, "success": result.success}
        )
        get_metrics().histogram(
            "agentcore_tool_latency_ms", result.latency_ms, labels={"tool": tc.name}
        )
        await self._emit(
            AgentEvent(
                "tool_end",
                step,
                {
                    "id": tc.id,
                    "name": tc.name,
                    "success": result.success,
                    "output": result.as_text(2000),
                    "error": result.error,
                    "latency_ms": result.latency_ms,
                },
            ),
            sink,
            extra,
        )
        return result

    async def _reflect(
        self,
        messages: list[Message],
        step: int,
        sink: list[AgentEvent],
        extra: list[Callback],
        calls_seen: dict[str, int],
    ) -> None:
        notes: list[str] = []
        # 1) stuck detection: the same call (name + args) repeated
        last = messages[-1] if messages else None
        for m in reversed(messages):
            if m.role == "assistant" and m.tool_calls:
                last = m
                break
        if last is not None:
            for tc in last.tool_calls:
                if calls_seen.get(_call_key(tc), 0) >= self.config.stuck_threshold:
                    notes.append(
                        f"You have called {tc.name} with the same arguments {calls_seen[_call_key(tc)]} times. "
                        "Do not repeat it; use the results you already have or try a different approach."
                    )
                    break
        # 2) user-provided hook
        if self.reflection_hook is not None:
            res = self.reflection_hook(messages, step)
            if inspect.isawaitable(res):
                res = await res
            if res:
                notes.append(str(res))
        # 3) periodic LLM self-reflection
        if self.config.reflect_every and step % self.config.reflect_every == 0:
            with self.tracer.span("agent.reflect", {"step": step}):
                resp = await self._call_model(
                    [*messages, Message.user(REFLECTION_PROMPT)], step, sink, extra, use_tools=False
                )
            if resp.content.strip():
                notes.append(resp.content.strip())
        for note in notes:
            messages.append(Message.user(f"[reflection] {note}"))
            await self._emit(AgentEvent("reflection", step, {"content": note}), sink, extra)

    async def _loop(
        self,
        task: str | list[Message],
        sink: list[AgentEvent],
        extra: list[Callback],
        state: dict[str, Any],
    ) -> AgentResult:
        messages, user_text = self._initial_messages(task)
        state["messages"] = messages
        usage = Usage()
        tool_results: list[ToolResult] = state.setdefault("tool_results", [])
        calls_seen: dict[str, int] = {}
        output, stop_reason, step = "", "max_steps", 0
        for step in range(1, self.config.max_steps + 1):
            state["step"] = step
            with self.tracer.span("agent.step", {"step": step}):
                await self._emit(AgentEvent("step_start", step), sink, extra)
                resp = await self._call_model(messages, step, sink, extra)
                usage = usage + resp.usage
                state["usage"] = usage
                messages.append(resp.message)
                await self._emit(
                    AgentEvent(
                        "model_response",
                        step,
                        {
                            "content": resp.content,
                            "tool_calls": [tc.to_dict() for tc in resp.tool_calls],
                            "usage": resp.usage.to_dict(),
                            "latency_ms": resp.latency_ms,
                        },
                    ),
                    sink,
                    extra,
                )
                if not resp.tool_calls:
                    output, stop_reason = resp.content, "final"
                    break
                for tc in resp.tool_calls:
                    calls_seen[_call_key(tc)] = calls_seen.get(_call_key(tc), 0) + 1
                if self.config.parallel_tool_calls and len(resp.tool_calls) > 1:
                    results = await asyncio.gather(
                        *(self._run_tool(tc, step, sink, extra) for tc in resp.tool_calls)
                    )
                else:
                    results = [
                        await self._run_tool(tc, step, sink, extra) for tc in resp.tool_calls
                    ]
                for tc, res in zip(resp.tool_calls, results):
                    tool_results.append(res)
                    messages.append(Message.tool(res.as_text(), tc.id, tc.name))
                await self._reflect(messages, step, sink, extra, calls_seen)
        else:
            last = next(
                (m.content for m in reversed(messages) if m.role == "assistant" and m.content), ""
            )
            output = last or f"Stopped after {self.config.max_steps} steps without a final answer."
        if self.memory is not None and user_text:
            self.memory.add(Message.user(user_text))
            self.memory.add(Message.assistant(output))
            await self.memory.compact()
        return AgentResult(output, messages, step, usage, tool_results, stop_reason)

    async def run(
        self, task: str | list[Message], *, callbacks: list[Callback] | None = None
    ) -> AgentResult:
        """Run the agent on a task (a string, or a full message list)."""
        sink: list[AgentEvent] = []
        extra = list(callbacks or [])
        state: dict[str, Any] = {}
        start = time.perf_counter()
        task_preview = task if isinstance(task, str) else (task[-1].content if task else "")
        get_metrics().counter("agentcore_agent_runs_total", labels={"agent": self.name})
        with self.tracer.span(
            f"agent.run:{self.name}",
            {"agent.name": self.name, "task": task_preview[:500], "model": self.model.model_id},
        ) as span:
            await self._emit(
                AgentEvent("run_start", 0, {"task": task_preview, "agent": self.name}), sink, extra
            )
            try:
                coro = self._loop(task, sink, extra, state)
                if self.config.timeout_seconds:
                    result = await asyncio.wait_for(coro, self.config.timeout_seconds)
                else:
                    result = await coro
            except asyncio.TimeoutError:
                span.record_error("timeout")
                result = AgentResult(
                    "",
                    state.get("messages", []),
                    state.get("step", 0),
                    state.get("usage", Usage()),
                    state.get("tool_results", []),
                    "timeout",
                    error=f"agent timed out after {self.config.timeout_seconds}s",
                )
            except Exception as exc:
                span.record_error(exc)
                await self._emit(
                    AgentEvent("error", state.get("step", 0), {"error": str(exc)}), sink, extra
                )
                raise
            result.duration_ms = (time.perf_counter() - start) * 1000
            result.trace_id = current_trace_id()
            span.set_attributes(
                {
                    "steps": result.steps,
                    "stop_reason": result.stop_reason,
                    "tokens.total": result.usage.total_tokens,
                    "output": result.output[:1000],
                }
            )
            if result.stop_reason == "final":
                await self._emit(
                    AgentEvent("final", result.steps, {"output": result.output}), sink, extra
                )
            await self._emit(
                AgentEvent(
                    "run_end",
                    result.steps,
                    {
                        "stop_reason": result.stop_reason,
                        "usage": result.usage.to_dict(),
                        "duration_ms": result.duration_ms,
                    },
                ),
                sink,
                extra,
            )
        result.events = sink
        return result

    def run_sync(self, task: str | list[Message], **kwargs: Any) -> AgentResult:
        """Blocking convenience wrapper around :meth:`run`."""
        return asyncio.run(self.run(task, **kwargs))

    async def stream(self, task: str | list[Message]) -> AsyncIterator[AgentEvent]:
        """Yield :class:`AgentEvent` objects as the run progresses (tokens included if ``stream=True``)."""
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def push(ev: AgentEvent) -> None:
            await queue.put(ev)

        async def runner() -> AgentResult:
            try:
                return await self.run(task, callbacks=[push])
            finally:
                await queue.put(None)

        job = asyncio.create_task(runner())
        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield ev
        await job  # re-raise errors from the run

    def as_tool(self, name: str | None = None, description: str | None = None) -> Any:
        """Expose this agent as a tool another agent can call (agent-as-tool delegation)."""
        from agentcore.tools.decorator import Tool

        async def delegate(task: str) -> str:
            return (await self.run(task)).output

        return Tool(
            name=name or self.name,
            description=description or f"Delegate a sub-task to the {self.name} agent.",
            parameters={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The sub-task to perform."}
                },
                "required": ["task"],
            },
            fn=delegate,
            category="agents",
            timeout=None,
        )


TRACE_TEXT_LIMIT = 4000
TRACE_MAX_MESSAGES = 40


def _trace_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """A compact, size-bounded copy of the prompt for trace inspection."""
    out = []
    for m in messages[-TRACE_MAX_MESSAGES:]:
        d: dict[str, Any] = {"role": m.role, "content": m.content[:TRACE_TEXT_LIMIT]}
        if len(m.content) > TRACE_TEXT_LIMIT:
            d["truncated"] = len(m.content) - TRACE_TEXT_LIMIT
        if m.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in m.tool_calls]
        if m.name:
            d["name"] = m.name
        out.append(d)
    if len(messages) > TRACE_MAX_MESSAGES:
        out.insert(
            0,
            {
                "role": "note",
                "content": f"{len(messages) - TRACE_MAX_MESSAGES} earlier messages omitted",
            },
        )
    return out


def _call_key(tc: ToolCall) -> str:
    return f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True, default=str)}"
