"""Built-in tool library."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agentcore.tools.builtins.calculator import calculator, safe_eval
from agentcore.tools.builtins.files import file_tools, resolve_in_workspace
from agentcore.tools.builtins.python_exec import make_python_exec, python_exec
from agentcore.tools.builtins.web import (
    html_to_text,
    http_get,
    make_http_get,
    make_web_search,
    web_search,
)
from agentcore.tools.decorator import Tool, tool


@tool(category="utilities")
def current_time() -> str:
    """Return the current UTC date and time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


BUILTIN_NAMES = [
    "calculator",
    "current_time",
    "python_exec",
    "http_get",
    "web_search",
    "read_file",
    "write_file",
    "list_files",
]


def builtin_tools(
    names: list[str] | None = None, workspace: str | Path = "workspace"
) -> list[Tool]:
    """Return built-in tools by name (all of them if ``names`` is None).

    File tools are bound to ``workspace`` (created on demand).
    """
    wanted = names or BUILTIN_NAMES
    table: dict[str, Tool] = {
        "calculator": calculator,
        "current_time": current_time,
        "python_exec": python_exec,
        "http_get": http_get,
        "web_search": web_search,
    }
    if any(n in wanted for n in ("read_file", "write_file", "list_files")):
        for t in file_tools(workspace):
            table[t.name] = t
    unknown = [n for n in wanted if n not in table]
    if unknown:
        raise KeyError(f"unknown built-in tools: {unknown}; available: {BUILTIN_NAMES}")
    return [table[n] for n in wanted]


__all__ = [
    "BUILTIN_NAMES",
    "builtin_tools",
    "calculator",
    "current_time",
    "file_tools",
    "html_to_text",
    "http_get",
    "make_http_get",
    "make_python_exec",
    "make_web_search",
    "python_exec",
    "resolve_in_workspace",
    "safe_eval",
    "web_search",
]
