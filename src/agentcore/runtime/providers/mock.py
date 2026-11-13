"""Deterministic offline models for tests, demos and CI.

* :class:`ScriptedModel` replays a fixed list of responses (exact control in unit tests).
* :class:`MockModel` is a small rule-based "policy" that behaves plausibly with tools:
  it calls a calculator for arithmetic, a search tool for questions, ``python_exec`` for
  code blocks, answers RAG prompts extractively with citations, and turns tool results
  into a final answer. It lets every example run with no LLM at all.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from agentcore.runtime.model_client import ModelClient, ModelError, ToolSpecs
from agentcore.types import (
    ChatResponse,
    DoneEvent,
    Message,
    StreamEvent,
    TokenEvent,
    ToolCall,
    ToolCallEvent,
    Usage,
)

ScriptItem = str | Message | ChatResponse | Callable[..., Any]


class ScriptedModel(ModelClient):
    """Returns pre-scripted responses in order.

    Items may be strings (final answers), ``Message``/``ChatResponse`` objects, or
    callables ``(messages, tools) -> str | Message`` for dynamic behaviour.
    """

    provider = "scripted"

    def __init__(
        self,
        responses: list[ScriptItem],
        *,
        model: str = "scripted",
        on_exhausted: str = "error",  # "error" | "repeat_last" | "echo"
    ):
        super().__init__(model)
        self.responses = list(responses)
        self.on_exhausted = on_exhausted
        self.calls: list[dict[str, Any]] = []
        self._index = 0

    async def generate(
        self,
        messages: list[Message],
        tools: ToolSpecs | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        self.calls.append({"messages": list(messages), "tools": tools})
        if self._index >= len(self.responses):
            if self.on_exhausted == "repeat_last" and self.responses:
                item: ScriptItem = self.responses[-1]
            elif self.on_exhausted == "echo":
                item = f"(echo) {messages[-1].content if messages else ''}"
            else:
                raise ModelError(f"ScriptedModel exhausted after {len(self.responses)} responses")
        else:
            item = self.responses[self._index]
            self._index += 1
        if callable(item) and not isinstance(item, (Message, ChatResponse)):
            item = item(messages, tools)
            if inspect.isawaitable(item):
                item = await item
        if isinstance(item, ChatResponse):
            return item
        msg = item if isinstance(item, Message) else Message.assistant(str(item))
        return ChatResponse(
            message=msg,
            usage=Usage(self.count_tokens(messages), self._counter.count(msg.content) + 1),
            model=self.model,
            latency_ms=0.0,
            finish_reason="tool_calls" if msg.tool_calls else "stop",
        )


# --- MockModel -------------------------------------------------------------------

_MATH_RE = re.compile(
    r"(?<![\w.])(?:\(\s*)*-?\d+(?:\.\d+)?(?:\s*\)+)?"
    r"(?:\s*(?:\*\*|//|[-+*/%^×÷])\s*(?:\(\s*)*-?\d+(?:\.\d+)?(?:\s*\)+)?)+"
)
_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)
_STOP = set(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "why",
        "when",
        "where",
        "does",
        "do",
        "did",
        "can",
        "could",
        "should",
        "would",
        "will",
        "with",
        "by",
        "from",
        "as",
        "at",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "about",
        "into",
        "than",
        "then",
        "there",
        "their",
        "them",
        "they",
        "you",
        "your",
        "i",
        "me",
        "my",
        "we",
        "our",
        "please",
        "explain",
        "tell",
        "give",
        "list",
        "describe",
    ]
)


# Number-like tokens that are not arithmetic: ISO / slash dates, clock times and
# version strings ("2026-01-01" is a date, not 2026 minus 1 minus 1).
_NOT_MATH_RE = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?\b"
    r"|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b"
    r"|\bv?\d+\.\d+\.\d+\b"
)
_LOOKUP_INTENT_RE = re.compile(r"\b(look\s*up|lookup|search(?:\s+for)?|find out)\b", re.I)


def find_math_expression(text: str) -> str | None:
    """Return the longest arithmetic expression in ``text`` (e.g. ``"17 * 23 + 4"``)."""
    text = _NOT_MATH_RE.sub(" ", text)
    matches = [m.group(0).strip() for m in _MATH_RE.finditer(text)]
    if not matches:
        return None
    expr = max(matches, key=len)
    # balance parentheses that the regex may have clipped
    expr = expr.lstrip(")").rstrip("(")
    while expr.count("(") > expr.count(")"):
        expr += ")"
    while expr.count(")") > expr.count("(") and expr.endswith(")"):
        expr = expr[:-1]
    return expr.replace("^", "**").replace("×", "*").replace("÷", "/")


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


def _split_sentences(text: str) -> list[str]:
    out = []
    for part in re.split(r"(?<=[.!?])\s+|\n+", text):
        p = part.strip()
        # skip markdown headings and "[section path]" labels added by chunkers
        if len(p) <= 20 or p.startswith("#") or (p.startswith("[") and p.endswith("]")):
            continue
        out.append(p)
    return out


def extractive_answer(question: str, sources: dict[int, str], max_sentences: int = 2) -> str:
    """Pick the sentences that best overlap with the question and cite their sources."""
    q = _keywords(question)
    scored: list[tuple[float, int, int, str]] = []
    for idx, text in sources.items():
        for pos, sent in enumerate(_split_sentences(text)):
            overlap = len(q & _keywords(sent))
            if overlap:
                scored.append((overlap + 0.001 / (pos + 1), idx, pos, sent))
    if not scored:
        return "I could not find the answer in the provided sources."
    scored.sort(key=lambda s: -s[0])
    picked = sorted(scored[:max_sentences], key=lambda s: (s[1], s[2]))
    return " ".join(f"{s[3].rstrip()} [{s[1]}]" for s in picked)


def parse_numbered_sources(text: str) -> dict[int, str]:
    """Parse ``[1] text ... [2] text`` blocks (the format used by the RAG prompt)."""
    sources: dict[int, str] = {}
    pattern = re.compile(r"^\[(\d+)\][^\n]*\n?(.*?)(?=^\[\d+\]|\Z|^Question:)", re.S | re.M)
    for m in pattern.finditer(text):
        header_and_body = m.group(0)
        body = header_and_body.split("\n", 1)[1] if "\n" in header_and_body else header_and_body
        sources[int(m.group(1))] = body.strip()
    return sources


_JUDGE_RE = re.compile(
    r"impartial judge.*?Task given to the assistant:\n(?P<task>.*?)\n\n"
    r"(?:Reference answer:\n(?P<ref>.*?)\n\n)?Assistant's answer:\n(?P<answer>.*?)\n\n"
    r"Score each criterion from 0 to 10:\n(?P<criteria>.*?)\n\nRespond with ONLY",
    re.S,
)


def judge_answer(prompt: str) -> str | None:
    """Answer an LLM-as-judge prompt with valid JSON (deterministic, offline).

    Every criterion gets 10 when the answer contains the reference answer (or there is no
    reference and the answer is non-empty), 2 otherwise.
    """
    m = _JUDGE_RE.search(prompt)
    if m is None:
        return None
    criteria = [
        line[2:].strip() for line in m.group("criteria").splitlines() if line.startswith("- ")
    ]
    answer = " ".join(m.group("answer").lower().split())
    ref = " ".join((m.group("ref") or "").lower().split()).strip(" .")
    if ref:
        ok = ref in answer
        why = "the answer contains the reference" if ok else "the answer lacks the reference"
    else:
        ok = bool(answer) and answer != "(no answer)"
        why = "an answer was given" if ok else "no answer was given"
    score = 10 if ok else 2
    return json.dumps(
        {"scores": dict.fromkeys(criteria, score), "reasoning": f"mock judge: {why}."}
    )


# The runtime's REFLECTION_PROMPT (agentcore.runtime.agent) starts with this.
_REFLECTION_PROMPT_START = "Pause and reflect before continuing."
_NOT_FOUND_RE = re.compile(
    r"^(no\b|none\b|nothing\b|not found\b|unknown\b|could not\b|couldn't\b|unable\b)", re.I
)


def _sentence(text: str) -> str:
    """``text`` with exactly one closing punctuation mark."""
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _reflection(history: list[Message]) -> str:
    calls = [tc.name for m in history if m.role == "assistant" for tc in m.tool_calls]
    if not calls:
        return "No tools have been used yet; answer directly if no tool is needed."
    return (
        f"So far {len(calls)} tool call(s) ran ({', '.join(dict.fromkeys(calls))}). "
        "Their results are available, so the next step is the final answer."
    )


def _tool_names(tools: ToolSpecs | None) -> dict[str, dict[str, Any]]:
    out = {}
    for t in tools or []:
        fn = t.get("function", t)
        out[fn["name"]] = fn.get("parameters", {})
    return out


def _first_string_param(schema: dict[str, Any]) -> str | None:
    props = schema.get("properties", {})
    for name in schema.get("required", []) + list(props):
        if props.get(name, {}).get("type") == "string":
            return name
    return None


class MockModel(ModelClient):
    """Rule-based offline model. Deterministic: same input -> same output."""

    provider = "mock"

    def __init__(self, model: str = "mock", *, latency_ms: float = 0.0, stream_delay: float = 0.0):
        super().__init__(model)
        self.latency_ms = latency_ms
        self.stream_delay = stream_delay  # seconds between streamed chunks (demo realism)

    @property
    def model_id(self) -> str:
        return "mock"

    async def generate(
        self,
        messages: list[Message],
        tools: ToolSpecs | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        start = time.perf_counter()
        msg = self.respond(messages, tools)
        return ChatResponse(
            message=msg,
            usage=Usage(
                self.count_tokens(messages),
                self._counter.count(msg.content) + 3 * len(msg.tool_calls),
            ),
            model="mock",
            latency_ms=self.latency_ms or (time.perf_counter() - start) * 1000,
            finish_reason="tool_calls" if msg.tool_calls else "stop",
        )

    async def stream(
        self,
        messages: list[Message],
        tools: ToolSpecs | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream the deterministic answer word by word (joined chunks == ``generate``)."""
        resp = await self.generate(messages, tools, temperature=temperature, max_tokens=max_tokens)
        for chunk in re.findall(r"\S+\s*|\s+", resp.content):
            if self.stream_delay:
                await asyncio.sleep(self.stream_delay)
            yield TokenEvent(chunk)
        for tc in resp.tool_calls:
            yield ToolCallEvent(tc)
        yield DoneEvent(resp)

    # The policy ---------------------------------------------------------------
    def respond(self, messages: list[Message], tools: ToolSpecs | None) -> Message:
        if (
            messages
            and messages[-1].role == "user"
            and messages[-1].content.startswith(_REFLECTION_PROMPT_START)
        ):
            return Message.assistant(_reflection(messages[:-1]))
        # "[reflection] ..." notes the agent adds between steps are not new tasks.
        last_user = max(
            (
                i
                for i, m in enumerate(messages)
                if m.role == "user" and not m.content.startswith("[reflection]")
            ),
            default=-1,
        )
        task = messages[last_user].content if last_user >= 0 else ""
        observations = [m for m in messages[last_user + 1 :] if m.role == "tool"]
        available = _tool_names(tools)

        judged = judge_answer(task) if "impartial judge" in task else None
        if judged is not None:
            return Message.assistant(judged)

        if observations:
            return Message.assistant(self._final_from_observations(task, observations))

        call = self._choose_tool(task, available)
        if call is not None:
            return Message.assistant("", [call])

        sources = parse_numbered_sources(task)
        if sources:
            question = task.rsplit("Question:", 1)[-1].strip() if "Question:" in task else task
            return Message.assistant(extractive_answer(question, sources))

        expr = find_math_expression(task)
        if expr:
            from agentcore.tools.builtins.calculator import safe_eval

            try:
                return Message.assistant(f"The answer is {safe_eval(expr)}.")
            except (ValueError, ZeroDivisionError, OverflowError):
                pass
        snippet = " ".join(task.split())
        if not snippet:
            return Message.assistant("[mock] Hello!")
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        return Message.assistant(
            f"[mock] I can't answer \"{snippet}\" because I'm the offline mock model: "
            "I only do arithmetic, call simple tools like the calculator, and quote "
            "from sources you give me. For real answers, start AgentCore with a model, "
            "for example `agentcore serve --model ollama:qwen2.5:7b`, or set "
            "`OPENAI_BASE_URL` and use `--model openai:<name>`."
        )

    def _choose_tool(self, task: str, available: dict[str, dict[str, Any]]) -> ToolCall | None:
        if not available or not task.strip():
            return None
        code = _CODE_RE.search(task)
        if code and "python_exec" in available:
            return ToolCall("python_exec", {"code": code.group(1)})
        lookup = next(
            (
                (name, schema)
                for name, schema in available.items()
                if any(k in name.lower() for k in ("search", "retriev", "lookup", "knowledge"))
            ),
            None,
        )
        if lookup and _LOOKUP_INTENT_RE.search(task):
            # "Look up X" asks for the lookup tool even if numbers appear later.
            name, schema = lookup
            return ToolCall(name, {_first_string_param(schema) or "query": task.strip()[:500]})
        expr = find_math_expression(task)
        if expr:
            for name, schema in available.items():
                if "calc" in name.lower():
                    param = _first_string_param(schema) or "expression"
                    return ToolCall(name, {param: expr})
            if "python_exec" in available:
                return ToolCall("python_exec", {"code": f"print({expr})"})
        for name, schema in available.items():
            if any(k in name.lower() for k in ("search", "retriev", "lookup", "knowledge")):
                param = _first_string_param(schema) or "query"
                return ToolCall(name, {param: task.strip()[:500]})
        return None

    @staticmethod
    def _final_from_observations(task: str, observations: list[Message]) -> str:
        outputs = [o.content.strip() for o in observations]
        if len(outputs) == 1 and len(outputs[0]) <= 200 and "\n" not in outputs[0]:
            out = outputs[0]
            if out.startswith("ERROR"):
                return f"The tool reported an error: {out}"
            if _NOT_FOUND_RE.match(out):
                tool = observations[0].name or "the tool"
                return f"I could not find an answer with {tool}: {_sentence(out)}"
            return f"The answer is {_sentence(out)}"
        sources: dict[int, str] = {}
        for o in outputs:
            for n, text in parse_numbered_sources(o).items():
                sources[n if n not in sources else len(sources) + 1] = text
        if sources:
            return extractive_answer(task, sources, max_sentences=3)
        body = "\n\n".join(o[:600] for o in outputs)
        return f"Here is what I found:\n\n{body}"
