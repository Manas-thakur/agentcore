"""``agentcore doctor``: check the environment, configuration and model reachability."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import platform
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from agentcore import __version__
from agentcore._install import install_command
from agentcore.config import Config, ConfigError, load_tool_modules, resolve_tools


@dataclass
class Check:
    status: str  # ok | warn | fail | info
    name: str
    detail: str = ""


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # parent package missing (dotted names)
        return False


def _mask(value: str) -> str:
    return "set" if not value else f"set ({value[:3]}...{value[-2:]})" if len(value) > 8 else "set"


def run_checks(
    cfg: Config | None, *, model: str | None = None, ping: bool = False, timeout: float = 3.0
) -> list[Check]:
    from agentcore.runtime.providers import DEFAULT_OLLAMA_MODEL, create_model
    from agentcore.runtime.providers.ollama import ollama_host

    checks: list[Check] = []
    py = platform.python_version()
    checks.append(
        Check("ok" if sys.version_info >= (3, 10) else "fail", "python", f"{py} ({sys.executable})")
    )
    checks.append(Check("info", "agentcore", __version__))

    if cfg is None:
        checks.append(Check("fail", "config", "agentcore.toml could not be loaded"))
        cfg = Config()
    elif cfg.path:
        checks.append(Check("ok", "config", cfg.path))
    else:
        checks.append(Check("info", "config", "no agentcore.toml here (defaults + env vars)"))

    for extra, modules in (
        ("server", ["fastapi", "uvicorn"]),
        ("pydantic", ["pydantic"]),
        ("otel", ["opentelemetry.trace", "opentelemetry.sdk"]),
    ):
        missing = [m for m in modules if not _has(m)]
        if missing:
            status = "warn" if extra == "server" else "info"
            state = (
                "not installed"
                if len(missing) == len(modules)
                else f"incomplete, missing {', '.join(missing)}"
            )
            checks.append(Check(status, f"extra [{extra}]", f"{state} ({install_command(extra)})"))
        else:
            checks.append(Check("ok", f"extra [{extra}]", "installed"))
    checks.append(
        Check(
            "info",
            "tokenizer",
            "tiktoken" if _has("tiktoken") else "heuristic token counting (tiktoken not installed)",
        )
    )

    # writable check without creating anything: probe the nearest existing ancestor
    trace_dir = Path(cfg.trace_dir)
    probe = trace_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        with tempfile.NamedTemporaryFile(dir=probe, prefix=".agentcore-doctor-", delete=True):
            pass
        where = "exists" if trace_dir.exists() else f"will be created under {probe}"
        checks.append(Check("ok", "trace dir", f"{trace_dir} ({where}, writable)"))
    except OSError as exc:
        checks.append(Check("fail", "trace dir", f"{trace_dir}: {exc}"))

    custom: dict = {}
    if cfg.tool_modules:
        try:
            custom = load_tool_modules(cfg.tool_modules)
            checks.append(
                Check("ok", "tool modules", f"{len(custom)} tools: {', '.join(sorted(custom))}")
            )
        except ConfigError as exc:
            checks.append(Check("fail", "tool modules", str(exc)))
    if cfg.tools:
        try:
            resolve_tools(cfg.tools, workspace=cfg.workspace, extra=custom)
            checks.append(Check("ok", "tools", ", ".join(cfg.tools)))
        except KeyError as exc:
            checks.append(Check("fail", "tools", str(exc).strip('"')))

    evals = [d for d in cfg.eval_dirs if Path(d).is_dir()]
    checks.append(
        Check(
            "ok" if evals else "info",
            "eval dirs",
            ", ".join(evals) if evals else f"none of {cfg.eval_dirs} exist",
        )
    )

    # --- models -----------------------------------------------------------------------
    host = ollama_host()
    ollama_models: list[str] | None = None
    try:
        resp = httpx.get(f"{host}/api/tags", timeout=timeout)
        resp.raise_for_status()
        ollama_models = [m.get("name", "") for m in resp.json().get("models", [])]
        checks.append(
            Check("ok", "ollama", f"{host} reachable, {len(ollama_models)} models pulled")
        )
    except Exception as exc:
        checks.append(Check("info", "ollama", f"{host} not reachable ({type(exc).__name__})"))

    spec = (model or cfg.model or os.environ.get("AGENTCORE_MODEL") or "auto").strip()
    provider, _, name = spec.partition(":")
    if spec == "auto":
        want = os.environ.get("AGENTCORE_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        if ollama_models is not None and (
            want in ollama_models or f"{want}:latest" in ollama_models
        ):
            checks.append(Check("ok", "model", f"auto -> ollama:{want}"))
        else:
            checks.append(
                Check("warn", "model", f"auto -> mock (ollama model {want!r} not available)")
            )
    elif provider in ("mock", "offline"):
        checks.append(Check("ok", "model", "mock (offline, deterministic)"))
    elif provider == "ollama":
        target = name or DEFAULT_OLLAMA_MODEL
        if ollama_models is None:
            checks.append(Check("fail", "model", f"{spec}: Ollama is not reachable at {host}"))
        elif target in ollama_models or f"{target}:latest" in ollama_models:
            checks.append(Check("ok", "model", f"{spec} is pulled"))
        else:
            checks.append(Check("fail", "model", f"{spec} not pulled; run: ollama pull {target}"))
    elif provider in ("openai", "vllm", "lmstudio", "groq", "openai-compatible"):
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        key = os.environ.get("OPENAI_API_KEY", "")
        checks.append(
            Check("ok" if key else "warn", "OPENAI_API_KEY", _mask(key) if key else "not set")
        )
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            resp = httpx.get(f"{base}/models", headers=headers, timeout=timeout)
            if resp.status_code in (401, 403):
                checks.append(
                    Check("fail", "model", f"{base} rejected the API key (HTTP {resp.status_code})")
                )
            elif resp.status_code >= 400:
                checks.append(
                    Check("warn", "model", f"{base}/models returned HTTP {resp.status_code}")
                )
            else:
                ids = {m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict)}
                found = not ids or name in ids
                checks.append(
                    Check(
                        "ok" if found else "warn",
                        "model",
                        f"{base} reachable" + ("" if found else f"; {name!r} not in /models"),
                    )
                )
        except Exception as exc:
            checks.append(
                Check("fail", "model", f"{base} not reachable ({type(exc).__name__}: {exc})")
            )
    else:
        checks.append(Check("fail", "model", f"unknown model spec {spec!r}"))

    if ping:
        try:
            from agentcore.types import Message

            client = create_model(spec)

            async def _ping() -> str:
                resp = await client.generate(
                    [Message.user("Reply with the single word: OK")], max_tokens=8
                )
                return resp.content.strip()

            reply = asyncio.run(_ping())
            checks.append(Check("ok", "ping", f"{client.model_id} replied {reply[:40]!r}"))
        except Exception as exc:
            checks.append(Check("fail", "ping", f"{type(exc).__name__}: {exc}"))

    key = os.environ.get("AGENTCORE_API_KEY", "")
    checks.append(
        Check(
            "info", "server auth", "AGENTCORE_API_KEY " + ("set" if key else "not set (open API)")
        )
    )
    return checks


def format_checks(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    return "\n".join(f"  {c.status:<4}  {c.name:<{width}}  {c.detail}" for c in checks)
