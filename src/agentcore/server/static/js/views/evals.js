// Evals: discover suites, run one in the background with progress, inspect results, compare
// against a baseline run, and browse the run history.

import { api } from "../api.js";
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
  jsonPre,
  loading,
  store,
  toast,
} from "../ui.js";

export async function render(root, { params }) {
  const page = h("div", { class: "page" });
  root.appendChild(page);
  const refresh = h("button", { class: "btn", type: "button", html: `${icon("refresh")}<span>Rescan</span>` });
  page.appendChild(
    h(
      "div",
      { class: "page-head" },
      h("div", null, h("h1", null, "Evals"), h("p", { class: "lede" }, "Suites are discovered in the configured eval directories. Runs are kept as history; mark one as the baseline to flag regressions.")),
      h("div", { class: "actions" }, refresh),
    ),
  );
  const listCol = h("div", { class: "suite-list", "aria-label": "Eval suites" });
  const main = h("div", { class: "ev-main" });
  const layout = h("div", { class: "ev-layout" }, listCol, main);
  page.appendChild(layout);

  let suites = [];
  let models = [];
  let pollTimer = null;
  let disposed = false;
  const state = { suite: params.suite || store.get("evals.suite", null), run: params.run || null };

  function setQuery() {
    const q = new URLSearchParams();
    if (state.suite) q.set("suite", state.suite);
    if (state.run) q.set("run", state.run);
    history.replaceState(null, "", `#/evals${q.toString() ? `?${q}` : ""}`);
  }

  async function loadSuites() {
    clear(listCol).appendChild(loading("Scanning for suites..."));
    try {
      suites = await api.get("/api/evals/suites");
    } catch (err) {
      clear(listCol).appendChild(errorState(err, loadSuites));
      clear(main);
      return;
    }
    paintList();
    const current = suites.find((s) => s.path === state.suite && !s.error) || suites.find((s) => !s.error);
    if (current) selectSuite(current.path, state.run);
    else {
      clear(main);
      if (suites.length) main.appendChild(emptyState("No runnable suites", "Every suite file found has errors. Fix them and rescan."));
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
    for (const s of suites) {
      const last = s.last_run;
      const meta = [chip(`${s.cases} case${s.cases === 1 ? "" : "s"}`)];
      if (s.error) meta.push(chip("invalid", "err"));
      if (last && last.summary) meta.push(chip(`${fmtPct(last.summary.pass_rate)} last`, last.summary.pass_rate === 1 ? "ok" : "err"));
      if (s.baseline) meta.push(chip("baseline", "accent"));
      listCol.appendChild(
        h(
          "button",
          {
            class: "suite",
            type: "button",
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
    state.suite = path;
    state.run = runId;
    store.set("evals.suite", path);
    setQuery();
    for (const b of listCol.querySelectorAll(".suite")) b.setAttribute("aria-current", b.querySelector(".suite-path").textContent === path ? "true" : "false");
    const suite = suites.find((s) => s.path === path);
    if (!suite) return;
    clear(main);

    const modelInput = h("input", { class: "input mono", id: "ev-model", list: "ev-models", placeholder: suite.model || "server default", spellcheck: "false", autocomplete: "off", value: store.get("evals.model", "") });
    const datalist = h("datalist", { id: "ev-models" }, models.map((m) => h("option", { value: m })));
    const runBtn = h("button", { class: "btn btn--primary", type: "submit", html: `${icon("play")}<span>Run suite</span>` });
    const form = h(
      "form",
      { class: "run-bar" },
      h("div", { class: "field" }, h("label", { class: "label", for: "ev-model" }, "Model"), modelInput, datalist),
      runBtn,
    );
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

    main.appendChild(
      h(
        "div",
        { class: "panel", style: { marginBottom: "var(--space-4)" } },
        h(
          "div",
          { class: "panel-head" },
          h("div", null, h("h2", null, suite.name), suite.description ? h("p", { class: "hint", style: { margin: 0 } }, suite.description) : null),
          h("div", { class: "actions" }, (suite.tools || []).map((t) => chip(t))),
        ),
        h("div", { class: "panel-body" }, form),
      ),
    );
    const runArea = h("div", { id: "ev-run" });
    const historyArea = h("div", { class: "panel", style: { marginTop: "var(--space-4)" } });
    main.append(runArea, historyArea);
    main._runArea = runArea;
    main._historyArea = historyArea;
    loadHistory(suite);
    const target = runId || (suite.last_run && suite.last_run.id);
    if (target) showRun(target);
    else runArea.appendChild(emptyState("Not run yet", "Pick a model and run the suite. Each case gets a fresh agent; results stream in as cases finish."));
  }

  async function loadHistory(suite) {
    const area = main._historyArea;
    if (!area) return;
    clear(area).append(h("div", { class: "panel-head" }, h("h2", null, "Run history")), loading());
    let runs;
    try {
      runs = await api.get(`/api/evals/runs?suite=${encodeURIComponent(suite.name)}`);
    } catch (err) {
      clear(area).appendChild(errorState(err, () => loadHistory(suite)));
      return;
    }
    clear(area).appendChild(h("div", { class: "panel-head" }, h("h2", null, "Run history"), h("span", { class: "hint" }, `${runs.length} run${runs.length === 1 ? "" : "s"}`)));
    if (!runs.length) {
      area.appendChild(h("p", { class: "hint", style: { padding: "var(--space-4)", margin: 0 } }, "No runs yet."));
      return;
    }
    const tbody = h("tbody");
    for (const r of runs) {
      const sm = r.summary || {};
      const baseBtn = r.status === "completed" && !r.is_baseline
        ? h("button", {
            class: "btn btn--sm",
            type: "button",
            onclick: async (e) => {
              e.stopPropagation();
              try {
                await api.post(`/api/evals/runs/${r.id}/baseline`);
                toast("Baseline updated");
                loadSuitesQuiet();
                loadHistory(suite);
                if (state.run) showRun(state.run);
              } catch (err) {
                toast(err.message, { kind: "err" });
              }
            },
          }, "Set baseline")
        : r.is_baseline ? chip("baseline", "accent") : null;
      tbody.appendChild(
        h(
          "tr",
          { class: `clickable${r.id === state.run ? " is-selected" : ""}`, onclick: () => { state.run = r.id; setQuery(); showRun(r.id); loadHistory(suite); } },
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
        h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "Started"), h("th", null, "Model"), h("th", null, "Pass rate"), h("th", { class: "num" }, "Score"), h("th", { class: "num hide-sm" }, "Tokens"), h("th", { class: "num hide-sm" }, "Agent time"), h("th", { class: "num" }, ""))), tbody),
      ),
    );
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

  async function showRun(runId) {
    stopPolling();
    const area = main._runArea;
    if (!area) return;
    if (!area.childNodes.length || area.dataset.run !== runId) clear(area).appendChild(loading("Loading run..."));
    area.dataset.run = runId;
    let run;
    try {
      run = await api.get(`/api/evals/runs/${encodeURIComponent(runId)}`);
    } catch (err) {
      clear(area).appendChild(err.status === 404 ? emptyState("Run not found", "It may have been removed from the state directory.") : errorState(err, () => showRun(runId)));
      return;
    }
    if (disposed || area.dataset.run !== runId) return;
    paintRun(area, run);
    if (run.status === "queued" || run.status === "running") {
      pollTimer = setTimeout(() => showRun(runId), 600);
    } else if (run.status === "completed" && area._wasRunning) {
      area._wasRunning = false;
      const s = run.summary || {};
      toast(`Run finished: ${s.passed}/${s.cases} passed`);
      loadSuitesQuiet();
      const suite = suites.find((x) => x.path === state.suite);
      if (suite) loadHistory(suite);
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
      h("h2", null, running ? "Running..." : "Results"),
      h("span", { class: "hint mono" }, `${run.model} · ${isoAgo(run.started_at)}`),
      h("div", { class: "actions" }, run.is_baseline ? chip("baseline", "accent") : null, running ? chip(`${run.done}/${run.total}`, "accent") : run.status === "failed" ? chip("failed", "err") : chip(`${sm.passed}/${sm.cases} passed`, sm.pass_rate === 1 ? "ok" : "err")),
    );
    const panel = h("div", { class: "panel" }, head);
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
          { class: "figures", style: { marginBottom: "var(--space-4)" } },
          fig("Pass rate", fmtPct(sm.pass_rate), `${sm.passed}/${sm.cases} cases`),
          fig("Mean score", sm.mean_score?.toFixed(2) ?? "-", Object.entries(sm.metrics || {}).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(" · ") || "no metrics"),
          fig("Tokens", fmtNum(sm.total_tokens), "all cases"),
          fig("Agent time", fmtMs(sm.duration_ms), "sum over cases"),
        ),
      );
      bodyEl.appendChild(diffBanner(run));
    }
    const results = run.results || [];
    if (results.length) bodyEl.appendChild(resultsTable(results, run.baseline));
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
    if (d.improvements.length) extra.push(`${d.improvements.length} metric improvement${d.improvements.length === 1 ? "" : "s"}`);
    if (d.new_cases.length) extra.push(`new cases: ${d.new_cases.join(", ")}`);
    return h("div", { class: "banner banner--ok" }, h("strong", null, "No regressions vs baseline."), h("span", null, `Pass rate ${fmtPct(d.baseline_pass_rate)} → ${fmtPct(d.current_pass_rate)}${extra.length ? ` · ${extra.join(" · ")}` : ""}`));
  }

  function resultsTable(results, baseline) {
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
      const detailRow = h("tr", { class: "case-detail", hidden: true }, h("td", { colspan: 7 }, caseDetail(r)));
      const row = h(
        "tr",
        {
          class: `clickable${regressed ? " regressed" : ""}`,
          tabindex: 0,
          "aria-expanded": "false",
          onclick: () => toggle(),
          onkeydown: (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggle()),
        },
        h("td", null, h("span", { class: "mono small", style: { color: "var(--color-ink)" } }, r.case), r.tags && r.tags.length ? h("div", { class: "hint" }, r.tags.join(", ")) : null),
        h("td", null, r.passed ? chip("pass", "ok") : chip("fail", "err")),
        h("td", { class: "num" }, r.score.toFixed(2)),
        h("td", null, metrics),
        h("td", { class: "num hide-sm" }, String(r.steps)),
        h("td", { class: "num hide-sm" }, fmtMs(r.duration_ms)),
        h("td", null, vs),
      );
      function toggle() {
        detailRow.hidden = !detailRow.hidden;
        row.setAttribute("aria-expanded", String(!detailRow.hidden));
      }
      tbody.append(row, detailRow);
    }
    return h(
      "div",
      { class: "table-wrap" },
      h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "Case"), h("th", null, "Result"), h("th", { class: "num" }, "Score"), h("th", null, "Metrics"), h("th", { class: "num hide-sm" }, "Steps"), h("th", { class: "num hide-sm" }, "Time"), h("th", null, "Vs baseline"))), tbody),
    );
  }

  function caseDetail(r) {
    const failing = (r.metrics || []).filter((m) => !m.passed);
    const traj = (r.trajectory && r.trajectory.steps) || [];
    const tools = traj.filter((s) => s.type === "tool_call").map((s) => ({ tool: s.tool_name, args: s.arguments }));
    return h(
      "div",
      { style: { display: "grid", gap: "var(--space-3)", padding: "var(--space-2) 0" } },
      h("div", { class: "case-io" }, h("div", null, h("span", { class: "label" }, "Input"), h("p", { style: { whiteSpace: "pre-wrap", margin: "6px 0 0" } }, r.input)), h("div", null, h("span", { class: "label" }, "Output"), h("p", { style: { whiteSpace: "pre-wrap", margin: "6px 0 0" } }, r.output ?? "-"))),
      r.error ? h("div", { class: "banner banner--err" }, r.error) : null,
      failing.length ? h("div", null, h("span", { class: "label" }, "Failing metrics"), h("ul", { style: { margin: "6px 0 0", paddingLeft: "1.2em" } }, failing.map((m) => h("li", null, h("strong", null, m.name), `: ${m.details}`)))) : null,
      tools.length ? h("div", null, h("span", { class: "label" }, "Tool calls"), jsonPre(tools)) : null,
    );
  }

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
  };
}
