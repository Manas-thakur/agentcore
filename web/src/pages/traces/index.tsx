import * as React from "react";
import { cn } from "cn";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ClockIcon,
  CoinsIcon,
  CopyIcon,
  DownloadIcon,
  FilterIcon,
  OctagonXIcon,
  RefreshCwIcon,
  WaypointsIcon,
  XIcon,
} from "lucide-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";

import { EmptyState, ErrorState, SkeletonRows } from "@/components/app/common";
import { PeekHeader, SplitWithPeek } from "@/components/app/side-peek";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, ApiError, download, qs } from "@/lib/api";
import { fmtNum, fmtTime, plural } from "@/lib/format";
import { copyText, useKeydown, useMediaQuery } from "@/lib/hooks";
import { describe, fmtLatencyExpr, removeToken, selected, setValues, tokenize, validate } from "@/lib/query";
import { storage } from "@/lib/storage";
import type { ExploreResponse, TraceDetail as TraceDetailData, TraceSummary } from "@/lib/types";

import { activeFacetCount, Facets } from "./facets";
import { TraceHistogram } from "./histogram";
import { QueryBar } from "./query-bar";
import { TraceDetail, TraceStatusIcon, MetaPills, type TraceDetailHandle } from "./trace-detail";
import { TracesTable, type SortKey } from "./traces-table";

const PAGE = 100;
const RANGES = [
  { id: "1h", label: "1h", secs: 3600 },
  { id: "24h", label: "24h", secs: 86400 },
  { id: "7d", label: "7d", secs: 7 * 86400 },
  { id: "all", label: "All", secs: null },
] as const;
const SORTS: SortKey[] = ["time", "name", "status", "latency", "tokens", "cost", "model"];

const traceCache = new Map<string, TraceDetailData>();

export default function TracesPage() {
  const { traceId } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const openId = traceId || null;

  // URL is the source of truth for filters, sort, time window, open trace and tab.
  const query = params.get("query") ?? storage.get<string>("traces.query", "") ?? "";
  const since = params.get("since") ? Number(params.get("since")) : null;
  const until = params.get("until") ? Number(params.get("until")) : null;
  const range = params.get("range") || (since || until ? null : storage.get<string>("traces.range", "all"));
  const sortParam = params.get("sort") as SortKey | null;
  const sort: SortKey = sortParam && SORTS.includes(sortParam) ? sortParam : "time";
  const order = params.get("order") === "asc" ? "asc" : "desc";
  const tab = Number(params.get("tab") || 0) || 0;

  const update = React.useCallback(
    (patch: Partial<{ query: string; since: number | null; until: number | null; range: string | null; sort: SortKey; order: string; tab: number; open: string | null }>) => {
      const cur = {
        query,
        since,
        until,
        range,
        sort,
        order,
        tab,
        open: openId,
        ...patch,
      };
      if ("query" in patch) storage.set("traces.query", cur.query || null);
      if ("range" in patch) storage.set("traces.range", cur.range || "all");
      const search = qs({
        query: cur.query || null,
        range: cur.range && cur.range !== "all" && !cur.since && !cur.until ? cur.range : null,
        since: cur.since ? Math.round(cur.since) : null,
        until: cur.until ? Math.round(cur.until) : null,
        sort: cur.sort !== "time" ? cur.sort : null,
        order: cur.order !== "desc" ? cur.order : null,
        tab: cur.open && cur.tab ? cur.tab : null,
      });
      navigate(`/traces${cur.open ? `/${encodeURIComponent(cur.open)}` : ""}${search}`, { replace: true });
    },
    [query, since, until, range, sort, order, tab, openId, navigate],
  );

  const [draft, setDraft] = React.useState(query);
  React.useEffect(() => setDraft(query), [query]);
  const [data, setData] = React.useState<ExploreResponse | null>(null);
  const [rows, setRows] = React.useState<TraceSummary[]>([]);
  const [error, setError] = React.useState<Error | null>(null);
  const [queryError, setQueryError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [active, setActive] = React.useState(-1);
  const [tick, setTick] = React.useState(0);
  const [facetsSheet, setFacetsSheet] = React.useState(false);
  const qRef = React.useRef<HTMLInputElement>(null);
  const wide = useMediaQuery("(min-width: 1024px)");

  const window_ = React.useMemo(() => {
    if (since || until) return { since, until };
    const r = RANGES.find((x) => x.id === range);
    return r && r.secs ? { since: Date.now() / 1000 - r.secs, until: null } : { since: null, until: null };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [since, until, range, tick]);

  // Live validation of the draft as you type (debounced apply).
  React.useEffect(() => {
    const invalid = validate(draft);
    setQueryError(invalid);
    if (invalid || draft.trim() === query) return;
    const id = setTimeout(() => update({ query: draft.trim() }), 400);
    return () => clearTimeout(id);
  }, [draft, query, update]);

  const load = React.useCallback(
    async (append: boolean, signal?: AbortSignal) => {
      if (validate(query)) return;
      setLoading(true);
      try {
        const res = await api.get<ExploreResponse>(
          `/api/traces/explore${qs({
            query: query || null,
            since: window_.since,
            until: window_.until,
            sort,
            order,
            limit: PAGE,
            offset: append ? rows.length : 0,
          })}`,
          { signal },
        );
        setData(res);
        setRows((prev) => (append ? [...prev, ...res.items] : res.items));
        setError(null);
        setQueryError(null);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        if (err instanceof ApiError && err.status === 400) setQueryError(err.message);
        else setError(err as Error);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [query, window_, sort, order, rows.length],
  );

  React.useEffect(() => {
    const ctrl = new AbortController();
    void load(false, ctrl.signal);
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, window_, sort, order]);

  // Palette shortcut: /traces?chip=slow applies the p95 latency filter once stats are in.
  React.useEffect(() => {
    if (params.get("chip") === "slow" && data?.stats.p95_ms) {
      update({ query: `${query} latency:${fmtLatencyExpr(data.stats.p95_ms)}`.trim() });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  React.useEffect(() => {
    if (openId) setActive(rows.findIndex((r) => r.trace_id === openId));
  }, [openId, rows]);

  // --- detail -------------------------------------------------------------------------------
  const [detail, setDetail] = React.useState<TraceDetailData | null>(null);
  const [detailError, setDetailError] = React.useState<Error | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);
  const detailRef = React.useRef<TraceDetailHandle>(null);
  React.useEffect(() => {
    if (!openId) {
      setDetail(null);
      return;
    }
    const cached = traceCache.get(openId);
    if (cached) {
      setDetail(cached);
      setDetailError(null);
      return;
    }
    const ctrl = new AbortController();
    setDetailLoading(true);
    api
      .get<TraceDetailData>(`/api/traces/${encodeURIComponent(openId)}`, { signal: ctrl.signal })
      .then((d) => {
        traceCache.set(openId, d);
        if (traceCache.size > 40) traceCache.delete(traceCache.keys().next().value!);
        setDetail(d);
        setDetailError(null);
      })
      .catch((e: Error) => e.name !== "AbortError" && setDetailError(e))
      .finally(() => !ctrl.signal.aborted && setDetailLoading(false));
    return () => ctrl.abort();
  }, [openId]);

  const open = (i: number) => {
    setActive(i);
    const t = rows[i];
    if (t) update({ open: t.trace_id });
  };
  const close = () => update({ open: null, tab: 0 });
  const move = (delta: number) => {
    if (!rows.length) return;
    const next = active < 0 ? (delta > 0 ? 0 : rows.length - 1) : Math.max(0, Math.min(rows.length - 1, active + delta));
    setActive(next);
    if (openId) update({ open: rows[next].trace_id });
    else
      requestAnimationFrame(() =>
        document.querySelectorAll<HTMLElement>("[aria-label=Traces] tbody tr")[next]?.focus({ preventScroll: true }),
      );
  };

  useKeydown(
    (ev) => {
      if (ev.key === "Escape") {
        if (openId) {
          ev.preventDefault();
          close();
        }
        return;
      }
      const t = ev.target as HTMLElement;
      if (ev.key === "/") {
        ev.preventDefault();
        qRef.current?.focus();
        qRef.current?.select();
      } else if (ev.key === "j" || (ev.key === "ArrowDown" && !t.closest("[role=tree]"))) {
        ev.preventDefault();
        move(1);
      } else if (ev.key === "k" || (ev.key === "ArrowUp" && !t.closest("[role=tree]"))) {
        ev.preventDefault();
        move(-1);
      } else if (ev.key === "Enter" && !t.closest("button, a, input, [role=tree], [role=tab], [role=separator]")) {
        if (active >= 0 && rows[active]) {
          ev.preventDefault();
          open(active);
        }
      } else if (openId && ["1", "2", "3"].includes(ev.key)) {
        ev.preventDefault();
        update({ tab: Number(ev.key) - 1 });
      } else if (ev.key === "r") {
        setTick((x) => x + 1);
      }
    },
  );

  const setQuery = (q: string) => {
    setDraft(q);
    update({ query: q.trim() });
  };

  // --- quick chips --------------------------------------------------------------------------
  const stats = data?.stats;
  const statusSel = selected(query, "status");
  const errorsOn = statusSel.length === 1 && statusSel[0] === "error";
  const latTok = tokenize(query).find((t) => t.key === "latency" && !t.neg && t.value.startsWith(">"));
  const p95 = stats?.p95_ms ? fmtLatencyExpr(stats.p95_ms) : null;
  const costTok = tokenize(query).find((t) => (t.key === "cost" || t.key === "tokens") && !t.neg && t.value.startsWith(">"));
  const expensive = stats
    ? stats.p90_cost_usd > 0
      ? `cost:>${stats.p90_cost_usd}`
      : stats.p90_tokens > 0
        ? `tokens:>${Math.round(stats.p90_tokens)}`
        : null
    : null;
  const tokens = tokenize(query);
  const hasWindow = Boolean(since || until);
  const nFacets = activeFacetCount(query);
  const filtered = Boolean(query || hasWindow || (range && range !== "all"));

  const chips = (
    <div className="flex flex-wrap items-center gap-1.5">
      <Button
        variant={errorsOn ? "secondary" : "outline"}
        size="xs"
        aria-pressed={errorsOn}
        title="Only failed traces (status:error)"
        onClick={() => setQuery(setValues(query, "status", errorsOn ? [] : ["error"]))}
        className={cn(errorsOn && "border-destructive/40 text-destructive")}
      >
        <OctagonXIcon /> Errors
        {stats ? <span className="tabular text-muted-foreground">{fmtNum(stats.errors)}</span> : null}
      </Button>
      <Button
        variant={latTok ? "secondary" : "outline"}
        size="xs"
        aria-pressed={Boolean(latTok)}
        disabled={!p95 && !latTok}
        title={p95 ? `Slower than p95 (latency:${p95})` : "Slow traces"}
        onClick={() => setQuery(latTok ? removeToken(query, latTok.raw) : `${query} latency:${p95}`)}
      >
        <ClockIcon /> Slow
        <span className="tabular text-muted-foreground">
          {latTok ? latTok.value.slice(1) : p95 ? `p95 ${p95.slice(1)}` : ""}
        </span>
      </Button>
      <Button
        variant={costTok ? "secondary" : "outline"}
        size="xs"
        aria-pressed={Boolean(costTok)}
        disabled={!expensive && !costTok}
        title={expensive ? `Top 10% by ${expensive.startsWith("cost") ? "cost" : "tokens (no priced models)"}: ${expensive}` : "Expensive traces"}
        onClick={() => setQuery(costTok ? removeToken(query, costTok.raw) : `${query} ${expensive}`)}
      >
        <CoinsIcon /> Expensive
      </Button>
      {tokens.length || hasWindow ? <span className="mx-1 h-4 w-px bg-border" aria-hidden="true" /> : null}
      {hasWindow ? (
        <span className="inline-flex h-6 items-center gap-1 rounded-md border bg-card pr-0.5 pl-2 text-xs">
          <span className="text-muted-foreground">time</span>
          <span className="text-muted-foreground">between</span>
          <span className="font-medium">
            {fmtTime(since)} – {until ? fmtTime(until) : "now"}
          </span>
          <Button variant="ghost" size="icon-xs" aria-label="Clear time range" onClick={() => update({ since: null, until: null })}>
            <XIcon />
          </Button>
        </span>
      ) : null}
      {tokens.map((t) => {
        const d = describe(t);
        return (
          <span key={t.raw} className="inline-flex h-6 max-w-full items-center gap-1 rounded-md border bg-card pr-0.5 pl-2 text-xs">
            <span className="font-mono text-muted-foreground">{d.field}</span>
            <span className="text-muted-foreground">{d.op}</span>
            <span className="max-w-[12rem] truncate font-mono font-medium" title={d.value}>
              {d.value}
            </span>
            <Button variant="ghost" size="icon-xs" aria-label={`Remove filter ${t.raw}`} onClick={() => setQuery(removeToken(query, t.raw))}>
              <XIcon />
            </Button>
          </span>
        );
      })}
      {tokens.length + (hasWindow ? 1 : 0) > 1 ? (
        <Button variant="ghost" size="xs" onClick={() => {
          setDraft("");
          update({ query: "", since: null, until: null });
        }}>
          Clear all
        </Button>
      ) : null}
    </div>
  );

  const facetsEl = <Facets facets={data?.facets || {}} query={query} onQuery={setQuery} />;

  const main = (
    <div className="flex min-h-full">
      {wide ? (
        <aside aria-label="Filters" className="sticky top-0 hidden h-[calc(100svh-7.5rem)] w-56 shrink-0 overflow-y-auto border-r p-3 lg:block">
          {facetsEl}
        </aside>
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="border-b px-4 py-3">
          {data ? (
            <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
              <span>{plural(data.histogram.buckets.reduce((a, b) => a + b.count, 0), "trace")} over time</span>
              {data.stats.errors ? (
                <span className="text-destructive">
                  · {fmtNum(data.histogram.buckets.reduce((a, b) => a + b.errors, 0))} failed
                </span>
              ) : null}
              <span className="ml-auto hidden sm:inline">Drag to zoom</span>
              {hasWindow ? (
                <Button variant="ghost" size="xs" onClick={() => update({ since: null, until: null })}>
                  Reset zoom
                </Button>
              ) : null}
            </div>
          ) : null}
          {data ? (
            <TraceHistogram
              buckets={data.histogram.buckets}
              start={data.histogram.start}
              end={data.histogram.end}
              bucketSeconds={data.histogram.bucket_seconds}
              onSelect={(a, b) => update({ since: a, until: b, range: null })}
            />
          ) : (
            <Skeleton className="h-28 w-full" />
          )}
        </div>
        <div aria-busy={loading}>
          {error ? (
            <div className="p-4">
              <ErrorState error={error} onRetry={() => setTick((t) => t + 1)} />
            </div>
          ) : !data ? (
            <div className="p-4">
              <SkeletonRows rows={10} />
            </div>
          ) : !rows.length ? (
            <div className="p-4">
              {filtered ? (
                <EmptyState
                  icon={FilterIcon}
                  title="No traces match"
                  description="Remove a filter, widen the time range, or check the query."
                >
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setDraft("");
                      update({ query: "", since: null, until: null, range: "all" });
                    }}
                  >
                    Clear filters
                  </Button>
                </EmptyState>
              ) : (
                <EmptyState
                  icon={WaypointsIcon}
                  title="No traces yet"
                  description="Every agent run writes a trace. Send a message in the Playground or run an eval suite."
                >
                  <Button asChild size="sm">
                    <Link to="/playground">Open Playground</Link>
                  </Button>
                </EmptyState>
              )}
            </div>
          ) : (
            <>
              <TracesTable
                rows={rows}
                sort={sort}
                order={order}
                onSort={(s, o) => update({ sort: s, order: o })}
                activeIndex={active}
                openId={openId}
                onOpen={open}
                p95={data.stats.p95_ms}
              />
              <div className="flex items-center justify-center gap-3 px-4 py-3 text-xs text-muted-foreground">
                {rows.length < data.total ? (
                  <>
                    Showing {fmtNum(rows.length)} of {fmtNum(data.total)}
                    <Button variant="outline" size="xs" onClick={() => void load(true)} disabled={loading}>
                      Load more
                    </Button>
                  </>
                ) : rows.length > 12 ? (
                  `All ${fmtNum(data.total)} traces shown`
                ) : null}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );

  const pos = detail ? rows.findIndex((r) => r.trace_id === detail.trace_id) : -1;
  const peek = (
    <>
      <PeekHeader
        onClose={close}
        actions={
          detail ? (
            <div className="flex items-center gap-0.5">
              <span className="mr-1 hidden text-xs text-muted-foreground tabular sm:inline">{pos >= 0 ? `${pos + 1}/${data?.total ?? rows.length}` : ""}</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon-sm" disabled={pos <= 0} onClick={() => move(-1)} aria-label="Previous trace (K)">
                    <ChevronUpIcon />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Previous (K)</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    disabled={pos < 0 || pos >= rows.length - 1}
                    onClick={() => move(1)}
                    aria-label="Next trace (J)"
                  >
                    <ChevronDownIcon />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Next (J)</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Copy trace id"
                    onClick={() => copyText(detail.trace_id).then((ok) => ok && toast.success("Trace id copied"))}
                  >
                    <CopyIcon />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Copy id</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Export trace as JSON"
                    onClick={() =>
                      download(`/api/traces/${detail.trace_id}/export`, `trace-${detail.trace_id}.json`).catch((e: Error) =>
                        toast.error(`Export failed: ${e.message}`),
                      )
                    }
                  >
                    <DownloadIcon />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Export JSON</TooltipContent>
              </Tooltip>
            </div>
          ) : null
        }
      >
        <TraceStatusIcon status={detail?.summary?.status} loading={detailLoading && !detail} />
        <h2 className="truncate text-sm font-semibold" title={detail?.summary?.name}>
          {detail?.summary?.name || openId?.slice(0, 12) || "Trace"}
        </h2>
        {detail ? <span className="hidden font-mono text-xs text-muted-foreground sm:inline">{detail.trace_id.slice(0, 8)}</span> : null}
      </PeekHeader>
      {detailError ? (
        <div className="p-4">
          {detailError instanceof ApiError && detailError.status === 404 ? (
            <EmptyState
              icon={WaypointsIcon}
              title="Trace not found"
              description={`No trace matches "${openId}". It may have been deleted from the trace directory.`}
            />
          ) : (
            <ErrorState error={detailError} onRetry={() => navigate(0)} />
          )}
        </div>
      ) : !detail ? (
        <div className="space-y-3 p-4">
          <Skeleton className="h-6 w-2/3" />
          <SkeletonRows rows={8} />
        </div>
      ) : (
        <>
          <div className="shrink-0 space-y-3 border-b p-3">
            <MetaPills data={detail} />
            {detail.summary?.error ? (
              <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs break-words text-destructive" role="alert">
                <strong>Error</strong> {detail.summary.error}
              </p>
            ) : null}
          </div>
          <TraceDetail ref={detailRef} data={detail} tab={tab} onTab={(i) => update({ tab: i })} />
        </>
      )}
    </>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-2 border-b px-4 pt-3 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-base font-semibold">Traces</h1>
          {data ? (
            <span className="text-xs text-muted-foreground tabular" aria-live="polite">
              {fmtNum(data.total)} of {plural(data.stats.count, "trace")}
            </span>
          ) : null}
          <div className="ml-auto flex items-center gap-1.5">
            {!wide ? (
              <Button variant="outline" size="sm" onClick={() => setFacetsSheet(true)} aria-expanded={facetsSheet}>
                <FilterIcon /> Filters{nFacets ? ` (${nFacets})` : ""}
              </Button>
            ) : null}
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={hasWindow ? "" : range || "all"}
              onValueChange={(v) => v && update({ range: v, since: null, until: null })}
              aria-label="Time range"
            >
              {RANGES.map((r) => (
                <ToggleGroupItem key={r.id} value={r.id} className="px-2.5 text-xs">
                  {r.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" onClick={() => setTick((t) => t + 1)} aria-label="Refresh (R)">
                  <RefreshCwIcon className={cn(loading && "animate-spin")} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Refresh (R)</TooltipContent>
            </Tooltip>
          </div>
        </div>
        <QueryBar
          value={draft}
          onChange={setDraft}
          onApply={(v) => {
            if (!validate(v)) update({ query: v.trim() });
          }}
          facets={data?.facets || {}}
          error={queryError}
          inputRef={qRef}
        />
        {chips}
      </div>
      <div className="min-h-0 flex-1">
        <SplitWithPeek id="traces" label="Trace detail" main={main} peek={peek} open={Boolean(openId)} onClose={close} />
      </div>
      <Sheet open={!wide && facetsSheet} onOpenChange={setFacetsSheet}>
        <SheetContent side="bottom" className="max-h-[80svh] gap-0">
          <SheetHeader>
            <SheetTitle>Filters</SheetTitle>
            <SheetDescription>Pick values to filter by; the query bar shows the full filter.</SheetDescription>
          </SheetHeader>
          <div className="overflow-y-auto px-4 pb-6">{facetsEl}</div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
