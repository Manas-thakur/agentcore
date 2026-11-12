"""Deterministic replay: record model responses once, replay them forever.

A *cassette* maps each eval case to the ordered list of model responses it received.
Replaying a cassette makes an agent run bit-for-bit reproducible (no LLM needed), which
lets CI catch regressions in tools, prompts-as-code and agent logic.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from agentcore.runtime.model_client import ModelClient, ModelError, ToolSpecs
from agentcore.types import ChatResponse, Message


def request_fingerprint(messages: list[Message], tools: ToolSpecs | None) -> str:
    payload = json.dumps(
        {
            "messages": [m.to_dict() for m in messages],
            "tools": sorted(t["function"]["name"] for t in tools or []),
        },
        sort_keys=True,
        default=str,
    )
    # tool-call ids are random; strip them from the fingerprint
    payload = re.sub(r'"(id|tool_call_id)": "call_[0-9a-f]+"', '"\\1": "-"', payload)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class RecordingModel(ModelClient):
    """Wraps a real model and records every response (with a request fingerprint)."""

    def __init__(self, inner: ModelClient):
        super().__init__(inner.model)
        self.inner = inner
        self.provider = inner.provider
        self.records: list[dict[str, Any]] = []

    @property
    def model_id(self) -> str:
        return self.inner.model_id

    async def generate(
        self,
        messages: list[Message],
        tools: ToolSpecs | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        resp = await self.inner.generate(
            messages, tools, temperature=temperature, max_tokens=max_tokens
        )
        self.records.append(
            {"fingerprint": request_fingerprint(messages, tools), "response": resp.to_dict()}
        )
        return resp


class ReplayModel(ModelClient):
    """Returns recorded responses in order. ``strict`` also checks request fingerprints."""

    provider = "replay"

    def __init__(
        self, records: list[dict[str, Any]], *, strict: bool = False, model: str = "replay"
    ):
        super().__init__(model)
        self.records = records
        self.strict = strict
        self._i = 0

    async def generate(
        self,
        messages: list[Message],
        tools: ToolSpecs | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        if self._i >= len(self.records):
            raise ModelError(f"replay exhausted: only {len(self.records)} recorded responses")
        rec = self.records[self._i]
        self._i += 1
        if (
            self.strict
            and rec.get("fingerprint")
            and rec["fingerprint"] != request_fingerprint(messages, tools)
        ):
            raise ModelError(
                f"replay mismatch at call {self._i}: the agent sent a different request than was recorded"
            )
        return ChatResponse.from_dict(rec["response"])


class Cassette:
    """``{case_name: [records...]}`` persisted as JSON."""

    def __init__(self, data: dict[str, list[dict[str, Any]]] | None = None, model: str = ""):
        self.data = data or {}
        self.model = model

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps({"model": self.model, "cases": self.data}, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> Cassette:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(raw.get("cases", {}), raw.get("model", ""))

    def model_for(self, case_name: str, strict: bool = False) -> ReplayModel:
        if case_name not in self.data:
            raise KeyError(f"cassette has no recording for case {case_name!r}")
        return ReplayModel(self.data[case_name], strict=strict, model=f"replay:{self.model}")
