import * as React from "react";
import {
  BrainIcon,
  CircleCheckIcon,
  CircleSlashIcon,
  CpuIcon,
  ExternalLinkIcon,
  LoaderCircleIcon,
  MessageSquareTextIcon,
  OctagonXIcon,
} from "lucide-react";
import { Link } from "react-router";

import { StackTrace } from "@/components/ai/stack-trace";
import { ToolCall } from "@/components/ai/tool-call";
import { Badge } from "@/components/ui/badge";
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";
import { answerText, toolParts, turnTokens } from "@/lib/chat";
import { fmtMs, fmtNum, oneLine, plural } from "@/lib/format";
import type { AssistantTurn, ChatContext, ModelPart, TextPart, ToolPart } from "@/lib/types";

function useElapsed(running: boolean, since: number) {
  const [now, setNow] = React.useState(() => performance.now());
  React.useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(id);
  }, [running]);
  return running ? now - since : 0;
}

/** "Added to context" chips: what the model saw besides the new message. */
export function ContextChips({ context }: { context?: ChatContext }) {
  if (!context) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-muted-foreground">Added to context</span>
      <Badge variant="outline" className="font-normal">
        {context.system_prompt === "custom" ? "Custom" : "Default"} system prompt
      </Badge>
      {context.memory_messages ? (
        <Badge variant="outline" className="font-normal">
          {plural(context.memory_messages, "earlier message")}
        </Badge>
      ) : null}
      {context.tools.length ? (
        context.tools.map((t) => (
          <Badge key={t} variant="secondary" className="font-mono font-normal">
            {t}
          </Badge>
        ))
      ) : (
        <Badge variant="outline" className="font-normal">
          no tools
        </Badge>
      )}
    </div>
  );
}

/** Reasoning pattern: text the model wrote before calling tools ("thinking aloud"). */
function ReasoningRow({ text, running }: { text: string; running: boolean }) {
  return (
    <TraceCollapsible defaultOpen={false}>
      <TraceCollapsibleTrigger>
        <TraceLine status={running ? "running" : undefined}>
          <TraceIcon>
            <BrainIcon />
          </TraceIcon>
          <TraceTitle>{running ? "Thinking" : `Thought: ${oneLine(text, 70)}`}</TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <p className="text-xs whitespace-pre-wrap">{text}</p>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/** Task pattern: one model step with the tool calls it requested. */
function StepTask({
  step,
  model,
  thought,
  tools,
  running,
}: {
  step: number;
  model?: ModelPart;
  thought: string;
  tools: ToolPart[];
  running: boolean;
}) {
  const pending = !model && running;
  const failed = tools.some((t) => t.status === "error");
  const meta = model
    ? [model.latency_ms ? fmtMs(model.latency_ms) : "", model.tokens ? `${fmtNum(model.tokens)} tok` : ""]
        .filter(Boolean)
        .join(" · ")
    : "";
  const title = model
    ? model.tool_calls
      ? `Step ${step}: requested ${plural(model.tool_calls, "tool call")}`
      : `Step ${step}: model answered`
    : `Step ${step}: calling the model`;
  if (!thought && !tools.length) {
    return (
      <TraceLine status={pending ? "running" : undefined}>
        <TraceIcon>
          <CpuIcon />
        </TraceIcon>
        <TraceTitle>{title}</TraceTitle>
        {meta ? <TraceDescription>{meta}</TraceDescription> : null}
      </TraceLine>
    );
  }
  return (
    <TraceCollapsible defaultOpen>
      <TraceCollapsibleTrigger>
        <TraceLine status={pending && !tools.length ? "running" : failed ? "error" : undefined}>
          <TraceIcon>
            <CpuIcon />
          </TraceIcon>
          <TraceTitle>{title}</TraceTitle>
          {meta ? <TraceDescription>{meta}</TraceDescription> : null}
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <Trace>
          {thought ? <ReasoningRow text={thought} running={pending && !tools.length} /> : null}
          {tools.map((t) => (
            <ToolCall key={t.id || `${step}-${t.name}`} call={t} />
          ))}
        </Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/**
 * Chain of Thought pattern: "Worked for 1.2 s · 2 tool calls · 183 tokens" above a reply,
 * expanding into the step timeline (model calls, reasoning, tool calls, final answer).
 */
export function RunSummary({ turn, startedAt }: { turn: AssistantTurn; startedAt?: number }) {
  const running = turn.status === "running";
  const [open, setOpen] = React.useState(false);
  const since = React.useRef(startedAt ?? performance.now());
  const elapsed = useElapsed(running, since.current);
  const tools = toolParts(turn);
  const failed = tools.filter((t) => t.status === "error").length;
  const tokens = turnTokens(turn);
  const status = turn.status;
  const icon = running ? (
    <LoaderCircleIcon className="animate-spin" />
  ) : status === "ok" ? (
    failed ? (
      <CircleCheckIcon className="text-warning" />
    ) : (
      <CircleCheckIcon />
    )
  ) : status === "stopped" ? (
    <CircleSlashIcon />
  ) : (
    <OctagonXIcon />
  );
  const lead = running ? "Working" : status === "stopped" ? "Stopped" : status === "ok" ? "Worked" : "Failed";
  const dur = running ? elapsed : turn.duration_ms;
  const durText = dur ? `${running ? " · " : status === "ok" ? " for " : " after "}${fmtMs(dur)}` : "";
  const bits: string[] = [];
  if (tools.length) bits.push(plural(tools.length, "tool call"));
  else if (turn.steps) bits.push(plural(turn.steps, "step"));
  if (tokens) bits.push(`${fmtNum(tokens)} tokens`);
  if (failed) bits.push(`${failed} failed`);

  const stepNums = [...new Set(turn.parts.map((p) => p.step).filter((s): s is number => typeof s === "number"))].sort(
    (a, b) => a - b,
  );
  if (!stepNums.length && turn.steps) for (let i = 1; i <= turn.steps; i++) stepNums.push(i);
  const maxToolStep = tools.length ? Math.max(...tools.map((t) => t.step ?? 0)) : -1;
  const answer = answerText(turn);

  return (
    <Trace>
      <TraceCollapsible open={open} onOpenChange={setOpen}>
        <TraceCollapsibleTrigger aria-label={`${lead}${durText}${bits.length ? `, ${bits.join(", ")}` : ""}. ${open ? "Hide" : "Show"} steps`}>
          <TraceLine status={running ? "running" : status !== "ok" && status !== "stopped" ? "error" : undefined}>
            <TraceIcon>{icon}</TraceIcon>
            <TraceTitle>
              {lead}
              {durText}
            </TraceTitle>
            {bits.length ? <TraceDescription>· {bits.join(" · ")}</TraceDescription> : null}
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent className="space-y-3">
          <ContextChips context={turn.context} />
          <Trace>
            {stepNums.map((step) => {
              const model = turn.parts.find((p): p is ModelPart => p.type === "model" && p.step === step);
              const thought =
                step <= maxToolStep
                  ? turn.parts
                      .filter((p): p is TextPart => p.type === "text" && p.step === step)
                      .map((p) => p.content)
                      .join("")
                  : "";
              return (
                <StepTask
                  key={step}
                  step={step}
                  model={model}
                  thought={thought}
                  tools={tools.filter((t) => t.step === step)}
                  running={running}
                />
              );
            })}
            {!running && status === "ok" ? (
              <TraceLine>
                <TraceIcon>
                  <MessageSquareTextIcon />
                </TraceIcon>
                <TraceTitle>Final answer: {oneLine(turn.content || answer, 80)}</TraceTitle>
                {turn.duration_ms ? <TraceDescription>{fmtMs(turn.duration_ms)}</TraceDescription> : null}
              </TraceLine>
            ) : null}
            {!running && status === "stopped" ? (
              <TraceLine>
                <TraceIcon>
                  <CircleSlashIcon />
                </TraceIcon>
                <TraceTitle>Stopped before a final answer</TraceTitle>
              </TraceLine>
            ) : null}
            {!running && status !== "ok" && status !== "stopped" ? (
              <StackTrace error={turn.error || `Run ended: ${status}`} label={turn.error ? "Failed" : "Ended"} />
            ) : null}
          </Trace>
          {turn.trace_id ? (
            <Link
              to={`/traces/${turn.trace_id}`}
              className="inline-flex items-center gap-1 text-xs text-brand hover:underline"
            >
              Open the full trace <ExternalLinkIcon className="size-3" />
            </Link>
          ) : null}
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}
