"""``python_exec``: run Python code in the subprocess sandbox."""

from __future__ import annotations

from agentcore.tools.decorator import Tool, tool
from agentcore.tools.sandbox import SandboxConfig, SubprocessSandbox


def make_python_exec(config: SandboxConfig | None = None) -> Tool:
    sandbox = SubprocessSandbox(config)

    @tool(category="code", timeout=(sandbox.config.timeout_seconds + 5))
    async def python_exec(code: str) -> str:
        """Execute Python 3 code in an isolated subprocess and return stdout/stderr.

        Use print() to produce output. Network access is disabled.

        Args:
            code: The complete Python program to run.
        """
        result = await sandbox.arun(code)
        return result.summary()

    return python_exec


python_exec = make_python_exec()
