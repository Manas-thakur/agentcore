"""A state-graph workflow engine built from scratch.

Execution model (bulk-synchronous "super-steps"):

1. All scheduled nodes run concurrently on a snapshot of the shared state.
2. Each node returns a partial update (``dict``); updates are merged with per-key
   *reducers* (default: replace; e.g. ``append`` for lists collected from parallel nodes).
3. Outgoing edges pick the next nodes: static edges, conditional edges (a router function),
   fan-out (one -> many) and joins (many -> one, waits for all sources).
4. A checkpoint is saved after every super-step.

Nodes can call :func:`interrupt` to pause for human input; the run returns with status
``"interrupted"`` and continues later via :meth:`CompiledGraph.resume`. If a node fails
after its retries, previously completed nodes are compensated in reverse order (saga).
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from agentcore.graph.checkpoint import Checkpoint, Checkpointer, MemoryCheckpointer
from agentcore.obs.tracing import get_tracer

START = "__start__"
END = "__end__"

State = dict[str, Any]
NodeFn = Callable[[State], Any]
Reducer = Callable[[Any, Any], Any]


# --- reducers ---------------------------------------------------------------------------


def replace(old: Any, new: Any) -> Any:
    return new


def append(old: Any, new: Any) -> list[Any]:
    """Concatenate lists (a non-list ``new`` value is appended as one item)."""
    base = list(old or [])
    return base + (list(new) if isinstance(new, (list, tuple)) else [new])


def merge(old: Any, new: Any) -> dict[str, Any]:
    return {**(old or {}), **(new or {})}


def add(old: Any, new: Any) -> Any:
    return (old or 0) + new


# --- interrupts -----------------------------------------------------------------------


class GraphInterrupt(Exception):
    def __init__(self, node: str, payload: Any):
        super().__init__(f"interrupt in node {node!r}")
        self.node = node
        self.payload = payload


class WorkflowError(RuntimeError):
    pass


@dataclass
class _NodeContext:
    node: str
    resume: list[Any]
    calls: int = 0


_node_ctx: contextvars.ContextVar[_NodeContext | None] = contextvars.ContextVar(
    "agentcore_graph_node", default=None
)


def interrupt(payload: Any = None) -> Any:
    """Pause the graph and ask for human input.

    On first execution this raises (the run returns ``status="interrupted"`` with
    ``payload``). When the run is resumed with a value, the node re-executes and this call
    returns that value instead.
    """
    ctx = _node_ctx.get()
    if ctx is None:
        raise RuntimeError("interrupt() can only be called inside a graph node")
    idx = ctx.calls
    ctx.calls += 1
    if idx < len(ctx.resume):
        return ctx.resume[idx]
    raise GraphInterrupt(ctx.node, payload)


# --- graph definition ------------------------------------------------------------------


@dataclass
class NodeSpec:
    name: str
    fn: NodeFn
    retries: int = 0
    retry_delay: float = 0.0
    timeout: float | None = None
    compensate: NodeFn | None = None
    fallback: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConditionalEdge:
    source: str
    router: Callable[[State], Any]
    path_map: dict[Any, str] | None = None


class StateGraph:
    def __init__(self, name: str = "workflow", reducers: dict[str, Reducer] | None = None):
        self.name = name
        self.reducers: dict[str, Reducer] = dict(reducers or {})
        self.nodes: dict[str, NodeSpec] = {}
        self.edges: list[tuple[str, str]] = []
        self.joins: list[tuple[tuple[str, ...], str]] = []
        self.conditional: list[ConditionalEdge] = []

    def add_node(
        self,
        name: str | NodeFn,
        fn: NodeFn | None = None,
        *,
        retries: int = 0,
        retry_delay: float = 0.0,
        timeout: float | None = None,
        compensate: NodeFn | None = None,
        fallback: str | None = None,
        **metadata: Any,
    ) -> StateGraph:
        if callable(name) and fn is None:
            fn, name = name, name.__name__
        assert isinstance(name, str) and fn is not None
        if name in (START, END) or name in self.nodes:
            raise ValueError(f"invalid or duplicate node name {name!r}")
        self.nodes[name] = NodeSpec(
            name, fn, retries, retry_delay, timeout, compensate, fallback, metadata
        )
        return self

    def add_edge(self, source: str | Sequence[str], target: str | Sequence[str]) -> StateGraph:
        """``a -> b``; ``a -> [b, c]`` fans out; ``[a, b] -> c`` joins (waits for both)."""
        targets = [target] if isinstance(target, str) else list(target)
        if isinstance(source, str):
            self.edges.extend((source, t) for t in targets)
        else:
            for t in targets:
                self.joins.append((tuple(source), t))
        return self

    def add_conditional_edges(
        self,
        source: str,
        router: Callable[[State], Any],
        path_map: dict[Any, str] | Sequence[str] | None = None,
    ) -> StateGraph:
        """``router(state)`` returns a key (or list of keys) mapped through ``path_map``."""
        if isinstance(path_map, (list, tuple)):
            path_map = {p: p for p in path_map}
        self.conditional.append(ConditionalEdge(source, router, path_map))  # type: ignore[arg-type]
        return self

    def set_entry_point(self, name: str) -> StateGraph:
        return self.add_edge(START, name)

    def set_finish_point(self, name: str) -> StateGraph:
        return self.add_edge(name, END)

    def validate(self) -> None:
        known = set(self.nodes) | {START, END}
        for s, t in self.edges:
            for n in (s, t):
                if n not in known:
                    raise ValueError(f"edge references unknown node {n!r}")
        for sources, t in self.joins:
            for n in (*sources, t):
                if n not in known:
                    raise ValueError(f"join references unknown node {n!r}")
        for ce in self.conditional:
            if ce.source not in known:
                raise ValueError(f"conditional edge from unknown node {ce.source!r}")
            for t in (ce.path_map or {}).values():
                if t not in known:
                    raise ValueError(f"conditional edge targets unknown node {t!r}")
        for spec in self.nodes.values():
            if spec.fallback and spec.fallback not in self.nodes:
                raise ValueError(f"fallback {spec.fallback!r} of {spec.name!r} is not a node")
        if not any(s == START for s, _ in self.edges):
            raise ValueError(
                "graph has no entry point; call set_entry_point() or add_edge(START, ...)"
            )

    def compile(
        self, checkpointer: Checkpointer | None = None, *, max_steps: int = 100
    ) -> CompiledGraph:
        self.validate()
        return CompiledGraph(self, checkpointer or MemoryCheckpointer(), max_steps)

    def to_mermaid(self, highlight: dict[str, str] | None = None) -> str:
        """Render the graph as a Mermaid flowchart. ``highlight`` maps node -> CSS class."""

        def nid(n: str) -> str:
            return {"__start__": "START", "__end__": "END"}.get(
                n, n.replace(" ", "_").replace("-", "_")
            )

        lines = ["flowchart TD", "    START([start])", "    END([end])"]
        for name in self.nodes:
            lines.append(f'    {nid(name)}["{name}"]')
        for s, t in self.edges:
            lines.append(f"    {nid(s)} --> {nid(t)}")
        for sources, t in self.joins:
            lines.append(f"    {' & '.join(nid(s) for s in sources)} --> {nid(t)}")
        for ce in self.conditional:
            targets = ce.path_map or {}
            if not targets:
                lines.append(
                    f"    {nid(ce.source)} -.-> |{ce.router.__name__}| ROUTER_{nid(ce.source)}{{{{?}}}}"
                )
            for key, t in targets.items():
                lines.append(f'    {nid(ce.source)} -.->|"{key}"| {nid(t)}')
        if highlight:
            lines += [
                "    classDef done fill:#d4f7dc,stroke:#2f9e44",
                "    classDef failed fill:#ffe3e3,stroke:#c92a2a",
                "    classDef waiting fill:#fff3bf,stroke:#e67700",
            ]
            lines += [f"    class {nid(n)} {cls}" for n, cls in highlight.items()]
        return "\n".join(lines)


@dataclass
class GraphResult:
    status: str  # completed | interrupted | failed
    state: State
    thread_id: str
    steps: int
    history: list[str]
    interrupts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    failed_node: str | None = None
    compensated: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def interrupted(self) -> bool:
        return self.status == "interrupted"

    @property
    def interrupt(self) -> dict[str, Any] | None:
        return self.interrupts[0] if self.interrupts else None


Callback = Callable[[dict[str, Any]], Any]


class CompiledGraph:
    def __init__(self, graph: StateGraph, checkpointer: Checkpointer, max_steps: int):
        self.graph = graph
        self.checkpointer = checkpointer
        self.max_steps = max_steps

    @property
    def name(self) -> str:
        return self.graph.name

    def to_mermaid(self, highlight: dict[str, str] | None = None) -> str:
        return self.graph.to_mermaid(highlight)

    # public API ------------------------------------------------------------------
    async def run(
        self,
        inputs: State | None = None,
        *,
        thread_id: str | None = None,
        callbacks: list[Callback] | None = None,
    ) -> GraphResult:
        cp = Checkpoint(
            thread_id=thread_id or uuid.uuid4().hex[:12], graph=self.name, state=dict(inputs or {})
        )
        cp.next_nodes = self._successors(START, cp)
        return await self._execute(cp, callbacks or [])

    async def resume(
        self, thread_id: str, value: Any = None, *, callbacks: list[Callback] | None = None
    ) -> GraphResult:
        """Continue an interrupted run. ``value`` answers the pending interrupt.

        If several nodes are interrupted at once, pass ``{node_name: value}``.
        """
        cp = self.checkpointer.get(thread_id)
        if cp is None:
            raise WorkflowError(f"no checkpoint for thread {thread_id!r}")
        if cp.status != "interrupted":
            raise WorkflowError(f"thread {thread_id!r} is {cp.status}, not interrupted")
        pending = [i["node"] for i in cp.interrupts]
        if len(pending) > 1 and isinstance(value, dict) and set(value) <= set(pending):
            answers = value
        else:
            answers = {n: value for n in pending}
        for node, v in answers.items():
            cp.resume_values.setdefault(node, []).append(v)
        cp.status, cp.interrupts = "running", []
        return await self._execute(cp, callbacks or [])

    def run_sync(self, inputs: State | None = None, **kwargs: Any) -> GraphResult:
        return asyncio.run(self.run(inputs, **kwargs))

    def resume_sync(self, thread_id: str, value: Any = None, **kwargs: Any) -> GraphResult:
        return asyncio.run(self.resume(thread_id, value, **kwargs))

    def get_state(self, thread_id: str) -> Checkpoint | None:
        return self.checkpointer.get(thread_id)

    def as_node(
        self, input_keys: Sequence[str] | None = None, output_keys: Sequence[str] | None = None
    ) -> Callable[[State], Awaitable[State]]:
        """Use this compiled graph as a node inside another graph (a subgraph)."""

        async def subgraph_node(state: State) -> State:
            inputs = {k: state[k] for k in input_keys if k in state} if input_keys else dict(state)
            result = await self.run(inputs)
            if result.status != "completed":
                raise WorkflowError(f"subgraph {self.name!r} {result.status}: {result.error or ''}")
            out = result.state
            return {k: out[k] for k in output_keys if k in out} if output_keys else out

        subgraph_node.__name__ = f"subgraph_{self.name}"
        return subgraph_node

    # internals -----------------------------------------------------------------------
    def _successors(self, node: str, cp: Checkpoint) -> list[str]:
        g = self.graph
        out: list[str] = [t for s, t in g.edges if s == node]
        for ce in g.conditional:
            if ce.source != node:
                continue
            choice = ce.router(cp.state)
            keys = choice if isinstance(choice, (list, tuple, set)) else [choice]
            for key in keys:
                target = ce.path_map[key] if ce.path_map is not None else key
                if target != END and target not in g.nodes:
                    raise WorkflowError(f"router of {node!r} returned unknown target {target!r}")
                out.append(target)
        for sources, target in g.joins:
            if node in sources:
                key = f"{'|'.join(sources)}->{target}"
                done = cp.join_progress.setdefault(key, [])
                if node not in done:
                    done.append(node)
                if set(done) >= set(sources):
                    out.append(target)
                    cp.join_progress[key] = []
        return [t for t in dict.fromkeys(out) if t != END]

    def _apply(self, state: State, update: Any, node: str) -> None:
        if update is None:
            return
        if not isinstance(update, dict):
            raise WorkflowError(
                f"node {node!r} must return a dict of state updates or None, got {type(update).__name__}"
            )
        for key, value in update.items():
            reducer = self.graph.reducers.get(key, replace)
            state[key] = reducer(state.get(key), value)

    async def _call(self, spec: NodeSpec, state: State, resume: list[Any]) -> Any:
        ctx = _NodeContext(spec.name, resume)
        token = _node_ctx.set(ctx)
        try:
            res = spec.fn(dict(state))
            if inspect.isawaitable(res):
                res = await (asyncio.wait_for(res, spec.timeout) if spec.timeout else res)
            return res
        finally:
            _node_ctx.reset(token)

    async def _run_node(
        self, name: str, cp: Checkpoint, callbacks: list[Callback]
    ) -> tuple[str, Any]:
        spec = self.graph.nodes[name]
        await _notify(callbacks, {"type": "node_start", "node": name, "step": cp.step})
        attempt = 0
        with get_tracer().span(
            f"graph.node:{name}", {"node": name, "graph": self.name, "step": cp.step}
        ) as span:
            while True:
                attempt += 1
                try:
                    update = await self._call(spec, cp.state, cp.resume_values.get(name, []))
                    if update is not None and not isinstance(update, dict):
                        raise WorkflowError(
                            f"node {name!r} must return a dict of state updates or None, got {type(update).__name__}"
                        )
                    span.set_attribute("attempts", attempt)
                    await _notify(
                        callbacks,
                        {"type": "node_end", "node": name, "update": update, "step": cp.step},
                    )
                    return "ok", update
                except GraphInterrupt as gi:
                    span.add_event("interrupt", {"payload": gi.payload})
                    await _notify(
                        callbacks, {"type": "interrupt", "node": name, "payload": gi.payload}
                    )
                    return "interrupt", gi.payload
                except Exception as exc:
                    if attempt <= spec.retries:
                        span.add_event("retry", {"attempt": attempt, "error": str(exc)})
                        if spec.retry_delay:
                            await asyncio.sleep(spec.retry_delay * (2 ** (attempt - 1)))
                        continue
                    span.record_error(exc)
                    await _notify(
                        callbacks, {"type": "node_error", "node": name, "error": str(exc)}
                    )
                    return "error", exc

    async def _compensate(self, cp: Checkpoint, callbacks: list[Callback]) -> list[str]:
        done: list[str] = []
        for name in reversed(cp.history):
            spec = self.graph.nodes.get(name)
            if spec is None or spec.compensate is None or name in done:
                continue
            try:
                res = spec.compensate(dict(cp.state))
                if inspect.isawaitable(res):
                    res = await res
                if isinstance(res, dict):
                    self._apply(cp.state, res, name)
                done.append(name)
                await _notify(callbacks, {"type": "compensated", "node": name})
            except Exception as exc:  # keep compensating the rest (partial compensation)
                await _notify(
                    callbacks, {"type": "compensation_error", "node": name, "error": str(exc)}
                )
        return done

    async def _execute(self, cp: Checkpoint, callbacks: list[Callback]) -> GraphResult:
        start = time.perf_counter()
        with get_tracer().span(
            f"graph.run:{self.name}", {"graph": self.name, "thread_id": cp.thread_id}
        ) as span:
            result = await self._supersteps(cp, callbacks)
            span.set_attributes({"status": result.status, "steps": result.steps})
            if result.status == "failed":
                span.record_error(result.error or "failed")
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    def _result(self, cp: Checkpoint, **kw: Any) -> GraphResult:
        return GraphResult(
            cp.status,
            cp.state,
            cp.thread_id,
            cp.step,
            list(cp.history),
            list(cp.interrupts),
            cp.error,
            **kw,
        )

    async def _supersteps(self, cp: Checkpoint, callbacks: list[Callback]) -> GraphResult:
        while cp.next_nodes:
            if cp.step >= self.max_steps:
                cp.status, cp.error = (
                    "failed",
                    f"max_steps ({self.max_steps}) exceeded - possible infinite loop",
                )
                self.checkpointer.put(cp)
                return self._result(cp)
            cp.step += 1
            batch = list(dict.fromkeys(cp.next_nodes))
            outcomes = await asyncio.gather(*(self._run_node(n, cp, callbacks) for n in batch))

            interrupted: list[str] = []
            failed: list[tuple[str, BaseException]] = []
            completed: list[str] = []
            for name, (kind, value) in zip(batch, outcomes):
                if kind == "ok":
                    self._apply(cp.state, value, name)
                    cp.resume_values.pop(name, None)
                    completed.append(name)
                elif kind == "interrupt":
                    interrupted.append(name)
                    cp.interrupts.append({"node": name, "payload": value})
                else:
                    failed.append((name, value))

            next_nodes: list[str] = []
            for name in completed:
                cp.history.append(name)
                next_nodes.extend(self._successors(name, cp))

            unrecovered: list[tuple[str, BaseException]] = []
            for name, exc in failed:
                spec = self.graph.nodes[name]
                if spec.fallback:  # route to the fallback node instead of failing
                    cp.state["errors"] = {
                        **cp.state.get("errors", {}),
                        name: f"{type(exc).__name__}: {exc}",
                    }
                    next_nodes.append(spec.fallback)
                else:
                    unrecovered.append((name, exc))
            failed = unrecovered
            if failed:
                name, exc = failed[0]
                cp.status = "failed"
                cp.error = f"node {name!r} failed: {type(exc).__name__}: {exc}"
                compensated = await self._compensate(cp, callbacks)
                cp.next_nodes = []
                self.checkpointer.put(cp)
                return self._result(cp, failed_node=name, compensated=compensated)

            cp.next_nodes = list(dict.fromkeys(interrupted + next_nodes))
            if interrupted:
                cp.status = "interrupted"
                self.checkpointer.put(cp)
                return self._result(cp)
            self.checkpointer.put(cp)

        cp.status = "completed"
        self.checkpointer.put(cp)
        return self._result(cp)


async def _notify(callbacks: list[Callback], event: dict[str, Any]) -> None:
    for cb in callbacks:
        res = cb(event)
        if inspect.isawaitable(res):
            await res
