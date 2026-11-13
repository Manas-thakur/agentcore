import * as React from "react";
import { cn } from "cn";
import {
  ArrowDownIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  FlagIcon,
  FlaskConicalIcon,
  PlayIcon,
  RefreshCwIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { toast } from "sonner";

import { ModelSelector } from "@/components/ai/model-selector";
import { StackTrace } from "@/components/ai/stack-trace";
import { EmptyState, ErrorState, Panel, Pill, SectionTitle, SkeletonRows } from "@/components/app/common";
import { PeekHeader, SplitWithPeek } from "@/components/app/side-peek";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Trace } from "@/components/ui/trace";
import { api, ApiError, qs } from "@/lib/api";
import { fmtMs, fmtNum, fmtPct, isoAgo, plural, shortWhen } from "@/lib/format";
import { useFetch, useKeydown, useStored } from "@/lib/hooks";
import type { EvalMatrix, EvalRunDetail, EvalRunInfo, EvalSuite, ModelInfo } from "@/lib/types";

import { cellTone, Figure, PassBadge, RunQueue, TestResults, Trajectory } from "./parts";

const runCache = new Map<string, EvalRunDetail>();

async function getRun(id: string, fresh = false): Promise<EvalRunDetail> {
  if (!fresh && runCache.has(id)) return runCache.get(id)!;
  const r = await api.get<EvalRunDetail>(`/api/evals/runs/${encodeURIComponent(id)}`);
  if (r.status === "completed" || r.status === "failed") runCache.set(id, r);
  return r;
}

function DiffBanner({ run }: { run: EvalRunDetail }) {
  if (run.is_baseline)
    return (
      <Alert>
        <FlagIcon />
        <AlertTitle>This run is the baseline</AlertTitle>
        <AlertDescription>Later runs are compared against it.</AlertDescription>
      </Alert>
    );
  if (!run.diff)
    return (
      <Alert>
        <FlagIcon />
        <AlertTitle>No baseline yet</AlertTitle>
        <AlertDescription>Use “Set baseline” in the run history to compare future runs against one.</AlertDescription>
      </Alert>
    );
  const d = run.diff;
  if (d.has_regressions)
    return (
      <Alert variant="destructive">
        <TriangleAlertIcon />
        <AlertTitle>
          Regression vs baseline: pass rate {fmtPct(d.baseline_pass_rate)} → {fmtPct(d.current_pass_rate)}
        </AlertTitle>
        <AlertDescription>
          <ul className="list-disc pl-4">
            {d.new_failures.map((n) => (
              <li key={n}>
                <strong className="font-mono">{n}</strong> passed in the baseline and now fails
              </li>
            ))}
            {d.regressions.map((c) => (
              <li key={`${c.case}-${c.metric}`}>
                <strong className="font-mono">{c.case}</strong> {c.metric}: {c.baseline.toFixed(2)} → {c.current.toFixed(2)} (
                {c.delta.toFixed(2)})
              </li>
            ))}
          </ul>
        </AlertDescription>
      </Alert>
    );
  const extra: string[] = [];
  if (d.fixed.length) extra.push(`fixed: ${d.fixed.join(", ")}`);
  if (d.improvements.length) extra.push(plural(d.improvements.length, "metric improvement"));
  if (d.new_cases.length) extra.push(`new cases: ${d.new_cases.join(", ")}`);
  return (
    <Alert className="border-success/30">
      <FlagIcon className="text-success" />
      <AlertTitle>No regressions vs baseline</AlertTitle>
      <AlertDescription>
        Pass rate {fmtPct(d.baseline_pass_rate)} → {fmtPct(d.current_pass_rate)}
        {extra.length ? ` · ${extra.join(" · ")}` : ""}
      </AlertDescription>
    </Alert>
  );
}

function Matrix({
  matrix,
  selectedRun,
  openCell,
  onPickRun,
  onOpenCell,
}: {
  matrix: EvalMatrix;
  selectedRun: string | null;
  openCell: { case: string; runId: string } | null;
  onPickRun: (id: string) => void;
  onOpenCell: (caseName: string, runId: string) => void;
}) {
  const wrapRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (wrapRef.current) wrapRef.current.scrollLeft = wrapRef.current.scrollWidth;
  }, [matrix]);
  const onKeyDown = (ev: React.KeyboardEvent) => {
    const b = (ev.target as HTMLElement).closest<HTMLElement>("[data-r]");
    if (!b) return;
    let r = Number(b.dataset.r);
    let c = Number(b.dataset.c);
    if (ev.key === "ArrowRight") c++;
    else if (ev.key === "ArrowLeft") c--;
    else if (ev.key === "ArrowDown") r++;
    else if (ev.key === "ArrowUp") r--;
    else return;
    ev.preventDefault();
    const next = wrapRef.current?.querySelector<HTMLButtonElement>(`[data-r="${r}"][data-c="${c}"]`);
    if (next) {
      wrapRef.current?.querySelectorAll<HTMLElement>("[data-r]").forEach((x) => (x.tabIndex = -1));
      next.tabIndex = 0;
      next.focus();
      if (openCell && !next.disabled) next.click();
    }
  };
  if (!matrix.runs.length)
    return (
      <p className="text-sm text-muted-foreground">
        Completed runs appear here as columns, oldest on the left. Run the suite a couple of times to compare.
      </p>
    );
  return (
    <div ref={wrapRef} className="overflow-x-auto" onKeyDown={onKeyDown}>
      <table className="w-full border-separate border-spacing-1 text-xs" aria-label="Eval results by case and run">
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 z-10 bg-card px-2 text-left font-medium text-muted-foreground">
              Case
            </th>
            {matrix.runs.map((r) => (
              <th key={r.id} scope="col" className="min-w-[5.5rem] p-0 font-normal">
                <button
                  type="button"
                  aria-pressed={r.id === selectedRun}
                  title={`${r.id} · ${r.model} · ${isoAgo(r.started_at)}`}
                  onClick={() => onPickRun(r.id)}
                  className="flex w-full flex-col items-center gap-0.5 rounded-md border border-transparent px-1.5 py-1 hover:bg-muted aria-pressed:border-brand/50 aria-pressed:bg-brand/5"
                >
                  <span className="text-muted-foreground tabular">{shortWhen(r.started_at)}</span>
                  <span className="max-w-[6rem] truncate font-mono text-[11px]">{r.model}</span>
                  <span className="font-medium tabular">{fmtPct(r.summary?.pass_rate)}</span>
                  {r.is_baseline ? (
                    <Badge variant="outline" className="h-4 px-1 text-[9px] tracking-wide">
                      BASELINE
                    </Badge>
                  ) : null}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.cases.map((row, ri) => (
            <tr key={row.case}>
              <th scope="row" className="sticky left-0 z-10 max-w-[14rem] bg-card px-2 text-left font-normal">
                <span className="block truncate font-mono text-xs text-foreground">{row.case}</span>
                {row.tags?.length ? <span className="block truncate text-[11px] text-muted-foreground">{row.tags.join(", ")}</span> : null}
              </th>
              {matrix.runs.map((r, ci) => {
                const c = row.cells[ci];
                const reg = Boolean(c && (c.regressed || c.baseline_regressed));
                const isOpen = openCell?.case === row.case && openCell.runId === r.id;
                const label = c
                  ? `${row.case} in run ${shortWhen(r.started_at)}: ${c.passed ? "passed" : "failed"}, score ${c.score.toFixed(2)}${c.regressed ? ", regressed vs previous run" : ""}${c.baseline_regressed ? ", regressed vs baseline" : ""}`
                  : `${row.case}: not in this run`;
                return (
                  <td key={r.id} className="p-0">
                    <button
                      type="button"
                      data-r={ri}
                      data-c={ci}
                      tabIndex={ri === 0 && ci === matrix.runs.length - 1 ? 0 : -1}
                      aria-label={label}
                      title={c && c.failing.length ? `failing: ${c.failing.join(", ")}` : undefined}
                      disabled={!c}
                      onClick={() => c && onOpenCell(row.case, r.id)}
                      className={cn(
                        "flex h-8 w-full items-center justify-center gap-1 rounded-md font-medium tabular transition-shadow outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        cellTone(c),
                        reg && "ring-2 ring-destructive ring-inset",
                        isOpen && "ring-2 ring-brand",
                      )}
                    >
                      {reg ? <ArrowDownIcon className="size-3" aria-hidden="true" /> : null}
                      {c ? (c.passed ? "pass" : c.score.toFixed(2)) : "–"}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function EvalsPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [storedSuite, setStoredSuite] = useStored<string | null>("evals.suite", null);
  const [evalModel, setEvalModel] = useStored("evals.model", "");
  const suitePath = params.get("suite") || storedSuite;
  const runParam = params.get("run");

  const suitesQ = useFetch<EvalSuite[]>("/api/evals/suites");
  const modelsQ = useFetch<{ data: ModelInfo[] }>("/v1/models");
  const suites = suitesQ.data || [];
  const suite = suites.find((s) => s.path === suitePath && !s.error) || suites.find((s) => !s.error) || null;
  const [creating, setCreating] = React.useState(false);

  const setUrl = React.useCallback(
    (suiteP: string | null, run: string | null) => navigate(`/evals${qs({ suite: suiteP, run })}`, { replace: true }),
    [navigate],
  );

  const matrixQ = useFetch<EvalMatrix>(suite ? `/api/evals/matrix${qs({ suite: suite.name, limit: 10 })}` : null);
  const historyQ = useFetch<EvalRunInfo[]>(suite ? `/api/evals/runs${qs({ suite: suite.name })}` : null);

  const runId = runParam || suite?.last_run?.id || null;
  const [run, setRun] = React.useState<EvalRunDetail | null>(null);
  const [runError, setRunError] = React.useState<Error | null>(null);
  const [starting, setStarting] = React.useState(false);
  const wasRunning = React.useRef(false);
  const [openCell, setOpenCell] = React.useState<{ case: string; runId: string } | null>(null);

  React.useEffect(() => {
    if (suite && suite.path !== storedSuite) setStoredSuite(suite.path);
  }, [suite, storedSuite, setStoredSuite]);

  // Load the selected run; poll while it is queued or running.
  React.useEffect(() => {
    if (!runId) {
      setRun(null);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async (fresh: boolean) => {
      try {
        const r = await getRun(runId, fresh);
        if (!alive) return;
        setRun(r);
        setRunError(null);
        if (r.status === "queued" || r.status === "running") {
          wasRunning.current = true;
          timer = setTimeout(() => tick(true), 600);
        } else if (wasRunning.current) {
          wasRunning.current = false;
          if (r.status === "completed") toast.success(`Run finished: ${r.summary?.passed}/${r.summary?.cases} passed`);
          else toast.error(`Run failed: ${r.error || "unknown error"}`);
          suitesQ.reload();
          matrixQ.reload();
          historyQ.reload();
        }
      } catch (e) {
        if (alive) setRunError(e as Error);
      }
    };
    void tick(!runCache.has(runId));
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  useKeydown((ev) => {
    if (ev.key === "Escape" && openCell) {
      ev.preventDefault();
      setOpenCell(null);
    }
  });

  const startRun = async () => {
    if (!suite) return;
    setStarting(true);
    try {
      const job = await api.post<EvalRunInfo>("/api/evals/runs", { suite: suite.path, model: evalModel || null });
      setUrl(suite.path, job.id);
      historyQ.reload();
    } catch (err) {
      toast.error(`Could not start the run: ${(err as Error).message}`);
    } finally {
      setStarting(false);
    }
  };

  const setBaseline = async (id: string) => {
    try {
      await api.post(`/api/evals/runs/${id}/baseline`);
      toast.success("Baseline updated");
      runCache.clear();
      suitesQ.reload();
      historyQ.reload();
      matrixQ.reload();
      if (runId) setRun(await getRun(runId, true));
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const createStarter = async () => {
    setCreating(true);
    try {
      const made = await api.post<{ path: string; name: string }>("/api/evals/starter", {});
      toast.success(`Created ${made.path}`);
      suitesQ.reload();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setCreating(false);
    }
  };

  // --- case peek ------------------------------------------------------------------------------
  const [peekRun, setPeekRun] = React.useState<EvalRunDetail | null>(null);
  const [peekError, setPeekError] = React.useState<Error | null>(null);
  React.useEffect(() => {
    if (!openCell) return;
    let alive = true;
    setPeekRun(null);
    getRun(openCell.runId)
      .then((r) => alive && (setPeekRun(r), setPeekError(null)))
      .catch((e: Error) => alive && setPeekError(e));
    return () => {
      alive = false;
    };
  }, [openCell]);

  const matrix = matrixQ.data && suite && matrixQ.data.suite === suite.name ? matrixQ.data : null;
  const running = run && (run.status === "queued" || run.status === "running");
  const sm = run?.summary;

  const suiteList = (
    <nav aria-label="Eval suites" className="space-y-1">
      <SectionTitle className="px-1 pb-1">Suites · {suites.length}</SectionTitle>
      {suites.map((s) => (
        <button
          key={s.path}
          type="button"
          disabled={Boolean(s.error)}
          aria-current={suite?.path === s.path ? "true" : undefined}
          title={s.error || s.description || s.name}
          onClick={() => {
            setOpenCell(null);
            setUrl(s.path, null);
          }}
          className="flex w-full flex-col gap-1 rounded-lg border border-transparent px-2.5 py-2 text-left transition-colors hover:bg-muted disabled:opacity-60 aria-[current=true]:border-border aria-[current=true]:bg-card aria-[current=true]:shadow-xs"
        >
          <span className="truncate text-sm font-medium">{s.name}</span>
          <span className="truncate font-mono text-[11px] text-muted-foreground">{s.path}</span>
          <span className="flex flex-wrap gap-1">
            <Badge variant="outline" className="font-normal">
              {plural(s.cases, "case")}
            </Badge>
            {s.error ? <Badge variant="destructive">invalid</Badge> : null}
            {s.last_run?.summary ? <PassBadge rate={s.last_run.summary.pass_rate} /> : null}
            {s.baseline ? (
              <Badge variant="outline" className="border-brand/40 font-normal text-brand">
                baseline
              </Badge>
            ) : null}
          </span>
        </button>
      ))}
    </nav>
  );

  let body: React.ReactNode;
  if (suitesQ.error) body = <ErrorState error={suitesQ.error} onRetry={suitesQ.reload} />;
  else if (!suitesQ.data) body = <SkeletonRows rows={8} />;
  else if (!suites.length)
    body = (
      <EmptyState
        icon={FlaskConicalIcon}
        title="No eval suites yet"
        description={
          <>
            Create a three-case calculator suite to see how runs, scores and baselines work, or add your own YAML suites
            to <code className="font-mono">./evals</code> (configurable as <code className="font-mono">eval_dirs</code> in{" "}
            <code className="font-mono">agentcore.toml</code>).
          </>
        }
      >
        <Button onClick={createStarter} disabled={creating}>
          Create starter suite
        </Button>
      </EmptyState>
    );
  else if (!suite)
    body = <EmptyState icon={FlaskConicalIcon} title="No runnable suites" description="Every suite file found has errors. Fix them and rescan." />;
  else
    body = (
      <div className="grid gap-6 @4xl:grid-cols-[15rem_minmax(0,1fr)]">
        <div className="hidden min-w-0 @4xl:block">{suiteList}</div>
        <div className="@4xl:hidden">
          <Select
            value={suite.path}
            onValueChange={(v) => {
              setOpenCell(null);
              setUrl(v, null);
            }}
          >
            <SelectTrigger aria-label="Eval suite" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {suites.map((s) => (
                <SelectItem key={s.path} value={s.path} disabled={Boolean(s.error)}>
                  {s.name} · {plural(s.cases, "case")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="min-w-0 space-y-4">
          <Panel
            title={suite.name}
            description={suite.description}
            actions={(suite.tools || []).map((t) => (
              <Badge key={t} variant="secondary" className="font-mono font-normal">
                {t}
              </Badge>
            ))}
          >
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void startRun();
              }}
            >
              <div className="min-w-0 flex-1 basis-56 space-y-1.5 sm:max-w-sm">
                <label htmlFor="ev-model" className="text-xs font-medium">
                  Model
                </label>
                <ModelSelector
                  id="ev-model"
                  value={evalModel}
                  onChange={setEvalModel}
                  models={modelsQ.data?.data || []}
                  defaultModel={suite.model || modelsQ.data?.data.find((m) => m.default)?.id}
                  className="w-full"
                  size="default"
                />
              </div>
              <Button type="submit" disabled={starting || Boolean(running)}>
                <PlayIcon /> {running ? "Running…" : "Run suite"}
              </Button>
              <span className="text-xs text-muted-foreground">
                {plural(suite.cases, "case")} · each case gets a fresh agent
              </span>
            </form>
          </Panel>

          <Panel
            title="Results matrix"
            description={
              matrix?.runs.length
                ? `${plural(matrix.cases.length, "case")} × last ${plural(matrix.runs.length, "run")}${matrix.regressions ? ` · ${plural(matrix.regressions, "regression")}` : ""}`
                : undefined
            }
            actions={
              <div className="flex items-center gap-3 text-xs text-muted-foreground" aria-hidden="true">
                <span className="flex items-center gap-1">
                  <i className="size-2.5 rounded-sm bg-success/40" /> pass
                </span>
                <span className="flex items-center gap-1">
                  <i className="size-2.5 rounded-sm bg-destructive/40" /> fail
                </span>
                <span className="flex items-center gap-1">
                  <i className="size-2.5 rounded-sm ring-2 ring-destructive ring-inset" /> regressed
                </span>
              </div>
            }
          >
            {matrixQ.error ? (
              <ErrorState error={matrixQ.error} onRetry={matrixQ.reload} />
            ) : !matrix ? (
              <SkeletonRows rows={3} />
            ) : (
              <Matrix
                matrix={matrix}
                selectedRun={runId}
                openCell={openCell}
                onPickRun={(id) => setUrl(suite.path, id)}
                onOpenCell={(c, r) => setOpenCell({ case: c, runId: r })}
              />
            )}
          </Panel>

          {!runId ? (
            <EmptyState
              icon={PlayIcon}
              title="Not run yet"
              description="Pick a model and run the suite. Each case gets a fresh agent; results stream in as cases finish."
            />
          ) : runError ? (
            runError instanceof ApiError && runError.status === 404 ? (
              <EmptyState title="Run not found" description="It may have been removed from the state directory." />
            ) : (
              <ErrorState error={runError} />
            )
          ) : !run ? (
            <Panel title="Selected run">
              <SkeletonRows rows={4} />
            </Panel>
          ) : (
            <Panel
              title={running ? "Running…" : "Selected run"}
              description={
                <span className="font-mono">
                  {run.model} · {isoAgo(run.started_at)}
                </span>
              }
              actions={
                <>
                  {run.is_baseline ? (
                    <Badge variant="outline" className="border-brand/40 text-brand">
                      baseline
                    </Badge>
                  ) : null}
                  {running ? (
                    <Badge variant="secondary" className="tabular">
                      {run.done}/{run.total}
                    </Badge>
                  ) : run.status === "failed" ? (
                    <Badge variant="destructive">failed</Badge>
                  ) : (
                    <PassBadge rate={sm?.pass_rate} />
                  )}
                </>
              }
              bodyClassName="space-y-4"
            >
              {running ? (
                <>
                  <div className="space-y-1.5">
                    <Progress value={run.total ? (run.done / run.total) * 100 : 0} aria-label="Cases finished" />
                    <p className="text-xs text-muted-foreground tabular">
                      {run.done} of {run.total} cases finished · {run.passed} passed
                      {run.elapsed_s ? ` · ${run.elapsed_s}s` : ""}
                    </p>
                  </div>
                  <RunQueue run={run} caseNames={suite.case_names || []} />
                </>
              ) : null}
              {run.status === "failed" ? (
                <Trace>
                  <StackTrace error={run.error || "unknown error"} label="Run failed" />
                </Trace>
              ) : null}
              {run.status === "completed" && sm ? (
                <>
                  <div className="grid grid-cols-2 gap-2 @2xl:grid-cols-4">
                    <Figure label="Pass rate" value={fmtPct(sm.pass_rate)} sub={`${sm.passed}/${sm.cases} cases`} />
                    <Figure
                      label="Mean score"
                      value={sm.mean_score?.toFixed(2) ?? "-"}
                      sub={
                        Object.entries(sm.metrics || {})
                          .map(([k, v]) => `${k} ${v.toFixed(2)}`)
                          .join(" · ") || "no metrics"
                      }
                    />
                    <Figure label="Tokens" value={fmtNum(sm.total_tokens)} sub="all cases" />
                    <Figure label="Agent time" value={fmtMs(sm.duration_ms)} sub="sum over cases" />
                  </div>
                  <DiffBanner run={run} />
                  {run.results?.length ? (
                    <TestResults
                      run={run}
                      openCase={openCell?.runId === run.id ? openCell.case : null}
                      onOpenCase={(c) => setOpenCell({ case: c, runId: run.id })}
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground">No case results.</p>
                  )}
                </>
              ) : null}
            </Panel>
          )}

          <Panel title="Run history" description={historyQ.data ? plural(historyQ.data.length, "run") : undefined} bodyClassName="p-0">
            {historyQ.error ? (
              <div className="p-4">
                <ErrorState error={historyQ.error} onRetry={historyQ.reload} />
              </div>
            ) : !historyQ.data ? (
              <div className="p-4">
                <SkeletonRows rows={3} />
              </div>
            ) : !historyQ.data.length ? (
              <p className="p-4 text-sm text-muted-foreground">No runs yet.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Started</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead>Pass rate</TableHead>
                    <TableHead className="text-right">Score</TableHead>
                    <TableHead className="hidden text-right md:table-cell">Tokens</TableHead>
                    <TableHead className="hidden text-right md:table-cell">Agent time</TableHead>
                    <TableHead className="text-right">
                      <span className="sr-only">Baseline</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {historyQ.data.map((r) => {
                    const s = r.summary;
                    return (
                      <TableRow
                        key={r.id}
                        data-state={r.id === runId ? "selected" : undefined}
                        tabIndex={0}
                        className="cursor-pointer"
                        onClick={() => setUrl(suite.path, r.id)}
                        onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && setUrl(suite.path, r.id)}
                      >
                        <TableCell className="whitespace-nowrap text-muted-foreground" title={r.started_at}>
                          {isoAgo(r.started_at)}
                        </TableCell>
                        <TableCell className="font-mono text-xs">{r.model}</TableCell>
                        <TableCell>
                          {r.status === "completed" ? (
                            <PassBadge rate={s?.pass_rate} />
                          ) : (
                            <Badge variant={r.status === "failed" ? "destructive" : "secondary"}>{r.status}</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular">{s?.mean_score !== undefined ? s.mean_score.toFixed(2) : "-"}</TableCell>
                        <TableCell className="hidden text-right tabular md:table-cell">{s ? fmtNum(s.total_tokens) : "-"}</TableCell>
                        <TableCell className="hidden text-right tabular md:table-cell">{s ? fmtMs(s.duration_ms) : "-"}</TableCell>
                        <TableCell className="text-right">
                          {r.is_baseline ? (
                            <Badge variant="outline" className="border-brand/40 text-brand">
                              baseline
                            </Badge>
                          ) : r.status === "completed" ? (
                            <Button
                              variant="outline"
                              size="xs"
                              onClick={(e) => {
                                e.stopPropagation();
                                void setBaseline(r.id);
                              }}
                            >
                              Set baseline
                            </Button>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </Panel>
        </div>
      </div>
    );

  // --- peek content -----------------------------------------------------------------------------
  const result = peekRun && openCell ? (peekRun.results || []).find((x) => x.case === openCell.case) : null;
  const ri = matrix && openCell ? matrix.cases.findIndex((c) => c.case === openCell.case) : -1;
  const ci = matrix && openCell ? matrix.runs.findIndex((x) => x.id === openCell.runId) : -1;
  const cell = ri >= 0 && ci >= 0 ? matrix!.cases[ri].cells[ci] : null;
  const runMeta = ci >= 0 ? matrix!.runs[ci] : null;
  const navCase = (dr: number) => {
    if (!matrix || !openCell) return;
    const list = ri >= 0 ? matrix.cases.map((c) => c.case) : (peekRun?.results || []).map((r) => r.case);
    const idx = list.indexOf(openCell.case) + dr;
    if (idx >= 0 && idx < list.length) setOpenCell({ case: list[idx], runId: openCell.runId });
  };
  const peek = openCell ? (
    <>
      <PeekHeader
        onClose={() => setOpenCell(null)}
        actions={
          <>
            <Button variant="ghost" size="icon-sm" aria-label="Previous case" onClick={() => navCase(-1)}>
              <ChevronUpIcon />
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label="Next case" onClick={() => navCase(1)}>
              <ChevronDownIcon />
            </Button>
          </>
        }
      >
        {result ? (
          result.passed ? (
            <Badge className="bg-success/15 text-success">pass</Badge>
          ) : (
            <Badge variant="destructive">fail</Badge>
          )
        ) : null}
        <h2 className="truncate font-mono text-sm font-semibold">{openCell.case}</h2>
      </PeekHeader>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        {peekError ? (
          <ErrorState error={peekError} />
        ) : !peekRun ? (
          <SkeletonRows rows={6} />
        ) : !result ? (
          <EmptyState title="Case not in this run" description="The suite changed since this run." />
        ) : (
          <>
            <div className="flex flex-wrap gap-1.5">
              <Pill label="Run" value={`${shortWhen(runMeta?.started_at || peekRun.started_at)}${(runMeta?.is_baseline ?? peekRun.is_baseline) ? " · baseline" : ""}`} />
              <Pill label="Model" value={peekRun.model} />
              <Pill label="Score" value={result.score.toFixed(2)} tone={result.passed ? undefined : "error"} />
              <Pill label="Steps" value={String(result.steps)} />
              <Pill label="Time" value={fmtMs(result.duration_ms)} />
              {result.usage ? <Pill label="Tokens" value={fmtNum(result.usage.total_tokens)} /> : null}
              {result.trace_id ? (
                <Pill label="Trace" value={result.trace_id.slice(0, 8)} href={`/traces/${result.trace_id}`} title="Open this case's agent trace" />
              ) : null}
            </div>
            {cell && (cell.regressed || cell.baseline_regressed) ? (
              <Alert variant="destructive">
                <TriangleAlertIcon />
                <AlertTitle>Regression</AlertTitle>
                <AlertDescription>
                  {[
                    cell.regressed ? "it got worse than the previous run" : null,
                    cell.baseline_regressed ? "it passed in the baseline and fails now" : null,
                  ]
                    .filter(Boolean)
                    .join("; ")}
                </AlertDescription>
              </Alert>
            ) : null}
            {ri >= 0 ? (
              <div className="flex flex-wrap items-center gap-1" aria-label="This case across recent runs">
                <span className="mr-1 text-xs text-muted-foreground">Across runs</span>
                {matrix!.cases[ri].cells.map((c, i) => (
                  <button
                    key={matrix!.runs[i].id}
                    type="button"
                    disabled={!c}
                    aria-current={i === ci ? "true" : undefined}
                    aria-label={`${shortWhen(matrix!.runs[i].started_at)}: ${c ? (c.passed ? "pass" : "fail") : "missing"}`}
                    onClick={() => c && setOpenCell({ case: openCell.case, runId: matrix!.runs[i].id })}
                    className={cn(
                      "h-6 min-w-8 rounded px-1.5 text-xs font-medium",
                      cellTone(c),
                      i === ci && "ring-2 ring-brand",
                    )}
                  >
                    {c ? (c.passed ? "✓" : "✗") : "–"}
                  </button>
                ))}
              </div>
            ) : null}
            <section className="space-y-1.5">
              <SectionTitle>Input</SectionTitle>
              <div className="rounded-lg border bg-card px-3 py-2 text-sm whitespace-pre-wrap">{result.input}</div>
            </section>
            <section className="space-y-1.5">
              <SectionTitle>Output</SectionTitle>
              <div className="rounded-lg border bg-card px-3 py-2 text-sm whitespace-pre-wrap">{result.output ?? "-"}</div>
            </section>
            {result.error ? (
              <Trace>
                <StackTrace error={result.error} label="Error" />
              </Trace>
            ) : null}
            <section className="space-y-1.5">
              <SectionTitle>
                Metrics · {result.metrics.filter((m) => m.passed).length}/{result.metrics.length} passed
              </SectionTitle>
              <ul className="divide-y rounded-lg border">
                {result.metrics.map((m) => (
                  <li key={m.name} className="flex items-start gap-2 px-3 py-2 text-sm">
                    <span className={cn("mt-0.5 size-2 shrink-0 rounded-full", m.passed ? "bg-success" : "bg-destructive")} />
                    <span className="min-w-0 flex-1">
                      <span className="font-mono text-xs font-medium">{m.name}</span>
                      {m.details ? <span className="block text-xs text-muted-foreground">{m.details}</span> : null}
                    </span>
                    <span className="text-xs tabular">{m.score.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="space-y-1.5">
              <SectionTitle>Trajectory</SectionTitle>
              <Trajectory result={result} />
            </section>
            {result.trace_id ? (
              <Button asChild variant="outline" size="sm">
                <Link to={`/traces/${result.trace_id}`}>Open the agent trace</Link>
              </Button>
            ) : null}
          </>
        )}
      </div>
    </>
  ) : null;

  return (
    <SplitWithPeek
      id="evals"
      label="Case detail"
      open={Boolean(openCell)}
      onClose={() => setOpenCell(null)}
      defaultSize={40}
      main={
        <div className="@container mx-auto w-full max-w-6xl space-y-6 p-4 md:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <h1 className="text-xl font-semibold tracking-tight">Evals</h1>
              <p className="max-w-2xl text-sm text-muted-foreground">
                Suites from the configured eval directories. Compare recent runs case by case; set a baseline to flag
                regressions.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={suitesQ.reload}>
              <RefreshCwIcon className={cn(suitesQ.loading && "animate-spin")} /> Rescan
            </Button>
          </div>
          {body}
        </div>
      }
      peek={peek}
    />
  );
}
