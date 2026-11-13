import { GaugeIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { Progress } from "@/components/ui/progress";
import { fmtCost, fmtNum } from "@/lib/format";
import type { AssistantTurn, Turn } from "@/lib/types";

/** Server-side chat sessions keep the last 10 turns in memory (SlidingWindowMemory(10)). */
export const MEMORY_TURNS = 10;

/**
 * Context pattern: how much of the chat the model still sees (memory window) and the tokens
 * this chat has used so far.
 */
export function ContextUsage({ turns }: { turns: Turn[] }) {
  const assistant = turns.filter((t): t is AssistantTurn => t.role === "assistant");
  const userTurns = turns.filter((t) => t.role === "user").length;
  if (!assistant.length) return null;
  const last = [...assistant].reverse().find((t) => t.usage);
  const prompt = assistant.reduce((a, t) => a + (t.usage?.prompt_tokens || 0), 0);
  const completion = assistant.reduce((a, t) => a + (t.usage?.completion_tokens || 0), 0);
  const cost = assistant.reduce((a, t) => a + (t.cost_usd || 0), 0);
  const inWindow = Math.min(userTurns, MEMORY_TURNS);
  const pct = Math.round((inWindow / MEMORY_TURNS) * 100);
  const rows: [string, string][] = [
    ["Last prompt", `${fmtNum(last?.usage?.prompt_tokens ?? 0)} tok`],
    ["Chat input", `${fmtNum(prompt)} tok`],
    ["Chat output", `${fmtNum(completion)} tok`],
    ["Estimated cost", fmtCost(cost)],
  ];
  return (
    <HoverCard openDelay={100} closeDelay={100}>
      <HoverCardTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" aria-label={`Context: ${pct}% of the memory window used`}>
          <GaugeIcon />
          <span className="tabular">{pct}%</span>
          <span className="hidden sm:inline">context</span>
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="flex w-64 flex-col gap-3" align="end">
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="font-medium">Context</span>
          <span className="text-muted-foreground tabular">
            {inWindow} / {MEMORY_TURNS} turns
          </span>
        </div>
        <Progress value={pct} aria-label="Memory window used" />
        <p className="text-xs text-muted-foreground">
          The server keeps the last {MEMORY_TURNS} turns of this chat in the agent's memory; older turns drop out.
        </p>
        <div className="flex flex-col gap-1 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3">
              <span className="text-muted-foreground">{label}</span>
              <span className="tabular">{value}</span>
            </div>
          ))}
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}
