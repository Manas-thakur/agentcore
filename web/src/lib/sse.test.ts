import { describe, expect, it } from "vitest";

import { applyChatEvent, answerText, newAssistantTurn } from "./chat";
import { parseBlock, parseSSE, SSEParser } from "./sse";

describe("SSE parser", () => {
  it("parses event + JSON data blocks", () => {
    const events = parseSSE('event: token\ndata: {"step": 1, "content": "Hi"}\n\nevent: done\ndata: {"ok": true}\n\n');
    expect(events).toEqual([
      { event: "token", data: { step: 1, content: "Hi" } },
      { event: "done", data: { ok: true } },
    ]);
  });

  it("handles chunks split anywhere, CRLF and multi-line data", () => {
    const p = new SSEParser();
    const out = [
      ...p.push("event: ses"),
      ...p.push('sion\r\ndata: {"a":'),
      ...p.push("\r\ndata: 1}\r\n"),
      ...p.push("\r\n"),
    ];
    expect(out).toEqual([{ event: "session", data: { a: 1 } }]);
  });

  it("defaults to the message event, ignores comments and keeps non-JSON data as text", () => {
    expect(parseBlock(": keep-alive\ndata: [DONE]")).toEqual({ event: "message", data: "[DONE]" });
    expect(parseBlock(": only a comment")).toBeNull();
  });

  it("flushes a trailing event without a blank line", () => {
    const p = new SSEParser();
    expect(p.push('data: {"x": 2}')).toEqual([]);
    expect(p.end()).toEqual([{ event: "message", data: { x: 2 } }]);
  });

  it("parses OpenAI-style chunks", () => {
    const body = 'data: {"choices":[{"delta":{"content":"4"}}]}\n\ndata: [DONE]\n\n';
    const events = parseSSE(body);
    expect(events).toHaveLength(2);
    expect(events[1].data).toBe("[DONE]");
  });
});

describe("chat event folding", () => {
  it("builds an assistant turn from the agent event stream", () => {
    const stream = [
      { event: "session", data: { session_id: "s_1", title: "t", model: "mock", context: { tools: ["calculator"], system_prompt: "default", memory_messages: 0 } } },
      { event: "run_start", data: { step: 0, trace_id: "abc" } },
      { event: "step_start", data: { step: 1 } },
      { event: "model_response", data: { step: 1, latency_ms: 3, usage: { total_tokens: 40 }, tool_calls: [{}] } },
      { event: "tool_start", data: { step: 1, id: "c1", name: "calculator", arguments: { expression: "2+2" } } },
      { event: "tool_end", data: { step: 1, id: "c1", success: true, output: "4", error: null, latency_ms: 1 } },
      { event: "step_start", data: { step: 2 } },
      { event: "token", data: { step: 2, content: "The answer " } },
      { event: "token", data: { step: 2, content: "is 4." } },
      { event: "final", data: { step: 2, output: "The answer is 4." } },
      { event: "done", data: { session_id: "s_1", trace_id: "abc", output: "The answer is 4.", stop_reason: "final", steps: 2, usage: { prompt_tokens: 50, completion_tokens: 10, total_tokens: 60 }, cost_usd: 0, duration_ms: 12 } },
    ];
    const turn = stream.reduce(applyChatEvent, newAssistantTurn());
    expect(turn.status).toBe("ok");
    expect(turn.trace_id).toBe("abc");
    expect(turn.context?.tools).toEqual(["calculator"]);
    const tool = turn.parts.find((p) => p.type === "tool");
    expect(tool).toMatchObject({ name: "calculator", status: "ok", output: "4" });
    expect(answerText(turn)).toBe("The answer is 4.");
    expect(turn.usage?.total_tokens).toBe(60);
  });

  it("records errors and stops", () => {
    const failed = applyChatEvent(newAssistantTurn(), { event: "error", data: { message: "boom" } });
    expect(failed).toMatchObject({ status: "error", error: "boom" });
    const stopped = applyChatEvent(newAssistantTurn(), { event: "stopped", data: {} });
    expect(stopped.status).toBe("stopped");
  });
});
