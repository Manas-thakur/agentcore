import * as React from "react";
import { cn } from "cn";
import {
  BrainIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleIcon,
  CircleXIcon,
  FlaskConicalIcon,
  ListTodoIcon,
  MessageSquareTextIcon,
  WrenchIcon,
} from "lucide-react";

import { ArgsList, JsonView } from "@/components/app/code-view";
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
import { fmtMs, fmtPct, oneLine, plural } from "@/lib/format";
import type { CaseResult, EvalRunDetail, MatrixCell, TrajectoryStep } from "@/lib/types";

export function cellTone(c: MatrixCell | null | undefined): string {
  if (!c) return "bg-muted/40 text-muted-foreground";
  if (c.passed) return "bg-success/12 text-success dark:bg-success/15";
  if (c.score > 0) return "bg-warning/15 text-warning";
  return "bg-destructive/12 text-destructive dark:bg-destructive/20";
}

/** Queue pattern: the cases of a running eval, split into what is left and what is done. */
export function RunQueue({ run, caseNames }: { run: EvalRunDetail; caseNames: string[] }) {
  const done = run.results || [];
  const doneNames = new Set(done.map((r) => r.case));
  const left = caseNames.filter((c) => !doneNames.has(c));
  return (
    <Trace>
      <TraceCollapsible defaultOpen>
        <TraceCollapsibleTrigger>
          <TraceLine status="running">
            <TraceIcon>
              <ListTodoIcon />
            </TraceIcon>
            <TraceTitle>{plural(left.length, "case")} left</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace>
            {left.length ? (
              left.map((c, i) => (
                <TraceLine key={c} status={i < 4 ? "running" : "pending"}>
                  <TraceIcon>{i < 4 ? <CircleDashedIcon /> : <CircleIcon />}</TraceIcon>
                  <TraceTitle className="font-mono text-xs">{c}</TraceTitle>
                </TraceLine>
              ))
            ) : (
              <TraceLine>
                <TraceTitle>Finishing up…</TraceTitle>
              </TraceLine>
            )}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
      <TraceCollapsible defaultOpen>
        <TraceCollapsibleTrigger>
          <TraceLine>
            <TraceIcon>
              <CircleCheckIcon />
            </TraceIcon>
            <TraceTitle>
              {plural(done.length, "case")} done · {run.passed} passed
            </TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace>
            {done.map((r) => (
              <TraceLine key={r.case} status={r.passed ? undefined : "error"}>
                <TraceIcon>{r.passed ? <CircleCheckIcon className="text-success" /> : <CircleXIcon />}</TraceIcon>
                <TraceTitle className="font-mono text-xs">{r.case}</TraceTitle>
                <TraceDescription>
                  {r.score.toFixed(2)} · {fmtMs(r.duration_ms)}
                </TraceDescription>
              </TraceLine>
            ))}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

/** Test Results pattern: "Ran 3 cases, 2 passed" expanding into one row per case. */
export function TestResults({
  run,
  onOpenCase,
  openCase,
}: {
  run: EvalRunDetail;
  onOpenCase: (name: string) => void;
  openCase: string | null;
}) {
  const results = [...(run.results || [])].sort(
    (a, b) => Number(a.passed) - Number(b.passed) || a.case.localeCompare(b.case),
  );
  const failed = results.filter((r) => !r.passed).length;
  const base = run.baseline?.cases;
  return (
    <Trace>
      <TraceCollapsible defaultOpen>
        <TraceCollapsibleTrigger>
          <TraceLine status={failed ? "error" : undefined}>
            <TraceIcon>
              <FlaskConicalIcon />
            </TraceIcon>
            <TraceTitle>
              Ran {plural(results.length, "case")}, {results.length - failed} passed
              {failed ? `, ${failed} failed` : ""}
            </TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent className="pr-0 pl-2">
          <ul className="divide-y rounded-lg border">
            {results.map((r) => {
              const b = base?.[r.case];
              const regressed = b && b.passed && !r.passed;
              const fixed = b && !b.passed && r.passed;
              const delta = b ? r.score - b.score : 0;
              return (
                <li key={r.case}>
                  <button
                    type="button"
                    onClick={() => onOpenCase(r.case)}
                    aria-current={openCase === r.case ? "true" : undefined}
                    className={cn(
                      "grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-3 gap-y-1 px-3 py-2 text-left text-sm hover:bg-muted/50 aria-[current=true]:bg-muted sm:grid-cols-[auto_minmax(0,14rem)_minmax(0,1fr)_auto]",
                      regressed && "bg-destructive/5",
                    )}
                  >
                    {r.passed ? (
                      <CircleCheckIcon className="mt-0.5 size-4 text-success" aria-label="passed" />
                    ) : (
                      <CircleXIcon className="mt-0.5 size-4 text-destructive" aria-label="failed" />
                    )}
                    <span className="min-w-0">
                      <span className="block truncate font-mono text-xs font-medium text-foreground">{r.case}</span>
                      {r.tags?.length ? <span className="block text-xs text-muted-foreground">{r.tags.join(", ")}</span> : null}
                    </span>
                    <span className="col-span-3 col-start-2 row-start-2 flex flex-wrap gap-1 sm:col-span-1 sm:col-start-3 sm:row-start-1">
                      {r.metrics.map((m) => {
                        const bm = b?.metrics?.[m.name];
                        const worse = bm !== undefined && m.score < bm - 0.001;
                        return (
                          <Badge
                            key={m.name}
                            variant={m.passed ? "secondary" : "destructive"}
                            className={cn("font-mono font-normal", worse && "ring-1 ring-warning")}
                            title={m.details || undefined}
                          >
                            {m.name} {m.score.toFixed(2)}
                          </Badge>
                        );
                      })}
                      {r.error ? <Badge variant="destructive">error</Badge> : null}
                    </span>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground tabular">
                      <span className="hidden sm:inline">{fmtMs(r.duration_ms)}</span>
                      <span className="font-medium text-foreground">{r.score.toFixed(2)}</span>
                      {regressed ? (
                        <Badge variant="destructive">regressed</Badge>
                      ) : fixed ? (
                        <Badge className="bg-success/15 text-success">fixed</Badge>
                      ) : b && Math.abs(delta) > 0.001 ? (
                        <span className={delta > 0 ? "text-success" : "text-destructive"}>
                          {delta > 0 ? "+" : ""}
                          {delta.toFixed(2)}
                        </span>
                      ) : run.baseline ? (
                        <span>{b ? "same" : "new"}</span>
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

/** A recorded eval trajectory as a step timeline. */
export function Trajectory({ result }: { result: CaseResult }) {
  const steps: TrajectoryStep[] = result.trajectory?.steps || [];
  if (!steps.length) return <p className="text-xs text-muted-foreground">No steps were recorded.</p>;
  return (
    <Trace>
      {steps.map((s, i) => {
        if (s.type === "tool_call")
          return (
            <TraceCollapsible key={i} defaultOpen>
              <TraceCollapsibleTrigger>
                <TraceLine>
                  <TraceIcon>
                    <WrenchIcon />
                  </TraceIcon>
                  <TraceTitle>
                    Called <span className="font-mono">{s.tool_name}</span>
                  </TraceTitle>
                  <TraceDescription>step {s.step}</TraceDescription>
                </TraceLine>
              </TraceCollapsibleTrigger>
              <TraceCollapsibleContent>
                <ArgsList args={s.arguments} />
              </TraceCollapsibleContent>
            </TraceCollapsible>
          );
        if (s.type === "tool_result")
          return (
            <TraceCollapsible key={i}>
              <TraceCollapsibleTrigger>
                <TraceLine status={s.success === false ? "error" : undefined}>
                  <TraceIcon>
                    <WrenchIcon />
                  </TraceIcon>
                  <TraceTitle>
                    <span className="font-mono">{s.tool_name || "tool"}</span> → {oneLine(s.content, 60)}
                  </TraceTitle>
                  <TraceDescription>step {s.step}</TraceDescription>
                </TraceLine>
              </TraceCollapsibleTrigger>
              <TraceCollapsibleContent>
                <JsonView value={s.content} />
              </TraceCollapsibleContent>
            </TraceCollapsible>
          );
        if (s.type === "output")
          return (
            <TraceLine key={i}>
              <TraceIcon>
                <MessageSquareTextIcon />
              </TraceIcon>
              <TraceTitle>Final answer: {oneLine(s.content, 80)}</TraceTitle>
              <TraceDescription>step {s.step}</TraceDescription>
            </TraceLine>
          );
        return (
          <TraceLine key={i}>
            <TraceIcon>
              <BrainIcon />
            </TraceIcon>
            <TraceTitle>
              {s.type === "thought" ? "Model" : s.type}
              {s.content ? `: ${oneLine(s.content, 70)}` : ""}
            </TraceTitle>
            <TraceDescription>step {s.step}</TraceDescription>
          </TraceLine>
        );
      })}
    </Trace>
  );
}

export function Figure({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border bg-card px-3 py-2.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-xl font-semibold tracking-tight tabular">{value}</div>
      {sub ? <div className="truncate text-xs text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

export function passTone(rate: number | null | undefined) {
  if (rate === null || rate === undefined) return "secondary" as const;
  return rate === 1 ? ("ok" as const) : ("bad" as const);
}

export function PassBadge({ rate }: { rate: number | null | undefined }) {
  const tone = passTone(rate);
  return (
    <Badge
      variant={tone === "bad" ? "destructive" : "secondary"}
      className={cn("tabular", tone === "ok" && "bg-success/15 text-success")}
    >
      {fmtPct(rate)}
    </Badge>
  );
}
