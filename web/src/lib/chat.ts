// Typed client for POST /api/chat (Server-Sent Events). The AI SDK's UI hooks expect their own
// stream protocol; AgentCore streams its agent events (session, run_start, step_start, token,
// model_response, tool_start, tool_end, reflection, final, done | stopped | error), so this
// module folds those events into the same AssistantTurn shape the server persists.

import type { AssistantTurn, ChatContext, ToolPart, TurnPart, Usage } from "@/lib/types";

export interface ChatRequest {
  message: string;
  session_id?: string | null;
  model?: string | null;
  tools?: string[] | null;
  system_prompt?: string | null;
  max_steps?: number;
}

export type ChatEvent =
  | { event: "session"; data: { session_id: string; title: string; model: string; context: ChatContext } }
  | { event: "run_start"; data: { step: number; trace_id?: string } }
  | { event: "step_start"; data: { step: number } }
  | { event: "token"; data: { step: number; content: string } }
  | {
      event: "model_response";
      data: { step: number; content?: string; latency_ms?: number; usage?: Usage; tool_calls?: unknown[] };
    }
  | { event: "tool_start"; data: { step: number; id: string; name: string; arguments: Record<string, unknown> } }
  | {
      event: "tool_end";
      data: { step: number; id: string; success: boolean; output: string; error: string | null; latency_ms: number };
    }
  | { event: "reflection"; data: { step: number; content: string } }
  | { event: "final"; data: { step: number; output: string } }
  | {
      event: "done";
      data: {
        session_id: string;
        trace_id: string;
        output: string;
        stop_reason: string;
        steps: number;
        usage: Usage;
        cost_usd: number;
        duration_ms: number;
      };
    }
  | { event: "stopped"; data: { trace_id?: string | null } }
  | { event: "error"; data: { message: string; trace_id?: string | null } };

export function newAssistantTurn(model?: string): AssistantTurn {
  return { role: "assistant", content: "", parts: [], status: "running", model, ts: Date.now() / 1000 };
}

/** Fold one SSE event into the streaming assistant turn (pure; returns a new object). */
export function applyChatEvent(turn: AssistantTurn, ev: { event: string; data: unknown }): AssistantTurn {
  const t: AssistantTurn = { ...turn, parts: turn.parts.slice() };
  const parts = t.parts;
  const d = (ev.data || {}) as Record<string, unknown>;
  switch (ev.event) {
    case "session": {
      const s = d as ChatEvent["data"] & { model: string; context: ChatContext };
      t.model = s.model;
      t.context = s.context;
      break;
    }
    case "run_start":
      t.trace_id = (d.trace_id as string) || t.trace_id;
      break;
    case "step_start":
      t.steps = Math.max(t.steps || 0, Number(d.step) || 0);
      break;
    case "token": {
      const step = Number(d.step);
      const last = parts[parts.length - 1];
      if (last && last.type === "text" && last.step === step) {
        parts[parts.length - 1] = { ...last, content: last.content + String(d.content ?? "") };
      } else {
        parts.push({ type: "text", step, content: String(d.content ?? "") });
      }
      break;
    }
    case "model_response": {
      const step = Number(d.step);
      const usage = d.usage as Usage | undefined;
      parts.push({
        type: "model",
        step,
        latency_ms: Number(d.latency_ms) || 0,
        tokens: usage?.total_tokens || 0,
        tool_calls: Array.isArray(d.tool_calls) ? d.tool_calls.length : 0,
      });
      const hasText = parts.some((p) => p.type === "text" && p.step === step);
      if (d.content && !hasText) parts.push({ type: "text", step, content: String(d.content) });
      break;
    }
    case "tool_start":
      parts.push({
        type: "tool",
        id: String(d.id),
        name: String(d.name),
        arguments: (d.arguments as Record<string, unknown>) || {},
        step: Number(d.step),
        status: "running",
      });
      break;
    case "tool_end": {
      const i = parts.findIndex((p) => p.type === "tool" && p.id === d.id);
      if (i >= 0) {
        parts[i] = {
          ...(parts[i] as ToolPart),
          status: d.success ? "ok" : "error",
          output: String(d.output ?? ""),
          error: (d.error as string | null) ?? null,
          latency_ms: Number(d.latency_ms) || 0,
        };
      }
      break;
    }
    case "reflection":
      parts.push({ type: "note", step: Number(d.step), content: String(d.content ?? "") });
      break;
    case "final":
      t.content = String(d.output ?? "");
      break;
    case "done": {
      const stop = String(d.stop_reason || "final");
      t.status = stop === "final" ? "ok" : stop;
      t.content = String(d.output ?? t.content);
      t.trace_id = (d.trace_id as string) || t.trace_id;
      t.usage = d.usage as Usage;
      t.cost_usd = Number(d.cost_usd) || 0;
      t.steps = Number(d.steps) || t.steps;
      t.duration_ms = Number(d.duration_ms) || t.duration_ms;
      if (stop !== "final") parts.push({ type: "note", content: String(d.output ?? stop) });
      break;
    }
    case "stopped":
      t.status = "stopped";
      t.trace_id = (d.trace_id as string) || t.trace_id;
      break;
    case "error":
      t.status = "error";
      t.error = String(d.message ?? "unknown error");
      t.trace_id = (d.trace_id as string) || t.trace_id;
      break;
    default:
      break;
  }
  return t;
}

export function toolParts(turn: AssistantTurn): ToolPart[] {
  return turn.parts.filter((p): p is ToolPart => p.type === "tool");
}

/** Text after the last tool call is the answer; earlier text is the model "thinking aloud". */
export function answerText(turn: AssistantTurn): string {
  const tools = toolParts(turn);
  const maxToolStep = tools.length ? Math.max(...tools.map((p) => p.step ?? 0)) : -1;
  const text = turn.parts
    .filter((p): p is Extract<TurnPart, { type: "text" }> => p.type === "text" && (p.step ?? 0) > maxToolStep)
    .map((p) => p.content)
    .join("");
  if (text) return text;
  if (turn.status !== "running" && !turn.parts.some((p) => p.type === "text")) return turn.content || "";
  return "";
}

export function turnTokens(turn: AssistantTurn): number {
  if (turn.usage) return turn.usage.total_tokens;
  return turn.parts.reduce((a, p) => a + (p.type === "model" ? p.tokens || 0 : 0), 0);
}
