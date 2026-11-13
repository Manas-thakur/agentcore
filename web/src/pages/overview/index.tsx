import * as React from "react";
import { cn } from "cn";
import { ArrowDownRightIcon, ArrowUpRightIcon, LayoutDashboardIcon, MinusIcon, RefreshCwIcon } from "lucide-react";
import { Link } from "react-router";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { EmptyState, ErrorState, Page, PageHeader, Panel } from "@/components/app/common";
import { Button } from "@/components/ui/button";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { qs } from "@/lib/api";
import { fmtAgo, fmtCompact, fmtCost, fmtMs, fmtNum, fmtPct, pctChange } from "@/lib/format";
import { useFetch, useStored } from "@/lib/hooks";
import type { Kpis, OverviewResponse, SeriesPoint } from "@/lib/types";

const RANGES = [
  { days: 1, label: "24 h" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];

function Sparkline({ values, id, label }: { values: (number | null)[]; id: string; label: string }) {
  const data = values.map((v, i) => ({ i, v: v ?? 0 }));
  if (data.length < 2) return <div className="h-8" />;
  return (
    <ChartContainer
      config={{ v: { label, color: "var(--chart-1)" } }}
      className="aspect-auto h-8 w-full"
      aria-hidden="true"
    >
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={`spark-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-v)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--color-v)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          dataKey="v"
          type="monotone"
          stroke="var(--color-v)"
          strokeWidth={1.5}
          fill={`url(#spark-${id})`}
          isAnimationActive={false}
          dot={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}

type Better = "up" | "down" | "none";

function Kpi({
  id,
  label,
  value,
  cur,
  before,
  better,
  pp,
  series,
  sub,
  alert,
  hasPrev,
  rangeLabel,
}: {
  id: string;
  label: string;
  value: string;
  cur: number | null;
  before: number | null | undefined;
  better: Better;
  pp?: boolean;
  series: (number | null)[];
  sub?: string;
  alert?: boolean;
  hasPrev: boolean;
  rangeLabel: string;
}) {
  let delta: React.ReactNode = null;
  if (hasPrev && before !== undefined) {
    let text: string;
    let dir = 0;
    if (pp) {
      if (cur === null || before === null) text = "n/a";
      else {
        const d = (cur - before) * 100;
        dir = Math.sign(d);
        text = `${Math.abs(d).toFixed(1)} pp`;
      }
    } else {
      const change = pctChange(cur, before);
      if (change === null) text = "new";
      else {
        dir = Math.sign(change);
        text = `${Math.abs(change * 100).toFixed(Math.abs(change) < 0.1 ? 1 : 0)}%`;
      }
    }
    const diff = (cur ?? 0) - (before ?? 0);
    let tone = "text-muted-foreground";
    if (Math.abs(diff) > 1e-9 && better !== "none")
      tone = diff > 0 === (better === "up") ? "text-success" : "text-destructive";
    const Icon = dir > 0 ? ArrowUpRightIcon : dir < 0 ? ArrowDownRightIcon : MinusIcon;
    delta = (
      <span
        className={cn("inline-flex items-center gap-0.5 text-xs font-medium tabular", tone)}
        title={`Previous ${rangeLabel}: ${before === null ? "-" : before}`}
      >
        <Icon className="size-3.5" aria-hidden="true" />
        <span className="sr-only">{dir > 0 ? "up" : dir < 0 ? "down" : "unchanged"}</span>
        {text}
      </span>
    );
  }
  return (
    <div className={cn("flex min-w-0 flex-col gap-1 rounded-xl border bg-card p-4", alert && "border-destructive/40")}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex items-baseline gap-2">
        <span className={cn("text-2xl font-semibold tracking-tight tabular", alert && "text-destructive")}>{value}</span>
        {delta}
      </div>
      <span className="truncate text-xs text-muted-foreground">
        {sub || (hasPrev ? `vs previous ${rangeLabel}` : "no earlier data to compare")}
      </span>
      <Sparkline values={series} id={id} label={label} />
    </div>
  );
}

function useLabels(hourly: boolean) {
  return React.useMemo(
    () => ({
      tick: (t: number) => {
        const d = new Date(t * 1000);
        return hourly
          ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
          : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
      },
      when: (t: number) =>
        new Date(t * 1000).toLocaleString(
          undefined,
          hourly ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" } : { month: "short", day: "numeric" },
        ),
    }),
    [hourly],
  );
}

const runsConfig = {
  ok: { label: "ok", color: "var(--chart-1)" },
  failed: { label: "failed", color: "var(--destructive)" },
} satisfies ChartConfig;
const latencyConfig = {
  p50: { label: "p50", color: "var(--chart-1)" },
  p95: { label: "p95", color: "var(--chart-4)" },
} satisfies ChartConfig;
const tokensConfig = { tokens: { label: "Tokens", color: "var(--chart-2)" } } satisfies ChartConfig;
const costConfig = { cost: { label: "Cost (USD)", color: "var(--chart-5)" } } satisfies ChartConfig;

function Charts({ series, hourly }: { series: SeriesPoint[]; hourly: boolean }) {
  const { tick, when } = useLabels(hourly);
  const data = series.map((b) => ({
    t: b.t,
    ok: b.runs - b.errors,
    failed: b.errors,
    p50: b.p50_ms,
    p95: b.p95_ms,
    tokens: b.tokens,
    cost: b.cost_usd,
  }));
  const xAxis = (
    <XAxis dataKey="t" tickLine={false} axisLine={false} tickMargin={8} minTickGap={24} tickFormatter={tick} />
  );
  const grid = <CartesianGrid vertical={false} strokeDasharray="3 3" />;
  const labelFmt = (_: unknown, payload: readonly { payload?: { t?: number } }[]) =>
    payload?.[0]?.payload?.t ? when(payload[0].payload.t) : "";
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="Runs" description="Agent runs per bucket, failures stacked on top">
        <ChartContainer config={runsConfig} className="aspect-auto h-56 w-full">
          <BarChart data={data} margin={{ left: -12, right: 4 }}>
            {grid}
            {xAxis}
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={40} />
            <ChartTooltip content={<ChartTooltipContent labelFormatter={labelFmt} />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="ok" stackId="r" fill="var(--color-ok)" radius={[0, 0, 0, 0]} />
            <Bar dataKey="failed" stackId="r" fill="var(--color-failed)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ChartContainer>
      </Panel>
      <Panel title="Latency" description="p50 and p95 of agent runs">
        <ChartContainer config={latencyConfig} className="aspect-auto h-56 w-full">
          <LineChart data={data} margin={{ left: -4, right: 8 }}>
            {grid}
            {xAxis}
            <YAxis tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => (v ? fmtMs(v) : "0")} />
            <ChartTooltip
              content={<ChartTooltipContent labelFormatter={labelFmt} formatter={(v, n) => `${n} ${fmtMs(Number(v))}`} />}
            />
            <ChartLegend content={<ChartLegendContent />} />
            <Line dataKey="p50" type="monotone" stroke="var(--color-p50)" strokeWidth={2} dot={false} />
            <Line dataKey="p95" type="monotone" stroke="var(--color-p95)" strokeWidth={2} strokeDasharray="5 4" dot={false} />
          </LineChart>
        </ChartContainer>
      </Panel>
      <Panel title="Tokens" description="Prompt + completion">
        <ChartContainer config={tokensConfig} className="aspect-auto h-56 w-full">
          <BarChart data={data} margin={{ left: -4, right: 4 }}>
            {grid}
            {xAxis}
            <YAxis tickLine={false} axisLine={false} width={48} tickFormatter={(v: number) => fmtCompact(v)} />
            <ChartTooltip content={<ChartTooltipContent labelFormatter={labelFmt} />} />
            <Bar dataKey="tokens" fill="var(--color-tokens)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ChartContainer>
      </Panel>
      <Panel title="Cost" description="USD, estimated from the price table">
        <ChartContainer config={costConfig} className="aspect-auto h-56 w-full">
          <AreaChart data={data} margin={{ left: -4, right: 4 }}>
            <defs>
              <linearGradient id="cost-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--color-cost)" stopOpacity={0.35} />
                <stop offset="100%" stopColor="var(--color-cost)" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            {grid}
            {xAxis}
            <YAxis tickLine={false} axisLine={false} width={64} tickFormatter={(v: number) => (v ? fmtCost(v) : "0")} />
            <ChartTooltip
              content={<ChartTooltipContent labelFormatter={labelFmt} formatter={(v) => fmtCost(Number(v))} />}
            />
            <Area dataKey="cost" type="monotone" stroke="var(--color-cost)" strokeWidth={2} fill="url(#cost-fill)" />
          </AreaChart>
        </ChartContainer>
      </Panel>
    </div>
  );
}

export default function OverviewPage() {
  const [days, setDays] = useStored("overview.days", 7);
  const q = useFetch<OverviewResponse>(`/api/overview${qs({ days, tz: new Date().getTimezoneOffset() })}`);
  const d = q.data;
  const rangeLabel = RANGES.find((r) => r.days === days)?.label || `${days} days`;

  let body: React.ReactNode;
  if (q.error) body = <ErrorState error={q.error} onRetry={q.reload} />;
  else if (!d)
    body = (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-32 rounded-xl" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-72 rounded-xl" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      </div>
    );
  else if (!d.kpis.runs && !d.kpis.tool_calls)
    body = (
      <EmptyState
        icon={LayoutDashboardIcon}
        title="No runs in this range"
        description="Overview aggregates traces written by agent runs. Chat in the Playground, run an eval suite, or call the API, then come back."
      >
        <Button asChild size="sm">
          <Link to="/playground">Open Playground</Link>
        </Button>
      </EmptyState>
    );
  else {
    const k: Kpis = d.kpis;
    const prev = d.previous;
    const s = d.series;
    const maxCalls = Math.max(1, ...d.top_tools.map((t) => t.calls));
    body = (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Kpi id="runs" label="Runs" value={fmtNum(k.runs)} cur={k.runs} before={prev?.runs} better="none" series={s.map((b) => b.runs)} sub={`${fmtNum(k.tool_calls)} tool calls`} hasPrev={!!prev} rangeLabel={rangeLabel} />
          <Kpi
            id="success"
            label="Success rate"
            value={fmtPct(k.success_rate, 1)}
            cur={k.success_rate}
            before={prev?.success_rate}
            better="up"
            pp
            series={s.map((b) => (b.runs ? (b.runs - b.errors) / b.runs : null))}
            sub={`${fmtNum(k.errors)} failed`}
            alert={k.success_rate !== null && k.success_rate < 0.95}
            hasPrev={!!prev}
            rangeLabel={rangeLabel}
          />
          <Kpi id="p50" label="p50 latency" value={fmtMs(k.p50_ms)} cur={k.p50_ms} before={prev?.p50_ms} better="down" series={s.map((b) => b.p50_ms)} hasPrev={!!prev} rangeLabel={rangeLabel} />
          <Kpi id="p95" label="p95 latency" value={fmtMs(k.p95_ms)} cur={k.p95_ms} before={prev?.p95_ms} better="down" series={s.map((b) => b.p95_ms)} hasPrev={!!prev} rangeLabel={rangeLabel} />
          <Kpi id="tokens" label="Tokens" value={fmtCompact(k.tokens)} cur={k.tokens} before={prev?.tokens} better="none" series={s.map((b) => b.tokens)} sub={k.runs ? `${fmtNum(Math.round(k.tokens / k.runs))} per run` : "-"} hasPrev={!!prev} rangeLabel={rangeLabel} />
          <Kpi id="cost" label="Cost" value={fmtCost(k.cost_usd)} cur={k.cost_usd} before={prev?.cost_usd} better="down" series={s.map((b) => b.cost_usd)} sub="estimated from the price table" hasPrev={!!prev} rangeLabel={rangeLabel} />
        </div>
        <Charts series={s} hourly={d.range.bucket_seconds < 86400} />
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Top tools" description="By calls, with error rate" bodyClassName="p-0">
            {d.top_tools.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tool</TableHead>
                    <TableHead className="text-right">Calls</TableHead>
                    <TableHead className="text-right">Error rate</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">Avg latency</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.top_tools.map((t) => {
                    const rate = t.error_rate ?? (t.calls ? t.errors / t.calls : 0);
                    return (
                      <TableRow key={t.name}>
                        <TableCell className="w-1/2">
                          <Link
                            to={`/traces${qs({ query: `tool:${t.name}` })}`}
                            className="font-mono text-xs font-medium hover:underline"
                            title={`Traces that called ${t.name}`}
                          >
                            {t.name}
                          </Link>
                          <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                            <i className="bg-chart-1" style={{ width: `${((t.calls - t.errors) / maxCalls) * 100}%` }} />
                            <i className="bg-destructive" style={{ width: `${(t.errors / maxCalls) * 100}%` }} />
                          </div>
                        </TableCell>
                        <TableCell className="text-right tabular">{fmtNum(t.calls)}</TableCell>
                        <TableCell className={cn("text-right tabular", rate > 0 && "text-destructive")}>{fmtPct(rate, 1)}</TableCell>
                        <TableCell className="hidden text-right tabular sm:table-cell">{fmtMs(t.avg_ms)}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            ) : (
              <p className="p-4 text-sm text-muted-foreground">No tool calls in this range.</p>
            )}
          </Panel>
          <Panel title="Models" bodyClassName="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead className="text-right">Runs</TableHead>
                  <TableHead className="text-right">Tokens</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.models.map((m) => (
                  <TableRow key={m.model}>
                    <TableCell>
                      <Link to={`/traces${qs({ query: `model:${m.model.includes(" ") ? `"${m.model}"` : m.model}` })}`} className="font-mono text-xs hover:underline">
                        {m.model}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right tabular">{fmtNum(m.runs)}</TableCell>
                    <TableCell className="text-right tabular">{fmtNum(m.tokens)}</TableCell>
                    <TableCell className="text-right tabular">{fmtCost(m.cost_usd)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {d.recent_errors.length ? (
              <div className="space-y-2 border-t p-4">
                <div className="text-xs font-medium text-muted-foreground">Recent failures</div>
                <ul className="space-y-1.5 text-sm">
                  {d.recent_errors.map((e) => (
                    <li key={e.trace_id} className="flex min-w-0 items-baseline gap-2">
                      <span className="size-1.5 shrink-0 translate-y-[-2px] rounded-full bg-destructive" aria-hidden="true" />
                      <Link to={`/traces/${e.trace_id}`} className="min-w-0 truncate text-destructive hover:underline">
                        {e.error || e.name}
                      </Link>
                      <span className="shrink-0 text-xs text-muted-foreground">{fmtAgo(e.start_time)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Panel>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <Page>
        <PageHeader
          title="Overview"
          description="Agent runs from the trace directory. Deltas compare with the previous period of the same length."
          actions={
            <>
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={String(days)}
                onValueChange={(v) => v && setDays(Number(v))}
                aria-label="Time range"
              >
                {RANGES.map((r) => (
                  <ToggleGroupItem key={r.days} value={String(r.days)} className="px-3 text-xs">
                    {r.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              <Button variant="outline" size="sm" onClick={q.reload} aria-label="Refresh">
                <RefreshCwIcon className={cn(q.loading && "animate-spin")} /> Refresh
              </Button>
            </>
          }
        />
        {body}
      </Page>
    </div>
  );
}
