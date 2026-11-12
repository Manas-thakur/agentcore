"""Workspace-scoped file tools with path-traversal protection."""

from __future__ import annotations

from pathlib import Path

from agentcore.tools.decorator import Tool, tool
from agentcore.tools.errors import ToolSandboxViolation

MAX_READ_BYTES = 200_000


def resolve_in_workspace(workspace: str | Path, path: str) -> Path:
    """Resolve ``path`` inside ``workspace``; raise if it escapes the workspace."""
    root = Path(workspace).resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ToolSandboxViolation(f"path {path!r} escapes the workspace")
    return target


def file_tools(workspace: str | Path = ".") -> list[Tool]:
    """Create ``read_file``, ``write_file`` and ``list_files`` bound to ``workspace``."""
    root = Path(workspace)  # created lazily by write_file

    @tool(category="filesystem")
    def read_file(path: str, max_bytes: int = MAX_READ_BYTES) -> str:
        """Read a UTF-8 text file from the workspace.

        Args:
            path: Path relative to the workspace root.
            max_bytes: Maximum number of bytes to return.
        """
        target = resolve_in_workspace(root, path)
        if not target.is_file():
            raise FileNotFoundError(f"no such file: {path}")
        data = target.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace")

    @tool(category="filesystem")
    def write_file(path: str, content: str, append: bool = False) -> str:
        """Write text to a file in the workspace (creating parent directories).

        Args:
            path: Path relative to the workspace root.
            content: Text to write.
            append: Append instead of overwriting.
        """
        target = resolve_in_workspace(root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a" if append else "w", encoding="utf-8") as fh:
            fh.write(content)
        return f"wrote {len(content)} chars to {path}"

    @tool(category="filesystem")
    def list_files(path: str = ".") -> list[str]:
        """List files under a workspace directory (recursive, max 500 entries).

        Args:
            path: Directory relative to the workspace root.
        """
        target = resolve_in_workspace(root, path)
        base = root.resolve()
        out = [
            str(p.relative_to(base)).replace("\\", "/")
            for p in sorted(target.rglob("*"))
            if p.is_file()
        ]
        return out[:500]

    return [read_file, write_file, list_files]
