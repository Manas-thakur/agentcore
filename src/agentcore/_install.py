"""Install instructions shown by the CLI, ``doctor``, the server and generated projects.

AgentCore is installed from GitHub. The ``agentcore`` name on PyPI belongs to a different,
unrelated project, so ``pip install agentcore`` must never be suggested.
"""

from __future__ import annotations

REPO_URL = "https://github.com/Manas-thakur/agentcore"
PYPI_NOTE = (
    "AgentCore is not published on PyPI; the 'agentcore' package there is a different project"
)


def install_command(extra: str | None = "server", *, ref: str | None = None) -> str:
    """``pip install "agentcore[extra] @ git+https://github.com/..."`` (optionally ``@ref``)."""
    package = f"agentcore[{extra}]" if extra else "agentcore"
    url = f"git+{REPO_URL}" + (f"@{ref}" if ref else "")
    return f'pip install "{package} @ {url}"'


def install_hint(extra: str | None = "server") -> str:
    """One-line hint for a missing extra, e.g. in error messages."""
    return f"{install_command(extra)} ({PYPI_NOTE})"
