// Evals: discover suites, run one in the background, compare recent runs in a results matrix
// (cases x runs, regressions outlined; click a cell to peek at that case's trajectory), inspect a
// run against the baseline, and browse the run history.

import { api } from "../api.js";
import { createPeek } from "../peek.js";
import { argsList, resultBox } from "../trace-detail.js";
import {
  chip,
  clear,
  emptyState,
  errorState,
  fmtMs,
  fmtNum,
  fmtPct,
  h,
  icon,
  isoAgo,
  isTyping,
  loading,
  plural,
  store,
  toast,
} from "../ui.js";

function shortWhen(iso) {
  const t = Date.parse(iso || "");
  if (Number.isNaN(t)) return "-";
  const d = new Date(t);
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export async function render(root, { params }) {
  const main = h("div", { class: "page" });
  const peek = createPeek({ id: "evals", label: "Case detail", defaultWidth: 560, onClose: () => { openCell = null; markCells(); } });
  root.appendChild(h("div", { class: "page page--full" }, h("div", { class: "split" }, h("div", { class: "split-main" }, main), peek.el)));

  const refresh = h("button", { class: "btn", type: "button", html: `${icon("refresh")}<span>Rescan</span>` });
  main.appendChild(
    h(
      "div",
      { class: "page-head" },
      h("div", null, h("h1", null, "Evals"), h("p", { class: "lede" }, "Suites from the configured eval directories. Compare recent runs case by case; set a baseline to flag regressions.")),
      h("div", { class: "actions" }, refresh),
    ),
  );
  const listCol = h("nav", { class: "suite-list", "aria-label": "Eval suites" });
  const stack = h("div", { class: "ev-stack" });
  main.appendChild(h("div", { class: "ev-layout" }, listCol, stack));

  let suites = [];
  let models = [];
  let pollTimer = null;
  let disposed = false;
  let matrix = null;
  let openCell = null; // { case, runId }
  const runCache = new Map();
  const state = { suite: params.suite || store.get("evals.suite", null), run: params.run || null };
  const areas = {};

  function setQuery() {
    const q = new URLSearchParams();
    if (state.suite) q.set("suite", state.suite);
    if (state.run) q.set("run", state.run);
    history.replaceState(null, "", `#/evals${q.toString() ? `?${q}` : ""}`);
  }

  async function getRun(id, { fresh = false } = {}) {
    if (!fresh && runCache.has(id)) return runCache.get(id);
    const r = await api.get(`/api/evals/runs/${encodeURIComponent(id)}`);
    if (r.status === "completed" || r.status === "failed") runCache.set(id, r);
    return r;
  }

  async function loadSuites() {
    clear(listCol).appendChild(loading("Scanning for suites..."));
    try {
      suites = await api.get("/api/evals/suites");
    } catch (err) {
      clear(listCol).appendChild(errorState(err, loadSuites));
      clear(stack);
      return;
    }
    paintList();
    const current = suites.find((s) => s.path === state.suite && !s.error) || suites.find((s) => !s.error);
    if (current) selectSuite(current.path, state.run);
    else {
      clear(stack);
      if (suites.length) stack.appendChild(emptyState("No runnable suites", "Every suite file found has errors. Fix them and rescan."));
    }
  }

  function paintList() {
    clear(listCol);
    if (!suites.length) {
      const create = h("button", { class: "btn btn--primary btn--sm", type: "button" }, "Create starter suite");
      create.addEventListener("click", async () => {
        create.disabled = true;
        try {
          const made = await api.post("/api/evals/starter", {});
          toast(`Created ${made.path}`);
          await loadSuites();
        } catch (err) {
          create.disabled = false;
          toast(err.message || String(err), { kind: "err" });
        }
      });
      listCol.appendChild(
        emptyState(
          "No eval suites yet",
          "Create a three-case calculator suite to see how runs, scores and baselines work, or add your own YAML suites to ./evals (configurable as eval_dirs in agentcore.toml).",
          create,
        ),
      );
      return;
    }
    listCol.appendChild(h("div", { class: "suite-list-head" }, `Suites · ${suites.length}`));
    for (const s of suites) {
      const last = s.last_run;
      const meta = [chip(plural(s.cases, "case"))];
      if (s.error) meta.push(chip("invalid", "err"));
      if (last && last.summary) meta.push(chip(`${fmtPct(last.summary.pass_rate)} last`, last.summary.pass_rate === 1 ? "ok" : "err"));
      if (s.baseline) meta.push(chip("baseline", "accent"));
      listCol.appendChild(
        h(
          "button",
          {
            class: "suite",
            type: "button",
            "data-path": s.path,
            "aria-current": s.path === state.suite ? "true" : "false",
            disabled: !!s.error,
            title: s.error || s.description || s.name,
            onclick: () => selectSuite(s.path),
          },
          h("span", { class: "suite-name" }, s.name),
          h("span", { class: "suite-path" }, s.path),
          h("span", { class: "suite-meta" }, meta),
        ),
      );
    }
  }

  async function selectSuite(path, runId = null) {
    stopPolling();
    peek.close({ silent: true });
    openCell = null;
    state.suite = path;
    state.run = runId;
    store.set("evals.suite", path);
    setQuery();
    for (const b of listCol.querySelectorAll(".suite")) b.setAttribute("aria-current", b.dataset.path === path ? "true" : "false");
    const suite = suites.find((s) => s.path === path);
    if (!suite) return;
    clear(stack);

    const modelInput = h("input", { class: "input mono", id: "ev-model", list: "ev-models", placeholder: suite.model || "server default", spellcheck: "false", autocomplete: "off", value: store.get("evals.model", "") });
    const datalist = h("datalist", { id: "ev-models" }, models.map((m) => h("option", { value: m })));
    const runBtn = h("button", { class: "btn btn--primary", type: "submit", html: `${icon("play")}<span>Run suite</span>` });
    const form = h("form", { class: "run-bar" }, h("div", { class: "field" }, h("label", { class: "label", for: "ev-model" }, "Model"), modelInput, datalist), runBtn);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      runBtn.disabled = true;
      store.set("evals.model", modelInput.value.trim());
      try {
        const job = await api.post("/api/evals/runs", { suite: suite.path, model: modelInput.value.trim() || null });
        state.run = job.id;
        setQuery();
        await showRun(job.id);
        loadHistory(suite);
      } catch (err) {
        toast(`Could not start the run: ${err.message}`, { kind: "err" });
      } finally {
        runBtn.disabled = false;
      }
    });

    stack.appendChild(
      h(
        "section",
        { class: "panel" },
        h(
          "div",
          { class: "panel-head" },
          h("div", null, h("h2", null, suite.name), suite.description ? h("p", { class: "hint", style: { margin: 0 } }, suite.description) : null),
          h("div", { class: "actions" }, (suite.tools || []).map((t) => chip(t, "outline"))),
        ),
        h("div", { class: "panel-body" }, form),
      ),
    );
    areas.matrix = h("section", { class: "panel", "aria-labelledby": "mx-title" });
    areas.run = h("div");
    areas.history = h("section", { class: "panel" });
    stack.append(areas.matrix, areas.run, areas.history);
    loadMatrix(suite);
    loadHistory(suite);
    const target = runId || (suite.last_run && suite.last_run.id);
    if (target) showRun(target);
    else areas.run.appendChild(h("div", { class: "panel" }, emptyState("Not run yet", "Pick a model and run the suite. Each case gets a fresh agent; results stream in as cases finish.")));
  }

  // --- results matrix ---------------------------------------------------------------------------
  async function loadMatrix(suite) {
    const area = areas.matrix;
    if (!area) return;
    if (!matrix || matrix.suite !== suite.name) clear(area).append(h("div", { class: "panel-head" }, h("h2", { id: "mx-title" }, "Results matrix")), loading());
    try {
      matrix = await api.get(`/api/evals/matrix?suite=${encodeURIComponent(suite.name)}&limit=10`);
    } catch (err) {
      clear(area).appendChild(errorState(err, () => loadMatrix(suite)));
      return;
    }
    if (disposed) return;
    paintMatrix();
  }

  function cellClass(c) {
    if (!c) return "cell cell--none";
    let cls = c.passed ? "cell cell--pass" : c.score > 0 ? "cell cell--partial" : "cell cell--fail";
    if (c.regressed || c.baseline_regressed) cls += " is-regressed";
    return cls;
  }

  function paintMatrix() {
    const area = areas.matrix;
    clear(area);
    const m = matrix;
    const legend = h(
      "div",
      { class: "mx-legend" },
      h("span", null, h("i", { class: "p" }), "pass"),
      h("span", null, h("i", { class: "f" }), "fail"),
      h("span", null, h("i", { class: "r" }), "regressed"),
    );
    area.appendChild(
      h(
        "div",
        { class: "panel-head" },
        h("h2", { id: "mx-title" }, "Results matrix"),
        h("span", { class: "hint" }, m.runs.length ? `${plural(m.cases.length, "case")} × last ${plural(m.runs.length, "run")}${m.regressions ? ` · ${plural(m.regressions, "regression")}` : ""}` : ""),
        h("div", { class: "actions" }, legend),
      ),
    );
    if (!m.runs.length) {
      area.appendChild(h("p", { class: "hint", style: { padding: "var(--space-4)", margin: 0 } }, "Completed runs appear here as columns, oldest on the left. Run the suite a couple of times to compare."));
      return;
    }
    const head = h(
      "tr",
      null,
      h("th", { scope: "col" }, "Case"),
      m.runs.map((r) => {
        const sm = r.summary || {};
        return h(
          "th",
          { scope: "col" },
          h(
            "button",
            {
              class: "mx-col",
              type: "button",
              "aria-pressed": String(r.id === state.run),
              title: `${r.id} · ${r.model} · ${isoAgo(r.started_at)}`,
              onclick: () => {
                state.run = r.id;
                setQuery();
                showRun(r.id);
                paintMatrix();
              },
            },
            h("span", { class: "when" }, shortWhen(r.started_at)),
            h("span", { class: "mdl" }, r.model),
            h("span", { class: "rate" }, fmtPct(sm.pass_rate)),
            r.is_baseline ? h("span", { class: "base" }, "BASELINE") : null,
          ),
        );
      }),
    );
    const tbody = h("tbody");
    m.cases.forEach((row, ri) => {
      tbody.appendChild(
        h(
          "tr",
          null,
          h("th", { scope: "row" }, row.case, row.tags && row.tags.length ? h("span", { class: "tags" }, row.tags.join(", ")) : null),
          m.runs.map((r, ci) => {
            const c = row.cells[ci];
            const label = c
              ? `${row.case} in run ${shortWhen(r.started_at)}: ${c.passed ? "passed" : "failed"}, score ${c.score.toFixed(2)}${c.regressed ? ", regressed vs previous run" : ""}${c.baseline_regressed ? ", regressed vs baseline" : ""}`
              : `${row.case}: not in this run`;
            return h(
              "td",
              null,
              h(
                "button",
                {
                  class: cellClass(c),
                  type: "button",
                  tabindex: ri === 0 && ci === m.runs.length - 1 ? 0 : -1,
                  "data-r": ri,
                  "data-c": ci,
                  "aria-label": label,
                  title: c && c.failing.length ? `failing: ${c.failing.join(", ")}` : undefined,
                  disabled: !c,
                  onclick: () => c && openCase(row.case, r.id),
                },
                c ? [c.regressed || c.baseline_regressed ? h("span", { html: icon("down") }) : null, c.passed ? "pass" : c.score.toFixed(2)] : "–",
              ),
            );
          }),
        ),
      );
    });
    const grid = h("table", { class: "matrix", "aria-label": "Eval results by case and run" }, h("thead", null, head), tbody);
    grid.addEventListener("keydown", (ev) => {
      const b = ev.target.closest(".cell");
      if (!b) return;
      let r = Number(b.dataset.r);
      let c = Number(b.dataset.c);
      if (ev.key === "ArrowRight") c++;
      else if (ev.key === "ArrowLeft") c--;
      else if (ev.key === "ArrowDown") r++;
      else if (ev.key === "ArrowUp") r--;
      else return;
      ev.preventDefault();
      const next = grid.querySelector(`.cell[data-r="${r}"][data-c="${c}"]`);
      if (next) {
        for (const x of grid.querySelectorAll(".cell")) x.tabIndex = -1;
        next.tabIndex = 0;
        next.focus();
        if (peek.isOpen && !next.disabled) next.click();
      }
    });
    const wrap = h("div", { class: "matrix-wrap" }, grid);
    area.appendChild(wrap);
    // newest runs are on the right: start scrolled there
    requestAnimationFrame(() => (wrap.scrollLeft = wrap.scrollWidth));
    markCells();
  }

  function markCells() {
    if (!areas.matrix) return;
    for (const b of areas.matrix.querySelectorAll(".cell")) {
      const row = matrix && matrix.cases[Number(b.dataset.r)];
      const run = matrix && matrix.runs[Number(b.dataset.c)];
      b.classList.toggle("is-open", !!(openCell && row && run && openCell.case === row.case && openCell.runId === run.id));
    }
  }

  async function openCase(caseName, runId) {
    openCell = { case: caseName, runId };
    markCells();
    peek.open();
    clear(peek.titleEl).appendChild(h("h2", null, caseName));
    clear(peek.actions);
    clear(peek.body).appendChild(loading("Loading case..."));
    let run;
    try {
      run = await getRun(runId);
    } catch (err) {
      clear(peek.body).appendChild(errorState(err, () => openCase(caseName, runId)));
      return;
    }
    if (!openCell || openCell.case !== caseName || openCell.runId !== runId) return;
    const r = (run.results || []).find((x) => x.case === caseName);
    if (!r) {
      clear(peek.body).appendChild(emptyState("Case not in this run", "The suite changed since this run."));
      return;
    }
    const ri = matrix.cases.findIndex((c) => c.case === caseName);
    const ci = matrix.runs.findIndex((x) => x.id === runId);
    const cell = matrix.cases[ri] && matrix.cases[ri].cells[ci];
    clear(peek.titleEl).append(r.passed ? chip("pass", "ok") : chip("fail", "err"), h("h2", null, caseName));
    const nav = (dr) => {
      const nr = matrix.cases[ri + dr];
      if (nr && nr.cells[ci]) openCase(nr.case, runId);
    };
    peek.actions.append(
      h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Previous case", title: "Previous case", html: icon("up"), disabled: ri <= 0, onclick: () => nav(-1) }),
      h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Next case", title: "Next case", html: icon("down"), disabled: ri >= matrix.cases.length - 1, onclick: () => nav(1) }),
    );
    const b = peek.body;
    clear(b);
    b.className = "peek-body";
    const runMeta = matrix.runs[ci] || {};
    const pills = h(
      "div",
      { class: "pills" },
      pill("Run", `${shortWhen(runMeta.started_at)}${runMeta.is_baseline ? " · baseline" : ""}`),
      pill("Model", run.model),
      pill("Score", r.score.toFixed(2)),
      pill("Steps", String(r.steps)),
      pill("Time", fmtMs(r.duration_ms)),
      r.usage ? pill("Tokens", fmtNum(r.usage.total_tokens)) : null,
      r.trace_id ? h("a", { class: "pill", href: `#/traces/${r.trace_id}`, title: "Open this case's agent trace" }, h("b", null, "Trace"), h("span", { class: "v" }, r.trace_id.slice(0, 8))) : null,
    );
    const top = h("div", { class: "peek-section" }, pills);
    if (cell && (cell.regressed || cell.baseline_regressed)) {
      const why = [cell.regressed ? "it got worse than the previous run" : null, cell.baseline_regressed ? "it passed in the baseline and fails now" : null].filter(Boolean).join("; ");
      top.appendChild(h("div", { class: "banner banner--err", role: "note", style: { margin: "var(--space-3) 0 0" } }, h("strong", null, "Regression"), h("div", null, why)));
    }
    // history strip for this case across the matrix columns
    const strip = h(
      "div",
      { class: "pills", style: { marginTop: "var(--space-3)" }, "aria-label": "This case across recent runs" },
      h("span", { class: "hint" }, "Across runs"),
      (matrix.cases[ri] ? matrix.cases[ri].cells : []).map((c, i) =>
        h(
          "button",
          { class: cellClass(c), type: "button", style: { minWidth: "40px", width: "auto", padding: "0 6px", height: "22px" }, disabled: !c, "aria-label": `${shortWhen(matrix.runs[i].started_at)}: ${c ? (c.passed ? "pass" : "fail") : "missing"}`, "aria-current": i === ci ? "true" : undefined, onclick: () => c && openCase(caseName, matrix.runs[i].id) },
          c ? (c.passed ? "✓" : "✗") : "–",
        ),
      ),
    );
    top.appendChild(strip);
    b.appendChild(top);
    const sec = (title, ...kids) => h("div", { class: "peek-section" }, h("div", { class: "io-label" }, title), ...kids);
    b.appendChild(sec("Input", h("div", { class: "io-text" }, r.input)));
    b.appendChild(sec("Output", h("div", { class: "io-text" }, r.output ?? "-")));
    if (r.error) b.appendChild(h("div", { class: "peek-section" }, h("div", { class: "banner banner--err", style: { margin: 0 } }, h("strong", null, "Error"), h("div", null, r.error))));
    b.appendChild(
      sec(
        `Metrics · ${(r.metrics || []).filter((x) => x.passed).length}/${(r.metrics || []).length} passed`,
        h(
          "div",
          { class: "metric-list" },
          (r.metrics || []).map((mt) =>
            h(
              "div",
              { class: "metric-row" },
              h("span", { class: mt.passed ? "ok" : "bad", html: icon(mt.passed ? "check" : "x") }),
              h("span", null, h("span", { class: "nm" }, mt.name), mt.details ? h("span", { class: "det" }, mt.details) : null),
              h("span", { class: "sc" }, mt.score.toFixed(2)),
            ),
          ),
        ),
      ),
    );
    b.appendChild(sec("Trajectory", trajectory(r)));
  }

  function pill(label, value) {
    return h("span", { class: "pill" }, h("b", null, label), h("span", { class: "v" }, value));
  }

  function trajectory(r) {
    const steps = (r.trajectory && r.trajectory.steps) || [];
    if (!steps.length) return h("p", { class: "hint" }, "No steps were recorded.");
    const list = h("ol", { class: "timeline" });
    for (const s of steps) {
      let kind = "model";
      let title = s.type;
      let sub = "";
      let extra = null;
      if (s.type === "tool_call") {
        kind = "tool";
        title = s.tool_name;
        sub = "tool call";
        extra = h("div", { class: "tl-detail" }, argsList(s.arguments));
      } else if (s.type === "tool_result") {
        kind = "tool";
        title = `${s.tool_name || "tool"} result`;
        extra = h("div", { class: "tl-detail" }, resultBox(s.content));
      } else if (s.type === "output") {
        kind = "final";
        title = "Final answer";
        extra = h("div", { class: "tl-text" }, s.content || "");
      } else {
        title = s.type === "thought" ? "Model" : s.type;
        extra = s.content ? h("div", { class: "tl-text" }, s.content) : null;
      }
      list.appendChild(
        h(
          "li",
          { class: "tl-item", "data-kind": kind, "data-status": s.success === false ? "error" : undefined },
          h("span", { class: "tl-dot", "aria-hidden": "true" }),
          h("div", { class: "tl-line" }, h("span", { class: `tl-title${kind === "tool" ? " mono" : ""}` }, title), h("span", { class: "tl-sub" }, sub), h("span", { class: "tl-meta" }, `step ${s.step}`)),
          extra,
        ),
      );
    }
    return list;
  }

  // --- history ------------------------------------------------------------------------------------
  async function loadHistory(suite) {
    const area = areas.history;
    if (!area) return;
    if (!area.childNodes.length) area.append(h("div", { class: "panel-head" }, h("h2", null, "Run history")), loading());
    let runs;
    try {
      runs = await api.get(`/api/evals/runs?suite=${encodeURIComponent(suite.name)}`);
    } catch (err) {
      clear(area).appendChild(errorState(err, () => loadHistory(suite)));
      return;
    }
    clear(area).appendChild(h("div", { class: "panel-head" }, h("h2", null, "Run history"), h("span", { class: "hint" }, plural(runs.length, "run"))));
    if (!runs.length) {
      area.appendChild(h("p", { class: "hint", style: { padding: "var(--space-4)", margin: 0 } }, "No runs yet."));
      return;
    }
    const tbody = h("tbody");
    for (const r of runs) {
      const sm = r.summary || {};
      const baseBtn =
        r.status === "completed" && !r.is_baseline
          ? h(
              "button",
              {
                class: "btn btn--sm",
                type: "button",
                onclick: async (e) => {
                  e.stopPropagation();
                  try {
                    await api.post(`/api/evals/runs/${r.id}/baseline`);
                    toast("Baseline updated");
                    runCache.clear();
                    loadSuitesQuiet();
                    loadHistory(suite);
                    loadMatrix(suite);
                    if (state.run) showRun(state.run);
                  } catch (err) {
                    toast(err.message, { kind: "err" });
                  }
                },
              },
              "Set baseline",
            )
          : r.is_baseline
            ? chip("baseline", "accent")
            : null;
      tbody.appendChild(
        h(
          "tr",
          {
            class: `clickable${r.id === state.run ? " is-selected" : ""}`,
            tabindex: 0,
            onclick: () => pickRun(r.id, suite),
            onkeydown: (e) => e.key === "Enter" && e.target === e.currentTarget && pickRun(r.id, suite),
          },
          h("td", { class: "nowrap small", title: r.started_at }, isoAgo(r.started_at)),
          h("td", { class: "mono small" }, r.model),
          h("td", null, r.status === "completed" ? chip(fmtPct(sm.pass_rate), sm.pass_rate === 1 ? "ok" : "err") : chip(r.status, r.status === "failed" ? "err" : "")),
          h("td", { class: "num" }, sm.mean_score !== undefined ? sm.mean_score.toFixed(2) : "-"),
          h("td", { class: "num hide-sm" }, sm.total_tokens !== undefined ? fmtNum(sm.total_tokens) : "-"),
          h("td", { class: "num hide-sm" }, sm.duration_ms !== undefined ? fmtMs(sm.duration_ms) : "-"),
          h("td", { class: "num" }, baseBtn),
        ),
      );
    }
    area.appendChild(
      h(
        "div",
        { class: "table-wrap" },
        h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "Started"), h("th", null, "Model"), h("th", null, "Pass rate"), h("th", { class: "num" }, "Score"), h("th", { class: "num hide-sm" }, "Tokens"), h("th", { class: "num hide-sm" }, "Agent time"), h("th", { class: "num" }, h("span", { class: "sr-only" }, "Baseline")))), tbody),
      ),
    );
  }

  function pickRun(id, suite) {
    state.run = id;
    setQuery();
    showRun(id);
    loadHistory(suite);
    if (matrix) paintMatrix();
  }

  async function loadSuitesQuiet() {
    try {
      suites = await api.get("/api/evals/suites");
      paintList();
    } catch {
      /* keep the old list */
    }
  }

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
  }

  // --- one run --------------------------------------------------------------------------------------
  async function showRun(runId) {
    stopPolling();
    const area = areas.run;
    if (!area) return;
    if (!area.childNodes.length || area.dataset.run !== runId) clear(area).appendChild(h("div", { class: "panel" }, loading("Loading run...")));
    area.dataset.run = runId;
    let run;
    try {
      run = await getRun(runId, { fresh: !runCache.has(runId) });
    } catch (err) {
      clear(area).appendChild(h("div", { class: "panel" }, err.status === 404 ? emptyState("Run not found", "It may have been removed from the state directory.") : errorState(err, () => showRun(runId))));
      return;
    }
    if (disposed || area.dataset.run !== runId) return;
    paintRun(area, run);
    if (run.status === "queued" || run.status === "running") {
      pollTimer = setTimeout(() => showRun(runId), 600);
    } else if (area._wasRunning) {
      area._wasRunning = false;
      const s = run.summary || {};
      if (run.status === "completed") toast(`Run finished: ${s.passed}/${s.cases} passed`);
      loadSuitesQuiet();
      const suite = suites.find((x) => x.path === state.suite);
      if (suite) {
        loadHistory(suite);
        loadMatrix(suite);
      }
    }
  }

  function paintRun(area, run) {
    clear(area);
    const running = run.status === "queued" || run.status === "running";
    area._wasRunning = area._wasRunning || running;
    const sm = run.summary || {};
    const head = h(
      "div",
      { class: "panel-head" },
      h("h2", null, running ? "Running..." : "Selected run"),
      h("span", { class: "hint mono" }, `${run.model} · ${isoAgo(run.started_at)}`),
      h("div", { class: "actions" }, run.is_baseline ? chip("baseline", "accent") : null, running ? chip(`${run.done}/${run.total}`, "accent") : run.status === "failed" ? chip("failed", "err") : chip(`${sm.passed}/${sm.cases} passed`, sm.pass_rate === 1 ? "ok" : "err")),
    );
    const panel = h("section", { class: "panel" }, head);
    const bodyEl = h("div", { class: "panel-body" });
    panel.appendChild(bodyEl);
    area.appendChild(panel);
    if (running) {
      const pct = run.total ? run.done / run.total : 0;
      bodyEl.appendChild(h("div", { class: "progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": run.total, "aria-valuenow": run.done, "aria-label": "Cases finished" }, h("i", { style: { transform: `scaleX(${pct})` } })));
      bodyEl.appendChild(h("p", { class: "hint", style: { margin: "8px 0 0" } }, `${run.done} of ${run.total} cases finished · ${run.passed} passed${run.elapsed_s ? ` · ${run.elapsed_s}s` : ""}`));
    }
    if (run.status === "failed") bodyEl.appendChild(h("div", { class: "banner banner--err", role: "alert" }, h("strong", null, "Run failed"), h("span", null, run.error || "unknown error")));
    if (!running && run.status === "completed") {
      bodyEl.appendChild(
        h(
          "div",
          { class: "figures" },
          fig("Pass rate", fmtPct(sm.pass_rate), `${sm.passed}/${sm.cases} cases`),
          fig("Mean score", sm.mean_score?.toFixed(2) ?? "-", Object.entries(sm.metrics || {}).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(" · ") || "no metrics"),
          fig("Tokens", fmtNum(sm.total_tokens), "all cases"),
          fig("Agent time", fmtMs(sm.duration_ms), "sum over cases"),
        ),
      );
      bodyEl.appendChild(diffBanner(run));
    }
    const results = run.results || [];
    if (results.length && !running) bodyEl.appendChild(resultsTable(results, run.baseline, run.id));
    else if (!running) bodyEl.appendChild(h("p", { class: "hint" }, "No case results."));
  }

  function fig(label, val, sub) {
    return h("div", { class: "figure" }, h("span", { class: "label" }, label), h("div", { class: "val" }, val), h("div", { class: "sub" }, sub));
  }

  function diffBanner(run) {
    if (run.is_baseline) return h("div", { class: "banner" }, "This run is the baseline. Later runs are compared against it.");
    if (!run.diff) return h("div", { class: "banner" }, "No baseline yet. Use “Set baseline” in the run history to compare future runs against this one.");
    const d = run.diff;
    const items = [];
    for (const name of d.new_failures) items.push(h("li", null, h("strong", null, name), " passed in the baseline and now fails"));
    for (const c of d.regressions) items.push(h("li", null, h("strong", null, c.case), ` ${c.metric}: ${c.baseline.toFixed(2)} → ${c.current.toFixed(2)} (${c.delta.toFixed(2)})`));
    if (d.has_regressions) {
      return h("div", { class: "banner banner--err", role: "alert" }, h("div", null, h("strong", null, `Regression vs baseline: pass rate ${fmtPct(d.baseline_pass_rate)} → ${fmtPct(d.current_pass_rate)}`), h("ul", null, items)));
    }
    const extra = [];
    if (d.fixed.length) extra.push(`fixed: ${d.fixed.join(", ")}`);
    if (d.improvements.length) extra.push(`${plural(d.improvements.length, "metric improvement")}`);
    if (d.new_cases.length) extra.push(`new cases: ${d.new_cases.join(", ")}`);
    return h("div", { class: "banner banner--ok" }, h("strong", null, "No regressions vs baseline."), h("span", null, `Pass rate ${fmtPct(d.baseline_pass_rate)} → ${fmtPct(d.current_pass_rate)}${extra.length ? ` · ${extra.join(" · ")}` : ""}`));
  }

  function resultsTable(results, baseline, runId) {
    const tbody = h("tbody");
    const sorted = [...results].sort((a, b) => Number(a.passed) - Number(b.passed) || a.case.localeCompare(b.case));
    for (const r of sorted) {
      const base = baseline && baseline.cases ? baseline.cases[r.case] : null;
      const regressed = base && base.passed && !r.passed;
      let vs = h("span", { class: "hint" }, baseline ? "new" : "-");
      if (base) {
        const delta = r.score - base.score;
        if (regressed) vs = chip("regressed", "err");
        else if (!base.passed && r.passed) vs = chip("fixed", "ok");
        else if (Math.abs(delta) > 0.001) vs = h("span", { class: `delta ${delta > 0 ? "up" : "down"}` }, `${delta > 0 ? "+" : ""}${delta.toFixed(2)}`);
        else vs = h("span", { class: "hint" }, "same");
      }
      const metrics = h(
        "div",
        { class: "metric-chips" },
        (r.metrics || []).map((m) => {
          const bm = base && base.metrics ? base.metrics[m.name] : undefined;
          const worse = bm !== undefined && m.score < bm - 0.001;
          return h("span", { class: `chip${m.passed ? "" : " chip--err"}${worse ? " chip--warn" : ""}`, title: m.details || "" }, `${m.name} ${m.score.toFixed(2)}`);
        }),
        r.error ? chip("error", "err") : null,
      );
      const open = () => openCase(r.case, runId);
      tbody.appendChild(
        h(
          "tr",
          { class: `clickable${regressed ? " regressed" : ""}`, tabindex: 0, onclick: open, onkeydown: (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open()) },
          h("td", null, h("span", { class: "mono small", style: { color: "var(--ink)" } }, r.case), r.tags && r.tags.length ? h("div", { class: "hint" }, r.tags.join(", ")) : null),
          h("td", null, r.passed ? chip("pass", "ok") : chip("fail", "err")),
          h("td", { class: "num" }, r.score.toFixed(2)),
          h("td", { class: "hide-sm" }, metrics),
          h("td", { class: "num hide-sm" }, String(r.steps)),
          h("td", { class: "num hide-sm" }, fmtMs(r.duration_ms)),
          h("td", null, vs),
        ),
      );
    }
    return h(
      "div",
      { class: "table-wrap" },
      h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "Case"), h("th", null, "Result"), h("th", { class: "num" }, "Score"), h("th", { class: "hide-sm" }, "Metrics"), h("th", { class: "num hide-sm" }, "Steps"), h("th", { class: "num hide-sm" }, "Time"), h("th", null, "Vs baseline"))), tbody),
    );
  }

  const onKey = (ev) => {
    if (ev.key === "Escape" && peek.isOpen && !(ev.target instanceof Element && ev.target.closest("dialog[open]")) && !isTyping(ev)) {
      ev.preventDefault();
      peek.close();
    }
  };
  document.addEventListener("keydown", onKey);
  refresh.addEventListener("click", loadSuites);
  api.get("/v1/models").then((r) => {
    models = r.data.map((m) => m.id);
    const dl = document.getElementById("ev-models");
    if (dl && !dl.childNodes.length) for (const m of models) dl.appendChild(h("option", { value: m }));
  }, () => {});
  await loadSuites();

  return () => {
    disposed = true;
    stopPolling();
    peek.dispose();
    document.removeEventListener("keydown", onKey);
  };
}
