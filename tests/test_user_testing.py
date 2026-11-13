"""Regressions found by using AgentCore hands-on as a new developer."""

from __future__ import annotations

import pytest

from agentcore import Agent, tool
from agentcore.runtime.providers.mock import MockModel, find_math_expression
from agentcore.tools import calculator


def test_dates_times_and_versions_are_not_arithmetic():
    assert find_math_expression("days between 2026-01-01 and 2026-11-13") is None
    assert find_math_expression("meet at 10:30") is None
    assert find_math_expression("upgrade to 0.3.0") is None
    assert find_math_expression("on 12/03/2026 what is 5-2") == "5-2"
    assert find_math_expression("What is 17 * 23 + 4?") == "17 * 23 + 4"
    assert find_math_expression("what is 10/2") == "10/2"


@tool
def lookup_fact(query: str) -> str:
    """Look up a fact.

    Args:
        query: What to look up.
    """
    return "299,792,458 metres per second" if "light" in query.lower() else "unknown"


def test_mock_prefers_lookup_tool_when_asked_to_look_something_up():
    agent = Agent(MockModel(), tools=[calculator, lookup_fact], max_steps=4)
    result = agent.run_sync(
        "Look up the speed of light, then tell me how many days are between "
        "2026-01-01 and 2026-11-13."
    )
    assert "299,792,458" in result.output
    assert "invalid expression" not in result.output


def test_reexported_builtin_tool_is_not_labelled_custom(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agentcore.config import Config
    from agentcore.server.app import create_app

    module = tmp_path / "mytools.py"
    module.write_text(
        "from agentcore import tool\n"
        "from agentcore.tools import calculator\n\n"
        "@tool\n"
        "def shout(text: str) -> str:\n"
        '    """Upper-case text.\n\n    Args:\n        text: Text.\n    """\n'
        "    return text.upper()\n\n"
        "TOOLS = [calculator, shout]\n",
        encoding="utf-8",
    )
    app = create_app(
        model="mock",
        trace_dir=str(tmp_path / "traces"),
        tools=["calculator", "shout"],
        config=Config(tool_modules=[str(module)]),
    )
    with TestClient(app) as client:
        sources = {t["name"]: t["source"] for t in client.get("/api/tools").json()}
    assert sources == {"calculator": "builtin", "shout": "custom"}
