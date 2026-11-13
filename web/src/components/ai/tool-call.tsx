import { WrenchIcon } from "lucide-react";

import { ArgsList, JsonView } from "@/components/app/code-view";
import { SectionTitle } from "@/components/app/common";
import {
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";
import { compactArgs, fmtMs, oneLine } from "@/lib/format";

export interface ToolCallView {
  name: string;
  arguments: Record<string, unknown> | undefined | null;
  status: "running" | "ok" | "error";
  output?: unknown;
  error?: string | null;
  latency_ms?: number | null;
}

/**
 * Tool pattern: one tool call from input to output. Collapsed it reads
 * `calculator(expression: "17 * 23 + 4") → 395`; expanded it shows arguments and result.
 */
export function ToolCall({ call, defaultOpen }: { call: ToolCallView; defaultOpen?: boolean }) {
  const failed = call.status === "error";
  const running = call.status === "running";
  const result = failed ? call.error || String(call.output ?? "") : call.output;
  const head = (
    <TraceLine status={running ? "running" : failed ? "error" : undefined}>
      <TraceIcon>
        <WrenchIcon />
      </TraceIcon>
      <TraceTitle>
        <span className="font-mono text-foreground/90">{call.name}</span>
        <span className="font-mono text-xs">({oneLine(compactArgs(call.arguments).replace(/^\(\)$/, ""), 60)})</span>
        {running ? (
          <span> running…</span>
        ) : (
          <span className="font-mono text-xs">
            {" "}
            → {failed ? "error: " : ""}
            {oneLine(typeof result === "string" ? result : JSON.stringify(result), 60)}
          </span>
        )}
      </TraceTitle>
      {call.latency_ms !== undefined && call.latency_ms !== null && !running ? (
        <TraceDescription>{fmtMs(call.latency_ms)}</TraceDescription>
      ) : null}
    </TraceLine>
  );
  if (running) return head;
  return (
    <TraceCollapsible defaultOpen={defaultOpen ?? failed}>
      <TraceCollapsibleTrigger aria-label={`Tool call ${call.name}${failed ? ", failed" : ""}. Show details`}>
        {head}
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="space-y-3">
        <div className="space-y-1.5">
          <SectionTitle>Arguments</SectionTitle>
          <ArgsList args={call.arguments} />
        </div>
        <div className="space-y-1.5">
          <SectionTitle>{failed ? "Error" : "Result"}</SectionTitle>
          <JsonView value={result} variant={failed ? "destructive" : "default"} contentClassName="max-h-64" />
        </div>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}
