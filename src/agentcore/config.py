"""Project configuration: ``agentcore.toml`` + environment variables + CLI flags.

Precedence (highest first): command-line flags > environment variables > ``agentcore.toml``
> built-in defaults. Relative paths in the file are resolved against the file's directory.

Example ``agentcore.toml``::

    model = "mock"                        # default model spec
    models = ["ollama:qwen2.5:7b"]        # extra entries for the web UI model picker
    tools = ["calculator", "lookup_fact"] # tools enabled for chat / serve
    tool_modules = ["agent.py"]           # python files/modules that define @tool functions
    trace_dir = ".agentcore/traces"
    eval_dirs = ["evals"]

    [server]
    host = "127.0.0.1"
    port = 8000
    cors_origins = ["http://localhost:5173"]
    max_body_kb = 1024
"""

from __future__ import annotations

import difflib
import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):  # pragma: no cover - depends on interpreter
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

CONFIG_FILENAME = "agentcore.toml"
DEFAULT_TRACE_DIR = ".agentcore/traces"
DEFAULT_EVAL_DIRS = ["evals", "examples/evals"]
DEFAULT_SERVER_TOOLS = ["calculator", "current_time"]


class ConfigError(ValueError):
    """Raised for an unreadable or invalid configuration file."""


class UnknownToolError(ConfigError, KeyError):
    """A tool name that is neither a built-in nor defined in a tool module.

    Subclasses ``KeyError`` for backwards compatibility with code that caught it before.
    """

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


@dataclass
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str | None = None
    cors_origins: list[str] = field(default_factory=list)
    max_body_bytes: int = 1024 * 1024

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "auth_enabled": bool(self.api_key),
            "cors_origins": list(self.cors_origins),
            "max_body_bytes": self.max_body_bytes,
        }


@dataclass
class Config:
    model: str | None = None
    models: list[str] = field(default_factory=list)
    tools: list[str] | None = None
    tool_modules: list[str] = field(default_factory=list)
    trace_dir: str = DEFAULT_TRACE_DIR
    data_dir: str | None = None
    workspace: str = "workspace"
    eval_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_EVAL_DIRS))
    system_prompt: str | None = None
    server: ServerSettings = field(default_factory=ServerSettings)
    path: str | None = None

    @property
    def state_dir(self) -> str:
        """Where sessions and eval history live (default: the trace dir's parent)."""
        return self.data_dir or str(Path(self.trace_dir).parent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_file": self.path,
            "model": self.model,
            "models": list(self.models),
            "tools": self.tools,
            "tool_modules": list(self.tool_modules),
            "trace_dir": self.trace_dir,
            "state_dir": self.state_dir,
            "workspace": self.workspace,
            "eval_dirs": list(self.eval_dirs),
            "server": self.server.to_dict(),
        }


SERVER_KEYS = ("host", "port", "cors_origins", "max_body_kb")


def _int_value(value: Any, key: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key!r} must be an integer, got {value!r}")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"between {minimum} and {maximum}" if maximum is not None else f">= {minimum}"
        raise ConfigError(f"{key!r} must be {bound}, got {value}")
    return value


def _str_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise ConfigError(f"{key!r} must be a list of strings")


def find_config(start: str | os.PathLike[str] | None = None) -> Path | None:
    """Return ``agentcore.toml`` in ``start`` (default: the current directory), if present."""
    candidate = Path(start or Path.cwd()) / CONFIG_FILENAME
    return candidate if candidate.is_file() else None


def load_config(path: str | os.PathLike[str] | None = None, *, env: bool = True) -> Config:
    """Load configuration. ``path=None`` looks for ``./agentcore.toml`` (optional)."""
    cfg = Config()
    file = Path(path) if path else find_config()
    if path and not Path(path).is_file():
        raise ConfigError(f"config file not found: {path}")
    if file is not None:
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read {file}: {exc}") from exc
        _apply_file(cfg, data, file.resolve().parent)
        cfg.path = str(file)
    if env:
        apply_env(cfg)
    return cfg


def _resolve(base: Path, value: str) -> str:
    p = Path(value)
    return str(p if p.is_absolute() else base / p)


def _apply_file(cfg: Config, data: dict[str, Any], base: Path) -> None:
    section = data.get("agentcore", data)
    if not isinstance(section, dict):
        raise ConfigError("[agentcore] must be a table")
    known = {
        "model",
        "models",
        "tools",
        "tool_modules",
        "trace_dir",
        "data_dir",
        "workspace",
        "eval_dirs",
        "system_prompt",
        "server",
        "agentcore",
    }
    unknown = sorted(set(section) - known)
    if unknown:
        raise ConfigError(f"unknown config keys: {unknown}")
    if "model" in section:
        cfg.model = str(section["model"])
    cfg.models = _str_list(section.get("models"), "models")
    if "tools" in section:
        cfg.tools = _str_list(section["tools"], "tools")
    cfg.tool_modules = [
        m if not m.endswith(".py") else _resolve(base, m)
        for m in _str_list(section.get("tool_modules"), "tool_modules")
    ]
    if "trace_dir" in section:
        cfg.trace_dir = _resolve(base, str(section["trace_dir"]))
    else:
        cfg.trace_dir = _resolve(base, DEFAULT_TRACE_DIR)
    if "data_dir" in section:
        cfg.data_dir = _resolve(base, str(section["data_dir"]))
    if "workspace" in section:
        cfg.workspace = _resolve(base, str(section["workspace"]))
    if "eval_dirs" in section:
        cfg.eval_dirs = [_resolve(base, d) for d in _str_list(section["eval_dirs"], "eval_dirs")]
    else:
        cfg.eval_dirs = [_resolve(base, d) for d in DEFAULT_EVAL_DIRS]
    if section.get("system_prompt"):
        cfg.system_prompt = str(section["system_prompt"])
    server = data.get("server", section.get("server")) or {}
    if not isinstance(server, dict):
        raise ConfigError("[server] must be a table")
    if "api_key" in server:
        raise ConfigError(
            "do not put secrets in agentcore.toml; set the AGENTCORE_API_KEY environment variable"
        )
    unknown_server = sorted(set(server) - set(SERVER_KEYS))
    if unknown_server:
        hints = []
        for k in unknown_server:
            close = difflib.get_close_matches(k, SERVER_KEYS, n=1)
            hints.append(f"{k!r}" + (f" (did you mean {close[0]!r}?)" if close else ""))
        raise ConfigError(
            f"unknown [server] keys: {', '.join(hints)}; allowed: {', '.join(SERVER_KEYS)}"
        )
    s = cfg.server
    s.host = str(server.get("host", s.host))
    s.port = _int_value(server.get("port", s.port), "server.port", 1, 65535)
    s.cors_origins = _str_list(server.get("cors_origins"), "server.cors_origins")
    if "max_body_kb" in server:
        s.max_body_bytes = _int_value(server["max_body_kb"], "server.max_body_kb", 1) * 1024


def apply_env(cfg: Config) -> None:
    e = os.environ
    if e.get("AGENTCORE_MODEL"):
        cfg.model = e["AGENTCORE_MODEL"]
    if e.get("AGENTCORE_TRACE_DIR"):
        cfg.trace_dir = e["AGENTCORE_TRACE_DIR"]
    if e.get("AGENTCORE_DATA_DIR"):
        cfg.data_dir = e["AGENTCORE_DATA_DIR"]
    if e.get("AGENTCORE_TOOLS"):
        cfg.tools = _str_list(e["AGENTCORE_TOOLS"], "AGENTCORE_TOOLS")
    if e.get("AGENTCORE_EVAL_DIRS"):
        cfg.eval_dirs = _str_list(e["AGENTCORE_EVAL_DIRS"], "AGENTCORE_EVAL_DIRS")
    if e.get("AGENTCORE_API_KEY"):
        cfg.server.api_key = e["AGENTCORE_API_KEY"]
    if e.get("AGENTCORE_CORS_ORIGINS"):
        cfg.server.cors_origins = _str_list(e["AGENTCORE_CORS_ORIGINS"], "AGENTCORE_CORS_ORIGINS")
    if e.get("AGENTCORE_MAX_BODY_KB"):
        cfg.server.max_body_bytes = int(e["AGENTCORE_MAX_BODY_KB"]) * 1024


# --- custom tools ---------------------------------------------------------------------------


def load_tool_modules(specs: list[str]) -> dict[str, Any]:
    """Import python files / modules and collect the ``@tool`` objects they define.

    A spec is a path to a ``.py`` file or a dotted module name. If the module defines a
    ``TOOLS`` list, only those are used; otherwise every module-level ``Tool`` is collected.
    """
    from agentcore.tools.decorator import Tool

    found: dict[str, Any] = {}
    for spec in specs:
        if spec.endswith(".py"):
            path = Path(spec)
            if not path.is_file():
                raise ConfigError(f"tool module not found: {spec}")
            mod_name = f"agentcore_user_{path.stem}_{abs(hash(str(path.resolve()))) % 10**8}"
            module = sys.modules.get(mod_name)
            if module is None:
                loader_spec = importlib.util.spec_from_file_location(mod_name, path)
                if loader_spec is None or loader_spec.loader is None:
                    raise ConfigError(f"cannot import {spec}")
                module = importlib.util.module_from_spec(loader_spec)
                sys.modules[mod_name] = module
                parent = str(path.resolve().parent)
                if parent not in sys.path:
                    sys.path.insert(0, parent)
                try:
                    loader_spec.loader.exec_module(module)
                except Exception as exc:
                    sys.modules.pop(mod_name, None)
                    raise ConfigError(
                        f"error importing {spec}: {type(exc).__name__}: {exc}"
                    ) from exc
        else:
            try:
                module = importlib.import_module(spec)
            except ImportError as exc:
                raise ConfigError(f"cannot import tool module {spec!r}: {exc}") from exc
        explicit = getattr(module, "TOOLS", None)
        candidates = list(explicit) if explicit is not None else list(vars(module).values())
        for obj in candidates:
            if isinstance(obj, Tool):
                found[obj.name] = obj
    return found


def resolve_tools(
    names: list[str] | None, *, workspace: str = "workspace", extra: dict[str, Any] | None = None
) -> list[Any]:
    """Resolve tool names against custom tools first, then the built-ins."""
    from agentcore.tools.builtins import BUILTIN_NAMES, builtin_tools

    extra = extra or {}
    out = []
    for name in names or []:
        if name in extra:
            out.append(extra[name])
        elif name in BUILTIN_NAMES:
            out.extend(builtin_tools([name], workspace=workspace))
        else:
            available = sorted(set(BUILTIN_NAMES) | set(extra))
            raise UnknownToolError(f"unknown tool {name!r}; available: {available}")
    return out
