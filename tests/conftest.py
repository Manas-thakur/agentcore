from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentcore.obs.metrics import get_metrics
from agentcore.obs.tracing import InMemoryExporter, Tracer, set_tracer

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


@pytest.fixture(autouse=True)
def _isolated_tracer():
    """Every test gets a fresh in-memory tracer (nothing is written to disk)."""
    exporter = InMemoryExporter()
    set_tracer(Tracer([exporter]))
    get_metrics().reset()
    yield exporter
    set_tracer(Tracer())


@pytest.fixture
def spans(_isolated_tracer: InMemoryExporter) -> InMemoryExporter:
    return _isolated_tracer


def run(coro):
    return asyncio.run(coro)
