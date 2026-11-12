from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass
from typing import Literal

import httpx
import pytest

from agentcore.tools import (
    ExecutionEngine,
    RetryPolicy,
    SandboxConfig,
    SubprocessSandbox,
    TokenBucket,
    ToolRegistry,
    ToolTransientError,
    ToolValidationError,
    builtin_tools,
    calculator,
    file_tools,
    parse_docstring,
    tool,
)
from agentcore.tools.builtins import safe_eval
from agentcore.tools.builtins.web import html_to_text, make_http_get, parse_ddg_html
from tests.conftest import run


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


@dataclass
class Point:
    """A 2-D point.

    Args:
        x: horizontal position
        y: vertical position
    """

    x: float
    y: float = 0.0


def test_schema_from_type_hints_and_google_docstring():
    @tool
    def search(
        query: str,
        limit: int = 5,
        tags: list[str] | None = None,
        mode: Literal["fast", "deep"] = "fast",
    ):
        """Search things.

        Args:
            query: What to look for.
            limit: Max results.
        """

    p = search.parameters
    assert search.name == "search"
    assert search.description == "Search things."
    assert p["required"] == ["query"]
    assert p["properties"]["query"] == {"type": "string", "description": "What to look for."}
    assert p["properties"]["limit"]["default"] == 5
    assert p["properties"]["tags"]["anyOf"][0] == {"type": "array", "items": {"type": "string"}}
    assert p["properties"]["mode"]["enum"] == ["fast", "deep"]
    assert search.to_openai()["function"]["name"] == "search"


def test_schema_dataclass_enum_and_numpy_docstring():
    @tool(name="paint")
    def paint_point(point: Point, color: Color, opacity: float | None = None) -> str:
        """Paint a point.

        Parameters
        ----------
        point : Point
            Where to paint.
        color : Color
            Which color.
        """
        return f"{point.x},{point.y}:{color.value}"

    props = paint_point.parameters["properties"]
    assert props["point"]["type"] == "object"
    assert props["point"]["required"] == ["x"]
    assert props["point"]["properties"]["x"]["description"] == "horizontal position"
    assert props["color"] == {
        "enum": ["red", "blue"],
        "type": "string",
        "description": "Which color.",
    }
    assert props["point"]["description"] == "Where to paint."
    # validation converts JSON -> dataclass / Enum
    kwargs = paint_point.validate({"point": {"x": "1.5"}, "color": "blue"})
    assert kwargs["point"] == Point(1.5, 0.0)
    assert kwargs["color"] is Color.BLUE
    assert paint_point(**kwargs) == "1.5,0.0:blue"


try:
    import pydantic

    class Address(pydantic.BaseModel):
        city: str
        zip_code: str | None = None

    class User(pydantic.BaseModel):
        name: str
        address: Address

except ImportError:  # pragma: no cover - pydantic is an optional extra
    pydantic = None


@pytest.mark.skipif(pydantic is None, reason="pydantic not installed")
def test_schema_pydantic_model():
    @tool
    def save_user(user: User) -> str:
        """Save a user."""
        return user.address.city

    schema = save_user.parameters["properties"]["user"]
    assert "$defs" not in schema
    assert schema["properties"]["address"]["properties"]["city"]["type"] == "string"
    kwargs = save_user.validate({"user": {"name": "a", "address": {"city": "Pune"}}})
    assert save_user(**kwargs) == "Pune"


def test_sphinx_docstring():
    summary, params = parse_docstring(
        "Do it.\n\n:param x: the x value\n:param int y: the y value\n"
    )
    assert summary == "Do it."
    assert params == {"x": "the x value", "y": "the y value"}


def test_validation_coerces_and_reports_errors():
    @tool
    def f(n: int, flag: bool, items: list[int]) -> int:
        return n

    assert f.validate({"n": "3", "flag": "true", "items": "[1, 2]"}) == {
        "n": 3,
        "flag": True,
        "items": [1, 2],
    }
    with pytest.raises(ToolValidationError) as exc:
        f.validate({"n": "abc", "items": [1]})
    assert any("missing required" in e for e in exc.value.errors)
    assert any("expected integer" in e for e in exc.value.errors)
    # unknown keys are dropped unless strict
    assert "extra" not in f.validate({"n": 1, "flag": False, "items": [], "extra": 1})


def test_registry_basics():
    reg = ToolRegistry([calculator])
    assert "calculator" in reg and len(reg) == 1
    with pytest.raises(ValueError):
        reg.register(calculator)
    assert reg.subset(["calculator"]).names == ["calculator"]
    assert reg.to_openai()[0]["type"] == "function"


def test_calculator_is_safe_and_correct():
    assert calculator(expression="17 * 23 + 4") == "395"
    assert calculator(expression="2 ^ 10") == "1024"
    assert calculator(expression="sqrt(16) + pi * 0") == "4"
    assert float(safe_eval("22/7")) == pytest.approx(3.142857, rel=1e-5)
    for bad in ["__import__('os')", "open('x')", "().__class__", "a + 1", "2 ** 100000"]:
        with pytest.raises(ValueError):
            safe_eval(bad)


def test_execution_engine_success_validation_and_not_found():
    engine = ExecutionEngine(ToolRegistry([calculator]))
    ok = run(engine.execute("calculator", {"expression": "1 + 1"}, call_id="c1"))
    assert ok.success and ok.output == "2" and ok.call_id == "c1"
    bad = run(engine.execute("calculator", {}))
    assert not bad.success and bad.error_type == "ToolValidationError"
    missing = run(engine.execute("nope", {}))
    assert not missing.success and missing.error_type == "ToolNotFoundError"
    err = run(engine.execute("calculator", {"expression": "1/0"}))
    assert not err.success and "ZeroDivisionError" in err.error
    assert err.as_text().startswith("ERROR")


def test_execution_engine_timeout_and_retries():
    calls = {"n": 0}

    @tool(timeout=0.05)
    async def slow() -> str:
        """Sleeps."""
        await asyncio.sleep(1)
        return "done"

    @tool(retries=2)
    def flaky() -> str:
        """Fails twice."""
        calls["n"] += 1
        if calls["n"] < 3:
            raise ToolTransientError("try again")
        return "ok"

    engine = ExecutionEngine(
        ToolRegistry([slow, flaky]), retry_policy=RetryPolicy(max_retries=0, base_delay_s=0.001)
    )
    t0 = time.perf_counter()
    res = run(engine.execute("slow"))
    assert not res.success and res.error_type == "ToolTimeoutError"
    assert time.perf_counter() - t0 < 0.9
    res = run(engine.execute("flaky"))
    assert res.success and res.output == "ok" and res.attempts == 3


def test_rate_limit_and_hooks():
    seen = []
    engine = ExecutionEngine(
        ToolRegistry([calculator]),
        rate_limits={"calculator": TokenBucket(1, per=60)},
        retry_policy=RetryPolicy(max_retries=0),
        after=[lambda r: seen.append(r.success)],
    )
    first = run(engine.execute("calculator", {"expression": "1"}))
    second = run(engine.execute("calculator", {"expression": "1"}))
    assert first.success and not second.success and second.error_type == "ToolRateLimitError"
    assert seen == [True, False]


def test_file_tools_block_path_traversal(tmp_path):
    read_file, write_file, list_files = file_tools(tmp_path / "ws")
    assert "wrote" in write_file(path="notes/a.txt", content="hello")
    assert read_file(path="notes/a.txt") == "hello"
    assert list_files() == ["notes/a.txt"]
    engine = ExecutionEngine(ToolRegistry([read_file]))
    res = run(engine.execute("read_file", {"path": "../../etc/passwd"}))
    assert not res.success and res.error_type == "ToolSandboxViolation"


def test_sandbox_runs_code_and_enforces_limits():
    sb = SubprocessSandbox(SandboxConfig(timeout_seconds=10))
    r = sb.run("print(sum(range(10)))")
    assert r.ok and r.stdout.strip() == "45"
    r = sb.run("import socket\nsocket.create_connection(('example.com', 80))")
    assert not r.ok and "network access is disabled" in r.stderr
    r = SubprocessSandbox(SandboxConfig(allowed_imports=["math"])).run("import math\nimport os")
    assert not r.ok and "not allowed" in r.stderr
    r = SubprocessSandbox(SandboxConfig(timeout_seconds=1)).run("while True: pass")
    assert r.timed_out and "TIMEOUT" in r.summary()


def test_python_exec_tool():
    (py,) = builtin_tools(["python_exec"])
    engine = ExecutionEngine(ToolRegistry([py]))
    res = run(engine.execute("python_exec", {"code": "print(6 * 7)"}))
    assert res.success and res.output.strip() == "42"


def test_html_and_search_parsing():
    title, text = html_to_text(
        "<html><head><title>T</title><script>x=1</script></head><body><p>Hello</p><p>World</p></body></html>"
    )
    assert title == "T" and "Hello" in text and "x=1" not in text
    markup = (
        '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">A <b>title</b></a>'
        '<a class="result__snippet" href="x">Some <b>snippet</b></a>'
    )
    assert parse_ddg_html(markup) == [
        {"title": "A title", "url": "https://example.com/a", "snippet": "Some snippet"}
    ]


def test_http_get_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/err":
            return httpx.Response(404)
        return httpx.Response(200, html="<title>Doc</title><p>body text</p>")

    http_get = make_http_get(httpx.Client(transport=httpx.MockTransport(handler)))
    assert "body text" in http_get(url="https://x.test/page")
    engine = ExecutionEngine(ToolRegistry([http_get]))
    res = run(engine.execute("http_get", {"url": "https://x.test/err"}))
    assert not res.success and "404" in res.error
    res = run(engine.execute("http_get", {"url": "file:///etc/passwd"}))
    assert not res.success
