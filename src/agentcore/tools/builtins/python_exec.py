"""``python_exec``: run Python code in the subprocess sandbox.

The built-in tool blocks imports of modules that reach the operating system, processes or
the network (:data:`DEFAULT_BLOCKED_IMPORTS`). Pass your own :class:`SandboxConfig` to
:func:`make_python_exec` to change that (``blocked_imports=[]`` lifts the deny-list,
``allowed_imports=[...]`` switches to an allow-list).
"""

from __future__ import annotations

from agentcore.tools.decorator import Tool, tool
from agentcore.tools.errors import ToolTimeoutError
from agentcore.tools.sandbox import SandboxConfig, SubprocessSandbox

DEFAULT_BLOCKED_IMPORTS = [
    "os",
    "posix",
    "nt",
    "subprocess",
    "_posixsubprocess",
    "_winapi",
    "socket",
    "_socket",
    "ssl",
    "shutil",
    "ctypes",
    "_ctypes",
    "multiprocessing",
    "signal",
    "pty",
    "importlib",
]


def make_python_exec(config: SandboxConfig | None = None) -> Tool:
    """Build a ``python_exec`` tool; ``config=None`` blocks :data:`DEFAULT_BLOCKED_IMPORTS`."""
    sandbox = SubprocessSandbox(
        config or SandboxConfig(blocked_imports=list(DEFAULT_BLOCKED_IMPORTS))
    )
    limit = sandbox.config.timeout_seconds

    # retries=0: re-running code that timed out would only time out again
    @tool(category="code", timeout=(limit + 5), retries=0)
    async def python_exec(code: str) -> str:
        """Execute Python 3 code in an isolated subprocess and return stdout/stderr.

        Use print() to produce output. Network access is disabled, and modules such as os,
        subprocess, socket and shutil cannot be imported.

        Args:
            code: The complete Python program to run.
        """
        result = await sandbox.arun(code)
        if result.timed_out:
            partial = (result.stdout + result.stderr).strip()
            raise ToolTimeoutError(
                f"code did not finish within {limit:g}s and was stopped"
                + (f"; output so far:\n{partial[:2000]}" if partial else "")
            )
        return result.summary()

    return python_exec


python_exec = make_python_exec()
