"""The ``agentcore`` command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import runpy
import sys
from datetime import datetime
from pathlib import Path

from agentcore import __version__
from agentcore.config import Config, ConfigError, load_config, load_tool_modules, resolve_tools

TRACE_DIR = os.environ.get("AGENTCORE_TRACE_DIR", ".agentcore/traces")
DEFAULT_CHAT_TOOLS = ["calculator", "current_time"]


def _cfg(args: argparse.Namespace) -> Config:
    cfg = getattr(args, "cfg", None)
    return cfg if cfg is not None else Config()


def _trace_dir(args: argparse.Namespace) -> str:
    return getattr(args, "trace_dir", None) or _cfg(args).trace_dir


def _custom_tools(cfg: Config) -> dict:
    return load_tool_modules(cfg.tool_modules) if cfg.tool_modules else {}


def _tool_names(flag: str | None, cfg: Config, custom: dict) -> list[str]:
    if flag is not None:
        return [t for t in flag.split(",") if t.strip()]
    if cfg.tools is not None:
        return list(cfg.tools)
    return [*DEFAULT_CHAT_TOOLS, *[n for n in custom if n not in DEFAULT_CHAT_TOOLS]]


def _setup_stdout() -> None:
    # Windows consoles default to a legacy code page; never crash on unicode output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


# --- run ----------------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    script = Path(args.script)
    if not script.exists():
        print(f"error: {script} not found", file=sys.stderr)
        return 2
    sys.argv = [str(script), *args.script_args]
    sys.path.insert(0, str(script.parent.resolve()))
    runpy.run_path(str(script), run_name="__main__")
    return 0


# --- chat ---------------------------------------------------------------------------------


def cmd_chat(args: argparse.Namespace) -> int:
    from agentcore.obs.tracing import configure_tracing
    from agentcore.runtime import Agent, AgentEvent, SlidingWindowMemory, create_model

    cfg = _cfg(args)
    configure_tracing(_trace_dir(args))
    model = create_model(args.model or cfg.model, verbose=True)
    custom = _custom_tools(cfg)
    tools = resolve_tools(
        _tool_names(args.tools, cfg, custom),
        workspace=args.workspace or cfg.workspace,
        extra=custom,
    )
    agent = Agent(
        model,
        tools=tools,
        system_prompt=args.system or cfg.system_prompt,
        memory=SlidingWindowMemory(args.memory_turns),
        max_steps=args.max_steps,
        stream=args.stream,
        name="chat",
    )

    def show(ev: AgentEvent) -> None:
        if ev.type == "token":
            print(ev.data["content"], end="", flush=True)
        elif ev.type == "tool_start" and args.verbose:
            print(f"  -> {ev.data['name']}({json.dumps(ev.data['arguments'])})", file=sys.stderr)
        elif ev.type == "tool_end" and args.verbose:
            print(f"  <- {ev.data['output'][:300]}", file=sys.stderr)

    agent.on(show)

    async def ask(q: str) -> None:
        result = await agent.run(q)
        if args.stream:
            print()
        else:
            print(result.output)
        if args.verbose:
            print(
                f"  [{result.stop_reason}, {result.steps} steps, {result.usage.total_tokens} tokens]",
                file=sys.stderr,
            )

    if args.prompt:
        asyncio.run(ask(args.prompt))
        return 0
    print(
        f"agentcore chat ({model.model_id}; tools: {', '.join(agent.tools.names) or 'none'}). Ctrl-D or 'exit' to quit."
    )
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if q.lower() in ("exit", "quit", ":q"):
            return 0
        if q:
            print("agent> ", end="", flush=True)
            asyncio.run(ask(q))


# --- eval ---------------------------------------------------------------------------------


def cmd_eval(args: argparse.Namespace) -> int:
    from agentcore.eval import EvalRunner, compare, load_report, load_suite
    from agentcore.runtime.providers import create_model

    cfg = _cfg(args)
    suite = load_suite(args.suite)
    if args.tags:
        suite = suite.filter(tags=args.tags.split(","))
    judge = create_model(args.judge_model) if args.judge_model else None
    runner = EvalRunner(
        args.model or (None if suite.agent.model else cfg.model),
        tools=_custom_tools(cfg),
        judge=judge,
        record_to=args.record,
        replay_from=args.replay,
        strict_replay=args.strict_replay,
        concurrency=args.concurrency,
    )
    report = runner.run_suite_sync(suite)
    print(report.to_text())
    if args.output:
        report.save(args.output)
        print(f"results written to {args.output}")
    if args.markdown:
        Path(args.markdown).write_text(report.to_markdown(), encoding="utf-8")
    if args.record:
        print(f"cassette recorded to {args.record}")
    exit_code = 0
    if args.baseline and Path(args.baseline).exists() and not args.save_baseline:
        diff = compare(load_report(args.baseline), report, threshold=args.threshold)
        print(diff.to_markdown())
        if diff.has_regressions:
            exit_code = 1
    if args.save_baseline:
        target = args.baseline or "eval-baseline.json"
        report.save(target)
        print(f"baseline saved to {target}")
    if report.summary()["pass_rate"] < args.fail_under:
        exit_code = 1
    return exit_code


# --- traces -------------------------------------------------------------------------------


def cmd_traces(args: argparse.Namespace) -> int:
    from agentcore.obs.storage import JSONLTraceStore, render_tree

    trace_dir = args.dir or _cfg(args).trace_dir
    store = JSONLTraceStore(trace_dir)
    if args.traces_cmd == "list":
        items = store.list(args.limit)
        if not items:
            print(f"no traces in {trace_dir}")
            return 0
        print(f"{'trace id':<34} {'started':<19} {'ms':>8} {'spans':>5} {'tokens':>7}  name")
        for s in items:
            started = datetime.fromtimestamp(s.start_time).strftime("%Y-%m-%d %H:%M:%S")
            flag = "" if s.status == "ok" else " [error]"
            print(
                f"{s.trace_id:<34} {started:<19} {s.duration_ms:>8.1f} {s.span_count:>5} {s.total_tokens:>7}  {s.name}{flag}"
            )
        return 0
    trace_id = store.resolve(args.trace_id)
    if trace_id is None:
        print(
            f"trace {args.trace_id!r} not found (or ambiguous prefix) in {trace_dir}",
            file=sys.stderr,
        )
        return 1
    spans = store.load(trace_id)
    if args.json:
        print(json.dumps([s.to_dict() for s in spans], indent=2))
    else:
        print(f"trace {trace_id}")
        print(render_tree(spans))
    return 0


# --- serve --------------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "the server needs the 'server' extra: pip install 'agentcore[server]'", file=sys.stderr
        )
        return 2
    from agentcore.server.app import create_app

    cfg = _cfg(args)
    try:
        app = create_app(
            model=args.model,
            tools=[t for t in args.tools.split(",") if t] if args.tools else None,
            trace_dir=args.trace_dir,
            config=cfg,
            cors_origins=args.cors_origins.split(",") if args.cors_origins else None,
            mock_stream_delay=0.02,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    host = args.host or cfg.server.host
    port = args.port or cfg.server.port
    auth = "API key required" if cfg.server.api_key else "open: set AGENTCORE_API_KEY to protect it"
    print(
        f"AgentCore {__version__} web app + API on http://{host}:{port} ({auth})", file=sys.stderr
    )
    if host not in ("127.0.0.1", "localhost", "::1") and not cfg.server.api_key:
        print(
            "warning: listening on a non-loopback address without AGENTCORE_API_KEY",
            file=sys.stderr,
        )
    uvicorn.run(app, host=host, port=port, log_level=args.log_level)
    return 0


# --- research -----------------------------------------------------------------------------


def cmd_research(args: argparse.Namespace) -> int:
    from agentcore.obs.tracing import configure_tracing
    from agentcore.research import research

    if not args.docs and not args.web:
        print("error: pass --docs DIR (local corpus) and/or --web", file=sys.stderr)
        return 2
    configure_tracing(_trace_dir(args))
    arts = asyncio.run(
        research(
            args.topic,
            model=args.model or _cfg(args).model,
            docs=args.docs,
            web=args.web,
            out=args.out,
            max_steps=args.max_steps,
        )
    )
    print(Path(arts.report_path).read_text(encoding="utf-8"))
    print(
        f"wrote {arts.report_path}, {arts.trace_path}, {arts.cost_path} ({arts.sources} sources)",
        file=sys.stderr,
    )
    return 0 if arts.success else 1


# --- tools --------------------------------------------------------------------------------


def cmd_tools(args: argparse.Namespace) -> int:
    from agentcore.tools.builtins import builtin_tools

    custom = _custom_tools(_cfg(args))
    builtin = builtin_tools(workspace=args.workspace)
    names = {t.name for t in builtin}
    for t in [*builtin, *(t for n, t in custom.items() if n not in names)]:
        origin = " (custom)" if t.name not in names else ""
        print(f"{t.name} [{t.category}]{origin} - {t.description}")
        if args.schema:
            print(json.dumps(t.parameters, indent=2))
    return 0


# --- init / doctor ------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    from agentcore.scaffold import scaffold

    try:
        written = scaffold(args.directory, name=args.name, force=args.force)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    root = Path(args.directory)
    print(f"Created an AgentCore project in {root}:")
    for path in written:
        print(f"  {path.relative_to(root).as_posix()}")
    print("\nTry it (offline, no model server needed):")
    if str(args.directory) not in (".", ""):
        print(f"  cd {args.directory}")
    print("  python agent.py --model mock")
    print("  agentcore eval --suite evals/basic.yaml --model mock")
    print("  agentcore serve --model mock")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from agentcore.doctor import Check, format_checks, run_checks

    error = getattr(args, "cfg_error", None)
    checks = run_checks(
        None if error else args.cfg, model=args.model, ping=args.ping, timeout=args.timeout
    )
    if error:
        checks.insert(0, Check("fail", "config error", error))
    print(f"agentcore doctor ({__version__})")
    print(format_checks(checks))
    failed = [c for c in checks if c.status == "fail"]
    warned = [c for c in checks if c.status == "warn"]
    print(f"\n{len(failed)} failed, {len(warned)} warnings")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentcore", description="AgentCore: a from-scratch agentic AI platform"
    )
    p.add_argument("--version", action="version", version=f"agentcore {__version__}")
    p.add_argument(
        "--config",
        default=None,
        help="path to agentcore.toml (default: ./agentcore.toml if present)",
    )
    sub = p.add_subparsers(dest="command", required=True)
    model_help = "mock | auto | ollama:<model> | openai:<model> (default: $AGENTCORE_MODEL or auto)"

    r = sub.add_parser("run", help="run a Python script (e.g. an example) with the given arguments")
    r.add_argument("script")
    r.add_argument("script_args", nargs=argparse.REMAINDER)
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser(
        "chat", help="chat with a tool-using agent (interactive, or one-shot with -p)"
    )
    c.add_argument("--model", default=None, help=model_help)
    c.add_argument(
        "--tools",
        default=None,
        help="comma-separated tools ('' for none; default: config or calculator,current_time)",
    )
    c.add_argument("--system", default=None, help="system prompt")
    c.add_argument("-p", "--prompt", default=None, help="ask one question and exit")
    c.add_argument("--stream", action="store_true")
    c.add_argument("--max-steps", type=int, default=8)
    c.add_argument("--memory-turns", type=int, default=6)
    c.add_argument("--workspace", default=None, help="directory for file tools")
    c.add_argument("--trace-dir", default=None)
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(fn=cmd_chat)

    e = sub.add_parser("eval", help="run an eval suite (YAML/JSON)")
    e.add_argument("--suite", required=True)
    e.add_argument("--model", default=None, help=model_help + "; overrides the suite's model")
    e.add_argument("--judge-model", default=None, help="enable LLM-as-judge with this model")
    e.add_argument("--output", default=None, help="write the JSON report here")
    e.add_argument("--markdown", default=None, help="write a markdown report here")
    e.add_argument(
        "--baseline",
        default=None,
        help="compare against (or with --save-baseline, write) this JSON",
    )
    e.add_argument("--save-baseline", action="store_true")
    e.add_argument(
        "--threshold", type=float, default=0.05, help="score drop that counts as a regression"
    )
    e.add_argument("--record", default=None, help="record model responses to a cassette file")
    e.add_argument(
        "--replay",
        default=None,
        help="replay model responses from a cassette (offline, deterministic)",
    )
    e.add_argument("--strict-replay", action="store_true")
    e.add_argument("--tags", default=None, help="only run cases with these comma-separated tags")
    e.add_argument("--concurrency", type=int, default=4)
    e.add_argument(
        "--fail-under", type=float, default=1.0, help="exit 1 if the pass rate is below this"
    )
    e.set_defaults(fn=cmd_eval)

    t = sub.add_parser("traces", help="inspect locally stored traces")
    t.add_argument("--dir", default=None, help="trace directory (default: config or env)")
    tsub = t.add_subparsers(dest="traces_cmd", required=True)
    tl = tsub.add_parser("list")
    tl.add_argument("--limit", type=int, default=20)
    ts = tsub.add_parser("show")
    ts.add_argument("trace_id", help="trace id or unique prefix")
    ts.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_traces)

    s = sub.add_parser("serve", help="start the web app + HTTP API (needs the 'server' extra)")
    s.add_argument("--host", default=None, help="default: config or 127.0.0.1")
    s.add_argument("--port", type=int, default=None, help="default: config or 8000")
    s.add_argument("--model", default=None, help=model_help)
    s.add_argument(
        "--tools",
        default=None,
        help="comma-separated tools to enable (default: config or calculator,current_time)",
    )
    s.add_argument("--trace-dir", default=None)
    s.add_argument(
        "--cors-origins", default=None, help="comma-separated allowed CORS origins (default: none)"
    )
    s.add_argument("--log-level", default="info")
    s.set_defaults(fn=cmd_serve)

    rs = sub.add_parser("research", help="research a topic and write a cited report")
    rs.add_argument("topic")
    rs.add_argument("--docs", default=None, help="local corpus (file or directory)")
    rs.add_argument("--web", action="store_true", help="also search the web (DuckDuckGo)")
    rs.add_argument("--model", default=None, help=model_help)
    rs.add_argument("--out", default="report.md")
    rs.add_argument("--max-steps", type=int, default=8)
    rs.add_argument("--trace-dir", default=None)
    rs.set_defaults(fn=cmd_research)

    tl2 = sub.add_parser("tools", help="list built-in tools")
    tl2.add_argument("--schema", action="store_true", help="print JSON schemas")
    tl2.add_argument("--workspace", default="workspace")
    tl2.set_defaults(fn=cmd_tools)

    it = sub.add_parser(
        "init", help="scaffold a new agent project (runs offline with --model mock)"
    )
    it.add_argument("directory", nargs="?", default=".")
    it.add_argument("--name", default=None, help="project name (default: directory name)")
    it.add_argument("--force", action="store_true", help="overwrite existing files")
    it.set_defaults(fn=cmd_init, no_config=True)

    dr = sub.add_parser("doctor", help="check the environment, config and model reachability")
    dr.add_argument("--model", default=None, help=model_help)
    dr.add_argument("--ping", action="store_true", help="also send one tiny request to the model")
    dr.add_argument("--timeout", type=float, default=3.0)
    dr.set_defaults(fn=cmd_doctor, tolerate_config_errors=True)
    return p


def main(argv: list[str] | None = None) -> int:
    _setup_stdout()
    args = build_parser().parse_args(argv)
    args.cfg = None
    if not getattr(args, "no_config", False):
        try:
            args.cfg = load_config(args.config)
        except ConfigError as exc:
            if not getattr(args, "tolerate_config_errors", False):
                print(f"error: {exc}", file=sys.stderr)
                return 2
            args.cfg_error = str(exc)
    try:
        return int(args.fn(args) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
