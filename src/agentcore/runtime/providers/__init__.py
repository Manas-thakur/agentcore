"""Model providers and the ``create_model`` factory.

Model spec strings:

* ``mock``                       - offline rule-based model
* ``ollama:<model>``             - e.g. ``ollama:qwen2.5:7b`` (uses ``OLLAMA_HOST``)
* ``openai:<model>``             - e.g. ``openai:gpt-4o-mini`` (``OPENAI_API_KEY``,
  ``OPENAI_BASE_URL`` for vLLM / LM Studio / Groq / any compatible server)
* ``auto``                       - Ollama if reachable with ``AGENTCORE_OLLAMA_MODEL``
  (default ``qwen2.5:7b``) pulled, otherwise ``mock``
"""

from __future__ import annotations

import os
import sys
from typing import Any

from agentcore.runtime.model_client import ModelClient
from agentcore.runtime.providers.mock import MockModel, ScriptedModel
from agentcore.runtime.providers.ollama import OllamaClient, ollama_available
from agentcore.runtime.providers.openai_compat import OpenAICompatibleClient

DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"


def default_model_spec() -> str:
    return os.environ.get("AGENTCORE_MODEL", "auto")


def create_model(
    spec: str | ModelClient | None = None, *, verbose: bool = False, **kwargs: Any
) -> ModelClient:
    """Build a :class:`ModelClient` from a spec string like ``ollama:qwen2.5:7b``."""
    if isinstance(spec, ModelClient):
        return spec
    spec = (spec or default_model_spec()).strip()
    if spec == "auto":
        model = os.environ.get("AGENTCORE_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        if ollama_available(model=model):
            chosen: ModelClient = OllamaClient(model, **kwargs)
        else:
            chosen = MockModel()
        if verbose:
            print(f"[agentcore] model: {chosen.model_id} (auto-detected)", file=sys.stderr)
        return chosen
    provider, _, name = spec.partition(":")
    provider = provider.lower()
    if provider in ("mock", "offline"):
        return MockModel()
    if provider == "ollama":
        return OllamaClient(name or DEFAULT_OLLAMA_MODEL, **kwargs)
    if provider in ("openai", "vllm", "lmstudio", "groq", "openai-compatible"):
        if not name:
            raise ValueError(f"model spec {spec!r} needs a model name, e.g. openai:gpt-4o-mini")
        client = OpenAICompatibleClient(name, **kwargs)
        if provider != "openai":
            client.provider = provider
        return client
    raise ValueError(
        f"unknown model spec {spec!r}; use 'mock', 'auto', 'ollama:<model>' or 'openai:<model>'"
    )


__all__ = [
    "MockModel",
    "OllamaClient",
    "OpenAICompatibleClient",
    "ScriptedModel",
    "create_model",
    "default_model_spec",
    "ollama_available",
]
