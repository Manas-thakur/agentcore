from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agentcore.runtime import (
    Agent,
    BufferMemory,
    ContextManager,
    HybridMemory,
    LongTermMemory,
    MockModel,
    OllamaClient,
    OpenAICompatibleClient,
    ScriptedModel,
    SlidingWindowMemory,
    SummarizingMemory,
    TokenBudget,
    TokenCounter,
    create_model,
)
from agentcore.runtime.providers.mock import extractive_answer, find_math_expression
from agentcore.tools import calculator, tool
from agentcore.types import ChatResponse, Message, ToolCall, Usage
from tests.conftest import run


def call(name: str, **args) -> Message:
    return Message.assistant("", [ToolCall(name, args)])


def test_agent_tool_loop_with_scripted_model():
    model = ScriptedModel([call("calculator", expression="6*7"), "The answer is 42."])
    agent = Agent(model, tools=[calculator])
    result = agent.run_sync("what is 6*7?")
    assert result.output == "The answer is 42."
    assert result.stop_reason == "final" and result.steps == 2
    assert [r.output for r in result.tool_results] == ["42"]
    # the second model call saw the tool result message
    second = model.calls[1]["messages"]
    assert second[-1].role == "tool" and second[-1].content == "42"
    assert second[-2].tool_calls[0].name == "calculator"
    assert model.calls[0]["tools"][0]["function"]["name"] == "calculator"
    assert result.usage.total_tokens > 0


def test_parallel_tool_calls_run_concurrently():
    @tool
    async def wait(seconds: float) -> str:
        """Wait."""
        await asyncio.sleep(seconds)
        return "ok"

    model = ScriptedModel(
        [
            Message.assistant(
                "", [ToolCall("wait", {"seconds": 0.4}), ToolCall("wait", {"seconds": 0.4})]
            ),
            "done",
        ]
    )
    result = Agent(model, tools=[wait]).run_sync("go")
    assert result.output == "done" and len(result.tool_results) == 2
    # the two 0.4 s calls overlapped (sequential would take >= 800 ms)
    assert result.duration_ms < 700


def test_max_steps_and_stuck_detection_reflection():
    model = ScriptedModel([call("calculator", expression="1+1")], on_exhausted="repeat_last")
    agent = Agent(model, tools=[calculator], max_steps=4, stuck_threshold=2)
    result = agent.run_sync("loop forever")
    assert result.stop_reason == "max_steps" and result.steps == 4
    reflections = [e for e in result.events if e.type == "reflection"]
    assert reflections and "same arguments" in reflections[0].data["content"]
    assert any(m.content.startswith("[reflection]") for m in result.messages)


def test_reflection_hook_and_llm_reflection():
    hooks = []
    model = ScriptedModel([call("calculator", expression="2+2"), "Reflecting: on track.", "4"])
    agent = Agent(
        model,
        tools=[calculator],
        reflect_every=1,
        reflection_hook=lambda msgs, step: hooks.append(step) or "remember to be brief",
    )
    result = agent.run_sync("2+2?")
    assert result.output == "4" and hooks == [1]
    notes = [e.data["content"] for e in result.events if e.type == "reflection"]
    assert notes == ["remember to be brief", "Reflecting: on track."]
    # the reflection model call was made without tools
    assert model.calls[1]["tools"] is None


def test_events_stream_and_callbacks():
    seen = []
    agent = Agent(ScriptedModel([call("calculator", expression="3*3"), "9"]), tools=[calculator])
    agent.on(lambda e: seen.append(e.type))

    async def collect():
        return [e.type async for e in agent.stream("3*3")]

    streamed = run(collect())
    expected = [
        "run_start",
        "step_start",
        "model_response",
        "tool_start",
        "tool_end",
        "step_start",
        "model_response",
        "final",
        "run_end",
    ]
    assert streamed == expected and seen == expected


def test_token_streaming_mode():
    tokens = []
    agent = Agent(ScriptedModel(["hello world"]), stream=True)
    agent.on(lambda e: tokens.append(e.data["content"]) if e.type == "token" else None)
    assert agent.run_sync("hi").output == "hello world"
    assert "".join(tokens) == "hello world"


def test_tool_errors_are_fed_back_to_the_model():
    model = ScriptedModel([call("calculator", expression="1/0"), "Division by zero is undefined."])
    result = Agent(model, tools=[calculator]).run_sync("1/0")
    assert not result.tool_results[0].success
    assert model.calls[1]["messages"][-1].content.startswith("ERROR")
    assert result.output == "Division by zero is undefined."


def test_timeout():
    async def slow(messages, tools):
        await asyncio.sleep(2)
        return "late"

    result = Agent(ScriptedModel([slow]), timeout_seconds=0.1).run_sync("hi")
    assert result.stop_reason == "timeout" and "timed out" in result.error


def test_agent_as_tool_delegation():
    worker = Agent(ScriptedModel(["sub-result"]), name="worker")
    boss_model = ScriptedModel([call("worker", task="do it"), "boss says: sub-result"])
    boss = Agent(boss_model, tools=[worker.as_tool()])
    assert boss.run_sync("delegate").output == "boss says: sub-result"
    assert boss_model.calls[1]["messages"][-1].content == "sub-result"


def test_mock_model_policy():
    agent = Agent(MockModel(), tools=[calculator])
    assert agent.run_sync("What is 17 * 23 + 4?").output == "The answer is 395."
    assert find_math_expression("compute (3 + 4) * 5 please") == "(3 + 4) * 5"
    assert find_math_expression("no math here") is None
    plain = Agent(MockModel()).run_sync("hello there")
    assert plain.output.startswith("[mock]")
    assert "offline mock model" in plain.output and "--model" in plain.output
    answer = extractive_answer(
        "what is bm25",
        {
            1: "BM25 is a ranking function used by search engines.",
            2: "Unrelated text about cooking pasta.",
        },
    )
    assert answer.endswith("[1]")


def test_memory_tiers():
    buf = BufferMemory(max_messages=3)
    for i in range(5):
        buf.add(Message.user(f"m{i}"))
    assert [m.content for m in buf.get_messages()] == ["m2", "m3", "m4"]

    win = SlidingWindowMemory(max_turns=2)
    for i in range(3):
        win.add(Message.user(f"q{i}"))
        win.add(Message.assistant(f"a{i}"))
    assert [m.content for m in win.get_messages()] == ["q1", "a1", "q2", "a2"]

    lt = LongTermMemory(min_score=0.1)
    lt.remember("The user's favorite database is PostgreSQL")
    lt.remember("The weather was sunny on Tuesday")
    hits = lt.recall("which database does the user like?")
    assert hits and "PostgreSQL" in hits[0].content
    assert hits[0].importance > 5  # "favorite" is an importance cue
    msgs = lt.get_messages("favorite database")
    assert msgs and msgs[0].role == "system"

    hybrid = HybridMemory(SlidingWindowMemory(1), LongTermMemory(min_score=0.1))
    hybrid.add(Message.user("my name is Ada"))
    hybrid.add(Message.assistant("hi Ada"))
    hybrid.add(Message.user("what's 2+2"))
    out = hybrid.get_messages("what is my name?")
    assert out[0].role == "system" and "Ada" in out[0].content


def test_summarizing_memory_compacts():
    summarizer = ScriptedModel(["- user wants a trip to Goa"])
    mem = SummarizingMemory(summarizer, max_tokens=60, keep_recent=2)
    for i in range(6):
        mem.add(Message.user(f"planning message number {i} with some extra words to use tokens"))
    run(mem.compact())
    msgs = mem.get_messages()
    assert msgs[0].role == "system" and "Goa" in msgs[0].content
    assert len(msgs) == 3 and mem.summarized_count == 4


def test_agent_with_memory_multi_turn(tmp_path):
    model = ScriptedModel(["Nice to meet you, Ada.", "Your name is Ada."])
    agent = Agent(model, memory=SlidingWindowMemory(4))
    agent.run_sync("My name is Ada.")
    agent.run_sync("What is my name?")
    second_call = model.calls[1]["messages"]
    assert [m.content for m in second_call if m.role == "user"] == [
        "My name is Ada.",
        "What is my name?",
    ]
    path = tmp_path / "mem.json"
    agent.memory.save(path)
    restored = SlidingWindowMemory(4)
    restored.load(path)
    assert len(restored.get_messages()) == 4


def test_context_manager_keeps_task_and_tool_pairs():
    counter = TokenCounter()
    cm = ContextManager(
        TokenBudget(context_window=200, reserve_output=50, max_tool_output=30), counter
    )
    msgs = [
        Message.system("sys"),
        Message.user("old question " * 20),
        Message.assistant("old answer " * 20),
    ]
    msgs += [
        Message.user("the task"),
        call("calculator", expression="1+1"),
        Message.tool("x " * 300, "id1", "calculator"),
    ]
    fitted = cm.fit(msgs)
    assert fitted[0].role == "system"
    assert any(m.content == "the task" for m in fitted)
    assert "old question" not in " ".join(m.content for m in fitted)
    tool_msg = [m for m in fitted if m.role == "tool"][0]
    assert "omitted" in tool_msg.content
    assert counter.count_messages(fitted) <= 150


def test_ollama_client_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert (
            body["model"] == "qwen2.5:7b" and body["tools"][0]["function"]["name"] == "calculator"
        )
        if body["stream"]:
            lines = [
                {"message": {"role": "assistant", "content": "Hel"}, "done": False},
                {"message": {"role": "assistant", "content": "lo"}, "done": False},
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "prompt_eval_count": 5,
                    "eval_count": 2,
                },
            ]
            return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines))
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "calculator", "arguments": {"expression": "2+2"}}}
                    ],
                },
                "done": True,
                "prompt_eval_count": 12,
                "eval_count": 3,
            },
        )

    client = OllamaClient(
        "qwen2.5:7b", host="http://ollama.test:11434", transport=httpx.MockTransport(handler)
    )
    tools = [calculator.to_openai()]
    resp = run(client.generate([Message.user("2+2")], tools))
    assert resp.tool_calls[0].name == "calculator" and resp.tool_calls[0].arguments == {
        "expression": "2+2"
    }
    assert resp.usage == Usage(12, 3)
    assert client.model_id == "ollama:qwen2.5:7b"

    async def stream():
        return [ev async for ev in client.stream([Message.user("hi")], tools)]

    events = run(stream())
    assert "".join(e.content for e in events if e.type == "token") == "Hello"
    assert events[-1].type == "done" and events[-1].response.usage.total_tokens == 7


def test_openai_client_with_mock_transport():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        if calls["n"] == 1:
            return httpx.Response(503, text="overloaded")  # retried
        if body.get("stream"):
            chunks = [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {"name": "calculator", "arguments": '{"expr'},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": 'ession": "1+2"}'}}
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
                {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4}},
            ]
            text = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, text=text)
        # tool message must carry tool_call_id; assistant tool calls carry JSON-string arguments
        msgs = body["messages"]
        if any(m["role"] == "tool" for m in msgs):
            assert msgs[-1]["tool_call_id"] == "call_1"
            assert json.loads(msgs[-2]["tool_calls"][0]["function"]["arguments"]) == {
                "expression": "1+2"
            }
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {"message": {"role": "assistant", "content": "3"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 1},
            },
        )

    client = OpenAICompatibleClient(
        "gpt-4o-mini",
        base_url="https://llm.test/v1",
        api_key="sk-test",
        transport=httpx.MockTransport(handler),
    )
    history = [
        Message.user("1+2"),
        Message.assistant("", [ToolCall("calculator", {"expression": "1+2"}, id="call_1")]),
        Message.tool("3", "call_1", "calculator"),
    ]
    resp = run(client.generate(history))
    assert resp.content == "3" and resp.usage.total_tokens == 21 and calls["n"] == 2

    async def stream():
        return [ev async for ev in client.stream([Message.user("1+2")], [calculator.to_openai()])]

    events = run(stream())
    tc = [e for e in events if e.type == "tool_call"][0].tool_call
    assert tc.name == "calculator" and tc.arguments == {"expression": "1+2"} and tc.id == "call_1"
    assert events[-1].response.usage.total_tokens == 13


def test_create_model_specs(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
    assert isinstance(create_model("mock"), MockModel)
    o = create_model("ollama:llama3.1:8b")
    assert isinstance(o, OllamaClient) and o.model == "llama3.1:8b"
    v = create_model("vllm:Qwen/Qwen2.5-7B-Instruct")
    assert isinstance(v, OpenAICompatibleClient) and v.base_url == "http://localhost:1234/v1"
    assert v.model_id == "vllm:Qwen/Qwen2.5-7B-Instruct"
    with pytest.raises(ValueError):
        create_model("unknown:thing")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")  # nothing listens here
    assert isinstance(create_model("auto"), MockModel)


def test_chat_response_roundtrip():
    resp = ChatResponse(
        Message.assistant("x", [ToolCall("t", {"a": 1}, id="call_9")]), Usage(1, 2), "m", 3.0
    )
    again = ChatResponse.from_dict(json.loads(json.dumps(resp.to_dict())))
    assert again.tool_calls[0].id == "call_9" and again.usage.total_tokens == 3
