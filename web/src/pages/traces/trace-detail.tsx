import * as React from "react";
import { cn } from "cn";
import { BotIcon, ChevronRightIcon, CircleCheckIcon, LoaderCircleIcon, OctagonXIcon } from "lucide-react";

import { Markdown } from "@/components/ai/markdown";
import { StackTrace } from "@/components/ai/stack-trace";
import { ToolCall } from "@/components/ai/tool-call";
import { ArgsList, CodeView, JsonView } from "@/components/app/code-view";
import { KindDot, Pill, SectionTitle, type SpanKind } from "@/components/app/common";
import { Badge } from "@/components/ui/badge";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
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
import { fmtCost, fmtMs, fmtNum, fmtTime, oneLine, pretty } from "@/lib/format";
import { useStored } from "@/lib/hooks";
import type { Span, TraceDetail as TraceDetailData } from "@/lib/types";

export function kindOf(name: string): SpanKind {
  if (name.startsWith("agent.run") || name.startsWith("graph.run") || name === "tool.invoke") return "agent";
  if (name === "agent.step" || name.startsWith("graph.node") || name === "agent.reflect") return "step";
  if (name === "model.generate") return "model";
  if (name.startsWith("tool.") || name.startsWith("a2a.")) return "tool";
  return "other";
}

function spanLabel(sp: Span): { name: string; sub: string } {
  const a = sp.attributes || {};
  if (sp.name === "agent.step") return { name: `step ${a.step ?? ""}`.trim(), sub: "" };
  if (sp.name === "model.generate") {
    const tok = a["tokens.total"] ? `${fmtNum(Number(a["tokens.total"]))} tok` : "";
    return { name: "model.generate", sub: [a.model, tok].filter(Boolean).join(" · ") };
  }
  if (sp.name.startsWith("tool.") && a["tool.name"]) return { name: String(a["tool.name"]), sub: sp.name };
  return { name: sp.name, sub: "" };
}

interface Node {
  span: Span;
  children: Node[];
}

function buildTree(spans: Span[]): Node[] {
  const byId = new Map<string, Node>(spans.map((s) => [s.span_id, { span: s, children: [] }]));
  const roots: Node[] = [];
  for (const s of spans) {
    const node = byId.get(s.span_id)!;
    if (s.parent_id && byId.has(s.parent_id)) byId.get(s.parent_id)!.children.push(node);
    else roots.push(node);
  }
  const sortRec = (nodes: Node[]) => {
    nodes.sort((a, b) => a.span.start_time - b.span.start_time);
    nodes.forEach((n) => sortRec(n.children));
  };
  sortRec(roots);
  return roots;
}

function descendants(sp: Span, all: Span[]): Span[] {
  const ids = new Set([sp.span_id]);
  const out: Span[] = [];
  for (const s of [...all].sort((a, b) => a.start_time - b.start_time)) {
    if (s.parent_id && ids.has(s.parent_id)) {
      ids.add(s.span_id);
      out.push(s);
    }
  }
  return out;
}

export function MetaPills({ data }: { data: TraceDetailData }) {
  const s = data.summary;
  const models = data.spans.filter((x) => x.name === "model.generate");
  const prompt = models.reduce((acc, m) => acc + Number(m.attributes["tokens.prompt"] || 0), 0);
  const completion = models.reduce((acc, m) => acc + Number(m.attributes["tokens.completion"] || 0), 0);
  if (!s) return null;
  const session = s.attributes?.["session.id"] as string | undefined;
  return (
    <div className="flex flex-wrap gap-1.5">
      <Pill label="Latency" value={fmtMs(s.duration_ms)} />
      <Pill label="Model" value={s.model || "-"} />
      <Pill
        label="Tokens"
        value={fmtNum(s.total_tokens ?? prompt + completion)}
        title={`${fmtNum(prompt)} prompt · ${fmtNum(completion)} completion`}
      />
      <Pill label="Cost" value={fmtCost(s.cost_usd ?? 0)} />
      {s.attributes?.steps !== undefined ? <Pill label="Steps" value={String(s.attributes.steps)} /> : null}
      <Pill
        label="Tools"
        value={String(s.tool_calls ?? 0)}
        tone={s.tool_errors ? "error" : undefined}
        title={s.tool_errors ? `${s.tool_errors} failed` : undefined}
      />
      <Pill label="Spans" value={String(s.span_count)} />
      {session ? (
        <Pill
          label="Session"
          value={session}
          href={`/playground/${encodeURIComponent(session)}`}
          title="Open this chat in the Playground"
        />
      ) : null}
      <Pill label="Started" value={fmtTime(s.start_time)} />
    </div>
  );
}

function ChatMessages({ messages }: { messages: { role: string; content?: string; name?: string; tool_calls?: unknown[] }[] }) {
  return (
    <div className="space-y-2">
      {messages.map((m, i) => (
        <div key={i} className="rounded-lg border bg-card">
          <div className="flex items-center gap-2 border-b px-3 py-1.5 text-xs">
            <Badge variant={m.role === "system" ? "secondary" : m.role === "tool" ? "outline" : "secondary"} className="font-mono">
              {m.role}
            </Badge>
            {m.name ? <span className="font-mono text-muted-foreground">{m.name}</span> : null}
          </div>
          {m.content ? <div className="px-3 py-2 text-xs whitespace-pre-wrap">{m.content}</div> : null}
          {m.tool_calls && m.tool_calls.length ? (
            <div className="p-2">
              <JsonView value={m.tool_calls} />
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <SectionTitle>{title}</SectionTitle>
      {children}
    </section>
  );
}

/** Subagent pattern: a nested agent run with its tool calls and result. */
function SubagentRow({ span, all }: { span: Span; all: Span[] }) {
  const tools = descendants(span, all).filter((s) => s.name === "tool.execute");
  const failed = span.status !== "ok";
  const name = span.name.replace(/^agent\.run:?/, "") || "agent";
  return (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>
        <TraceLine status={failed ? "error" : undefined}>
          <TraceIcon>
            <BotIcon />
          </TraceIcon>
          <TraceTitle>
            Subagent <span className="font-mono">{name}</span>
            {span.attributes.task ? `: ${oneLine(span.attributes.task, 60)}` : ""}
          </TraceTitle>
          <TraceDescription>{fmtMs(span.duration_ms)}</TraceDescription>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="space-y-2">
        <Trace>
          {tools.map((t) => (
            <ToolCall key={t.span_id} call={toolView(t)} />
          ))}
          <TraceLine>
            <TraceIcon>{failed ? <OctagonXIcon /> : <CircleCheckIcon />}</TraceIcon>
            <TraceTitle>{failed ? `Failed: ${span.error || ""}` : `Result: ${oneLine(span.attributes.output, 80)}`}</TraceTitle>
          </TraceLine>
        </Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

function toolView(t: Span) {
  const a = t.attributes || {};
  return {
    name: String(a["tool.name"] || "tool"),
    arguments: (a["tool.arguments"] as Record<string, unknown>) || {},
    status: t.status === "ok" ? ("ok" as const) : ("error" as const),
    output: a["tool.output"],
    error: t.status !== "ok" ? t.error || String(a["tool.output"] ?? "") : null,
    latency_ms: t.duration_ms,
  };
}

function Preview({ sp, all }: { sp: Span; all: Span[] }) {
  const a = sp.attributes || {};
  const kind = kindOf(sp.name);
  const parts: React.ReactNode[] = [];
  if (sp.error) parts.push(<Trace key="err"><StackTrace error={sp.error} label="Error" /></Trace>);
  if (sp.name === "model.generate") {
    const msgs = a["input.messages"];
    if (Array.isArray(msgs))
      parts.push(
        <Block key="in" title={`Input · ${msgs.length} messages`}>
          <ChatMessages messages={msgs as never} />
        </Block>,
      );
    const out = a["output.content"] as string | undefined;
    const calls = (a["output.tool_calls"] as { name: string; arguments: Record<string, unknown> }[]) || [];
    parts.push(
      <Block key="out" title="Output">
        {out ? <div className="rounded-lg border bg-card px-3 py-2 text-xs whitespace-pre-wrap">{out}</div> : null}
        {calls.map((c, i) => (
          <div key={i} className="rounded-lg border bg-card px-3 py-2">
            <div className="mb-1 text-xs text-muted-foreground">
              tool call <span className="font-mono text-foreground">{c.name}</span>
            </div>
            <ArgsList args={c.arguments} />
          </div>
        ))}
        {!out && !calls.length ? <p className="text-xs text-muted-foreground">(empty response)</p> : null}
      </Block>,
    );
    parts.push(
      <Block key="usage" title="Usage">
        <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-xs">
          <dt className="text-muted-foreground">model</dt>
          <dd className="font-mono">{String(a.model || "-")}</dd>
          <dt className="text-muted-foreground">tokens</dt>
          <dd className="tabular">
            {fmtNum(Number(a["tokens.prompt"] || 0))} in · {fmtNum(Number(a["tokens.completion"] || 0))} out
          </dd>
          <dt className="text-muted-foreground">cost</dt>
          <dd className="tabular">{fmtCost(Number(a["cost.usd"] || 0))}</dd>
          <dt className="text-muted-foreground">latency</dt>
          <dd className="tabular">{fmtMs(Number(a["latency.ms"] ?? sp.duration_ms))}</dd>
        </dl>
      </Block>,
    );
  } else if (kind === "tool" && ("tool.arguments" in a || "tool.output" in a)) {
    parts.push(
      <Trace key="tool">
        <ToolCall call={toolView(sp)} defaultOpen />
      </Trace>,
    );
  } else if (kind === "agent" || kind === "step") {
    if (a.task) parts.push(<Block key="task" title="Input"><div className="rounded-lg border bg-card px-3 py-2 text-sm whitespace-pre-wrap">{String(a.task)}</div></Block>);
    const under = descendants(sp, all);
    const subagents = under.filter((s) => s.name.startsWith("agent.run") && s.parent_id !== null);
    const subIds = new Set(subagents.flatMap((s) => [s.span_id, ...descendants(s, all).map((d) => d.span_id)]));
    const tools = under.filter((s) => s.name === "tool.execute" && !subIds.has(s.span_id));
    if (subagents.length || tools.length)
      parts.push(
        <Block key="calls" title={`Activity · ${tools.length} tool call${tools.length === 1 ? "" : "s"}${subagents.length ? ` · ${subagents.length} subagent${subagents.length === 1 ? "" : "s"}` : ""}`}>
          <Trace>
            {subagents.map((s) => (
              <SubagentRow key={s.span_id} span={s} all={all} />
            ))}
            {tools.map((t) => (
              <ToolCall key={t.span_id} call={toolView(t)} />
            ))}
          </Trace>
        </Block>,
      );
    if (a.output)
      parts.push(
        <Block key="output" title="Output">
          <div className="rounded-lg border bg-card px-3 py-2">
            <Markdown>{String(a.output)}</Markdown>
          </div>
        </Block>,
      );
    if (!a.task && !a.output && !under.length)
      parts.push(<p key="none" className="text-xs text-muted-foreground">Nothing to preview for this span. See Attributes.</p>);
  } else {
    parts.push(<Attributes key="attrs" sp={sp} t0={null} />);
  }
  return <div className="space-y-4">{parts}</div>;
}

function Attributes({ sp, t0 }: { sp: Span; t0: number | null }) {
  const basics: [string, unknown][] = [
    ["span id", sp.span_id],
    ["parent", sp.parent_id || "-"],
    ["status", sp.status],
    ["duration", fmtMs(sp.duration_ms)],
  ];
  if (t0 !== null) basics.push(["offset", `+${fmtMs((sp.start_time - t0) * 1000)}`]);
  basics.push(["started", fmtTime(sp.start_time)]);
  const rows = [...basics, ...Object.entries(sp.attributes || {})];
  return (
    <div className="space-y-4">
      <dl className="divide-y rounded-lg border text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[minmax(7rem,30%)_1fr] gap-3 px-3 py-1.5">
            <dt className="truncate font-mono text-muted-foreground" title={k}>
              {k}
            </dt>
            <dd className="min-w-0 font-mono break-words whitespace-pre-wrap">
              {v !== null && typeof v === "object" ? <JsonView value={v} contentClassName="max-h-60" /> : String(v)}
            </dd>
          </div>
        ))}
      </dl>
      {sp.events && sp.events.length ? (
        <Block title={`Events · ${sp.events.length}`}>
          <JsonView value={sp.events} />
        </Block>
      ) : null}
    </div>
  );
}

function JsonTab({ sp }: { sp: Span }) {
  const [formatted, setFormatted] = useStored("trace.jsonFormatted", true);
  return (
    <div className="space-y-2">
      <ToggleGroup
        type="single"
        size="sm"
        variant="outline"
        value={formatted ? "f" : "r"}
        onValueChange={(v) => v && setFormatted(v === "f")}
        aria-label="JSON format"
      >
        <ToggleGroupItem value="f">Formatted</ToggleGroupItem>
        <ToggleGroupItem value="r">Raw</ToggleGroupItem>
      </ToggleGroup>
      {formatted ? (
        <CodeView code={pretty(sp)} language="json" contentClassName="max-h-[60vh]" />
      ) : (
        <CodeView code={JSON.stringify(sp)} language="text" contentClassName="max-h-[60vh]" />
      )}
    </div>
  );
}

const TABS = ["preview", "attributes", "json"] as const;

export interface TraceDetailHandle {
  selectTab: (i: number) => void;
  focusTree: () => void;
}

/** Span tree (with latency bars proportional to the trace) above Preview / Attributes / JSON tabs. */
export const TraceDetail = React.forwardRef<
  TraceDetailHandle,
  { data: TraceDetailData; tab: number; onTab: (i: number) => void }
>(function TraceDetail({ data, tab, onTab }, ref) {
  const spans = data.spans;
  const roots = React.useMemo(() => buildTree(spans), [spans]);
  const t0 = Math.min(...spans.map((x) => x.start_time));
  const t1 = Math.max(...spans.map((x) => x.end_time || x.start_time));
  const total = Math.max((t1 - t0) * 1000, 0.001);
  const [collapsed, setCollapsed] = React.useState<Set<string>>(new Set());
  const [selected, setSelected] = React.useState<string | null>(roots[0]?.span.span_id ?? null);
  const treeRef = React.useRef<HTMLUListElement>(null);

  React.useEffect(() => {
    setSelected(roots[0]?.span.span_id ?? null);
    setCollapsed(new Set());
  }, [data.trace_id, roots]);

  const rows: { node: Node; depth: number; open: boolean; has: boolean }[] = [];
  const walk = (node: Node, depth: number) => {
    const has = node.children.length > 0;
    const open = !collapsed.has(node.span.span_id);
    rows.push({ node, depth, open, has });
    if (has && open) node.children.forEach((c) => walk(c, depth + 1));
  };
  roots.forEach((r) => walk(r, 0));

  const focusRow = (id: string | null) => {
    if (!id) return;
    requestAnimationFrame(() => treeRef.current?.querySelector<HTMLElement>(`[data-id="${id}"]`)?.focus());
  };

  React.useImperativeHandle(ref, () => ({
    selectTab: (i: number) => onTab(i),
    focusTree: () => focusRow(selected),
  }));

  const toggle = (id: string) =>
    setCollapsed((c) => {
      const n = new Set(c);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const onKeyDown = (ev: React.KeyboardEvent) => {
    const i = rows.findIndex((r) => r.node.span.span_id === selected);
    if (i < 0) return;
    const r = rows[i];
    let target: string | null = null;
    if (ev.key === "ArrowDown") target = rows[Math.min(rows.length - 1, i + 1)].node.span.span_id;
    else if (ev.key === "ArrowUp") target = rows[Math.max(0, i - 1)].node.span.span_id;
    else if (ev.key === "Home") target = rows[0].node.span.span_id;
    else if (ev.key === "End") target = rows[rows.length - 1].node.span.span_id;
    else if (ev.key === "ArrowRight" && r.has && !r.open) toggle(r.node.span.span_id);
    else if (ev.key === "ArrowLeft" && r.has && r.open) toggle(r.node.span.span_id);
    else return;
    ev.preventDefault();
    ev.stopPropagation();
    if (target) {
      setSelected(target);
      focusRow(target);
    }
  };

  const sp = spans.find((x) => x.span_id === selected) || spans[0];
  const label = spanLabel(sp);

  return (
    <ResizablePanelGroup orientation="vertical" className="min-h-0 flex-1" id="trace-detail-split">
      <ResizablePanel id="tree" defaultSize="38" minSize={96} className="min-h-0">
        <div className="h-full overflow-auto py-1">
          <ul ref={treeRef} role="tree" aria-label="Spans" onKeyDown={onKeyDown} className="@container">
            {rows.map(({ node, depth, open, has }) => {
              const s = node.span;
              const { name, sub } = spanLabel(s);
              const kind = kindOf(s.name);
              const left = ((s.start_time - t0) * 1000) / total;
              const width = Math.max(s.duration_ms / total, 0.004);
              const isSel = s.span_id === selected;
              const err = s.status !== "ok";
              return (
                <li
                  key={s.span_id}
                  role="treeitem"
                  aria-level={depth + 1}
                  aria-selected={isSel}
                  aria-expanded={has ? open : undefined}
                  tabIndex={isSel ? 0 : -1}
                  data-id={s.span_id}
                  title={`${s.name} · ${fmtMs(s.duration_ms)}`}
                  onClick={() => setSelected(s.span_id)}
                  className={cn(
                    "grid h-7 cursor-pointer grid-cols-[minmax(0,1fr)_4rem] items-center gap-2 px-2 @md:grid-cols-[minmax(0,1fr)_minmax(90px,30%)_4.5rem] text-xs outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
                    isSel && "bg-muted",
                  )}
                >
                  <span className="flex min-w-0 items-center gap-1" style={{ paddingLeft: depth * 14 }}>
                    {has ? (
                      <button
                        type="button"
                        tabIndex={-1}
                        aria-label={open ? "Collapse" : "Expand"}
                        className="flex size-4 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggle(s.span_id);
                        }}
                      >
                        <ChevronRightIcon className={cn("size-3.5 transition-transform", open && "rotate-90")} />
                      </button>
                    ) : (
                      <span className="size-4 shrink-0" />
                    )}
                    <KindDot kind={kind} error={err} />
                    <span className={cn("truncate font-medium", kind === "tool" && "font-mono", err && "text-destructive")}>
                      {name}
                    </span>
                    {sub ? <span className="truncate text-muted-foreground">{sub}</span> : null}
                    {err ? <span className="sr-only">(error)</span> : null}
                  </span>
                  <span className="relative hidden h-2 rounded-full bg-muted @md:block" aria-hidden="true">
                    <i
                      className={cn("absolute inset-y-0 rounded-full", err ? "bg-destructive" : {
                        agent: "bg-span-agent",
                        step: "bg-span-step",
                        model: "bg-span-model",
                        tool: "bg-span-tool",
                        other: "bg-muted-foreground",
                      }[kind])}
                      style={{
                        left: `${Math.min(left, 0.995) * 100}%`,
                        width: `${Math.min(width, 1 - Math.min(left, 0.995)) * 100}%`,
                      }}
                    />
                  </span>
                  <span className="text-right text-muted-foreground tabular">{fmtMs(s.duration_ms)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </ResizablePanel>
      <ResizableHandle withHandle aria-label="Resize span tree" />
      <ResizablePanel id="detail" minSize={160} className="min-h-0">
        <div className="flex h-full min-h-0 flex-col">
          <div className="flex shrink-0 items-center gap-2 px-4 pt-3">
            <KindDot kind={kindOf(sp.name)} error={sp.status !== "ok"} />
            <h3 className="truncate text-sm font-semibold">{label.name}</h3>
            <span className="truncate text-xs text-muted-foreground tabular">
              {sp.name} · {fmtMs(sp.duration_ms)} · +{fmtMs((sp.start_time - t0) * 1000)}
            </span>
            {sp.status !== "ok" ? (
              <Badge variant="destructive" className="ml-auto">
                error
              </Badge>
            ) : null}
          </div>
          <Tabs
            value={TABS[tab] || "preview"}
            onValueChange={(v) => onTab(Math.max(0, TABS.indexOf(v as (typeof TABS)[number])))}
            className="min-h-0 flex-1 gap-0"
          >
            <TabsList variant="line" className="mx-4 mt-1 shrink-0">
              <TabsTrigger value="preview">Preview</TabsTrigger>
              <TabsTrigger value="attributes">
                Attributes
                <span className="text-xs text-muted-foreground tabular">{Object.keys(sp.attributes || {}).length}</span>
              </TabsTrigger>
              <TabsTrigger value="json">JSON</TabsTrigger>
            </TabsList>
            <div className="min-h-0 flex-1 overflow-y-auto border-t p-4">
              <TabsContent value="preview">
                <Preview sp={sp} all={spans} />
              </TabsContent>
              <TabsContent value="attributes">
                <Attributes sp={sp} t0={t0} />
              </TabsContent>
              <TabsContent value="json">
                <JsonTab sp={sp} />
              </TabsContent>
            </div>
          </Tabs>
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
});

export function TraceStatusIcon({ status, loading }: { status?: string; loading?: boolean }) {
  if (loading) return <LoaderCircleIcon className="size-4 animate-spin text-muted-foreground" />;
  return status === "ok" ? (
    <CircleCheckIcon className="size-4 text-success" />
  ) : (
    <OctagonXIcon className="size-4 text-destructive" />
  );
}
