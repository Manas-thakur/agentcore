"""Subprocess sandbox for running model-generated Python code.

Isolation provided (best effort, defense in depth - NOT a security boundary against a
determined attacker; use a container or VM for untrusted multi-tenant workloads):

* separate interpreter process started with ``-I`` (isolated mode: no user site, no env vars)
* fresh temporary working directory, deleted afterwards
* wall-clock timeout (process is killed)
* CPU-time and address-space limits via ``resource`` on POSIX
* network disabled by replacing ``socket.socket`` (unless ``network_access=True``)
* optional import allow-list
* stdout/stderr size caps
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field


@dataclass
class SandboxConfig:
    timeout_seconds: float = 10.0
    memory_limit_mb: int | None = 512
    cpu_time_seconds: int | None = 10
    network_access: bool = False
    allowed_imports: list[str] | None = None
    max_output_chars: int = 20_000
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def summary(self) -> str:
        if self.timed_out:
            return f"TIMEOUT\n{self.stdout}{self.stderr}".strip()
        parts = []
        if self.stdout:
            parts.append(self.stdout.rstrip())
        if self.stderr:
            parts.append(("STDERR:\n" if self.returncode == 0 else "") + self.stderr.rstrip())
        if self.returncode not in (0, None):
            parts.append(f"(exit code {self.returncode})")
        return "\n".join(parts) if parts else "(no output)"


_BOOTSTRAP = r"""
import builtins, json, sys
_cfg = json.loads(sys.argv[1])
if _cfg.get("mem_mb") or _cfg.get("cpu_s"):
    try:
        import resource
        if _cfg.get("mem_mb"):
            _b = int(_cfg["mem_mb"]) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (_b, _b))
        if _cfg.get("cpu_s"):
            resource.setrlimit(resource.RLIMIT_CPU, (int(_cfg["cpu_s"]), int(_cfg["cpu_s"])))
    except Exception:
        pass  # not available on this platform (e.g. Windows)
if not _cfg.get("network"):
    import socket as _socket
    class _NoNet(_socket.socket):
        def __init__(self, *a, **k):
            raise PermissionError("network access is disabled in the sandbox")
    _socket.socket = _NoNet
    _socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(
        PermissionError("network access is disabled in the sandbox"))
_allowed = _cfg.get("allowed")
if _allowed is not None:
    _real_import = builtins.__import__
    _always = {"builtins", "sys", "json", "encodings", "codecs", "io", "abc", "_io"}
    def _guarded(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if level == 0 and root not in _allowed and root not in _always and not root.startswith("_"):
            raise ImportError(f"import of {root!r} is not allowed in the sandbox")
        return _real_import(name, globals, locals, fromlist, level)
    builtins.__import__ = _guarded
_code = open(_cfg["path"], encoding="utf-8").read()
_g = {"__name__": "__main__"}
exec(compile(_code, "<sandbox>", "exec"), _g)
"""


class SubprocessSandbox:
    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()

    def run(self, code: str) -> SandboxResult:
        cfg = self.config
        with tempfile.TemporaryDirectory(prefix="agentcore_sandbox_") as workdir:
            path = os.path.join(workdir, "main.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent(code))
            boot = json.dumps(
                {
                    "path": path,
                    "mem_mb": cfg.memory_limit_mb,
                    "cpu_s": cfg.cpu_time_seconds,
                    "network": cfg.network_access,
                    "allowed": cfg.allowed_imports,
                }
            )
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                **({"SYSTEMROOT": os.environ["SYSTEMROOT"]} if "SYSTEMROOT" in os.environ else {}),
                **cfg.env,
            }
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-c", _BOOTSTRAP, boot],
                    cwd=workdir,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=cfg.timeout_seconds,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired as exc:
                return SandboxResult(
                    stdout=_cap(_to_text(exc.stdout), cfg.max_output_chars),
                    stderr=_cap(_to_text(exc.stderr), cfg.max_output_chars),
                    returncode=None,
                    timed_out=True,
                )
            return SandboxResult(
                stdout=_cap(proc.stdout, cfg.max_output_chars),
                stderr=_cap(_clean_traceback(proc.stderr), cfg.max_output_chars),
                returncode=proc.returncode,
            )

    async def arun(self, code: str) -> SandboxResult:
        return await asyncio.to_thread(self.run, code)


def _to_text(data: str | bytes | None) -> str:
    if data is None:
        return ""
    return data.decode("utf-8", "replace") if isinstance(data, bytes) else data


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n...[truncated {len(text) - limit}]"


def _clean_traceback(stderr: str) -> str:
    # Hide the bootstrap frames so the model sees only its own code's traceback.
    lines = [ln for ln in stderr.splitlines() if 'File "<string>"' not in ln]
    return "\n".join(lines) + ("\n" if lines else "")
