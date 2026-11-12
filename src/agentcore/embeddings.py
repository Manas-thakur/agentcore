"""Text embedders.

``HashingEmbedder`` is a deterministic, dependency-free embedder (feature hashing of word
unigrams/bigrams and character trigrams, TF-weighted, L2-normalised). It is not a neural
model, but it captures lexical similarity well enough for offline demos and tests. Use
``OllamaEmbedder`` (e.g. ``nomic-embed-text``) or ``OpenAIEmbedder`` for real semantics.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from abc import ABC, abstractmethod

import httpx
import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(ABC):
    dimension: int

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return a float32 array of shape ``(len(texts), dimension)``."""

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    async def aembed(self, texts: list[str]) -> np.ndarray:
        return await asyncio.to_thread(self.embed, texts)


def _stable_hash(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "little")


class HashingEmbedder(Embedder):
    def __init__(self, dimension: int = 384, char_ngrams: bool = True):
        self.dimension = dimension
        self.char_ngrams = char_ngrams

    def _features(self, text: str) -> list[tuple[str, float]]:
        words = _TOKEN_RE.findall(text.lower())
        feats = [(f"w:{w}", 1.0) for w in words]
        feats += [(f"b:{a}_{b}", 0.7) for a, b in zip(words, words[1:])]
        if self.char_ngrams:
            for w in words:
                padded = f"#{w}#"
                feats += [(f"c:{padded[i : i + 3]}", 0.3) for i in range(len(padded) - 2)]
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for feat, weight in self._features(text):
                h = _stable_hash(feat)
                sign = 1.0 if (h >> 63) & 1 else -1.0
                out[row, h % self.dimension] += sign * weight
            # sublinear TF damping then L2 normalisation
            out[row] = np.sign(out[row]) * np.log1p(np.abs(out[row]))
            norm = np.linalg.norm(out[row])
            if norm > 0:
                out[row] /= norm
        return out


class OllamaEmbedder(Embedder):
    def __init__(
        self, model: str = "nomic-embed-text", host: str | None = None, dimension: int | None = None
    ):
        from agentcore.runtime.providers.ollama import ollama_host

        self.model = model
        self.host = (host or ollama_host()).rstrip("/")
        self.dimension = dimension or 0

    def embed(self, texts: list[str]) -> np.ndarray:
        resp = httpx.post(
            f"{self.host}/api/embed", json={"model": self.model, "input": texts}, timeout=120
        )
        resp.raise_for_status()
        arr = np.asarray(resp.json()["embeddings"], dtype=np.float32)
        self.dimension = arr.shape[1]
        return arr


class OpenAIEmbedder(Embedder):
    def __init__(
        self,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
        api_key: str | None = None,
        dimension: int | None = None,
    ):
        self.model = model
        self.base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.dimension = dimension or 0

    def embed(self, texts: list[str]) -> np.ndarray:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        resp = httpx.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model, "input": texts},
            headers=headers,
            timeout=120,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        arr = np.asarray([d["embedding"] for d in data], dtype=np.float32)
        self.dimension = arr.shape[1]
        return arr


def create_embedder(spec: str | Embedder | None = None) -> Embedder:
    """``hash`` (default), ``ollama:<model>`` or ``openai:<model>``."""
    if isinstance(spec, Embedder):
        return spec
    spec = spec or os.environ.get("AGENTCORE_EMBEDDER", "hash")
    provider, _, name = spec.partition(":")
    if provider == "hash":
        return HashingEmbedder(int(name) if name else 384)
    if provider == "ollama":
        return OllamaEmbedder(name or "nomic-embed-text")
    if provider == "openai":
        return OpenAIEmbedder(name or "text-embedding-3-small")
    raise ValueError(f"unknown embedder spec {spec!r}")
