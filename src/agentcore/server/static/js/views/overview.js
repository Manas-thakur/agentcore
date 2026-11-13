// Overview: KPI cards with sparklines and deltas vs the previous period, latency p50/p95,
// tokens and cost over time, top tools with error rates, models and recent failures.

import { api } from "../api.js";
import { barChart, lineChart, sparkline } from "../charts.js";
import {
  clear,
  emptyState,
  errorState,
  fmtAgo,
  fmtCost,
  fmtMs,
  fmtNum,
  fmtPct,
  h,
  icon,
  loading,
  pctChange,
  store,
} from "../ui.js";

const RANGES = [
  { days: 1, label: "24 h" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];

export async function render(root) {
  const page = h("div", { class: "page" });
  root.appendChild(page);
  let days = store.get("overview.days", 7);
  const seg = h("div", { class: "segmented", role: "group", "aria-label": "Time range" });
  const refresh = h("button", { class: "btn", type: "button", "aria-label": "Refresh", html: `${icon("refresh")}<span>Refresh</span>` });
  page.appendChild(
    h(
      "div",
      { class: "page-head" },
      h("div", null, h("h1", null, "Overview"), h("p", { class: "lede" }, "Agent runs from the trace directory. Deltas compare with the previous period of the same length.")),
      h("div", { class: "actions" }, seg, refresh),
    ),
  );
  const body = h("div");
  page.appendChild(body);

  function paintSeg() {
    clear(seg);
    for (const r of RANGES) {
      seg.appendChild(
        h("button", {
          type: "button",
          "aria-pressed": r.days === days ? "true" : "false",
          onclick: () => {
            days = r.days;
            store.set("overview.days", days);
            paintSeg();
            load();
          },
        }, r.label),
      );
    }
  }

  async function load() {
    clear(body).appendChild(loading("Crunching traces..."));
    let data;
    try {
      data = await api.get(`/api/overview?days=${days}&tz=${new Date().getTimezoneOffset()}`);
    } catch (err) {
      clear(body).appendChild(errorState(err, load));
      return;
    }
    paint(data);
  }

  function paint(d) {
    clear(body);
    const k = d.kpis;
    if (!k.runs && !k.tool_calls) {
      body.appendChild(
        emptyState(
          "No runs in this range",
          "Overview aggregates traces written by agent runs. Chat in the Playground, run an eval suite, or call the API, then come back.",
          h("a", { class: "btn btn--primary", href: "#/playground" }, "Open Playground"),
        ),
      );
      return;
    }
    const prev = d.previous;
    const s0 = d.series;
    const rangeLabel = (RANGES.find((r) => r.days === days) || {}).label || `${days} days`;
    // better: "up" = higher is better, "down" = lower is better, "none" = neutral volume.
    const kpi = ({ label, value, cur, before, better, fmtDelta, series, sub, err }) => {
      let delta = null;
      if (prev && before !== undefined) {
        const change = pctChange(cur, before);
        let text;
        if (fmtDelta) text = fmtDelta(cur, before);
        else if (change === null) text = "new";
        else text = `${change > 0 ? "▲ " : change < 0 ? "▼ " : ""}${Math.abs(change * 100).toFixed(Math.abs(change) < 0.1 ? 1 : 0)}%`;
        const diff = (cur ?? 0) - (before ?? 0);
        let tone = "flat";
        if (Math.abs(diff) > 1e-9 && better !== "none") tone = diff > 0 === (better === "up") ? "good" : "bad";
        delta = h("span", { class: `kpi-delta ${tone}`, title: `Previous ${rangeLabel}: ${before === null ? "-" : before}` }, text);
      }
      return h(
        "div",
        { class: `kpi${err ? " kpi--err" : ""}` },
        h("span", { class: "kpi-label" }, label),
        h("div", { class: "kpi-row" }, h("span", { class: "kpi-val" }, value), delta),
        h("span", { class: "kpi-sub" }, sub || (prev ? `vs previous ${rangeLabel}` : "no earlier data to compare")),
        series && series.length > 1 ? sparkline(series, { label: `${label} trend` }) : null,
      );
    };
    const ppDelta = (cur, before) => {
      if (cur === null || before === null || cur === undefined || before === undefined) return "n/a";
      const pp = (cur - before) * 100;
      return `${pp > 0 ? "▲ " : pp < 0 ? "▼ " : ""}${Math.abs(pp).toFixed(1)} pp`;
    };
    body.appendChild(
      h(
        "div",
        { class: "kpis" },
        kpi({ label: "Runs", value: fmtNum(k.runs), cur: k.runs, before: prev?.runs, better: "none", series: s0.map((b) => b.runs), sub: `${fmtNum(k.tool_calls)} tool calls` }),
        kpi({
          label: "Success rate",
          value: fmtPct(k.success_rate),
          cur: k.success_rate,
          before: prev?.success_rate,
          better: "up",
          fmtDelta: ppDelta,
          series: s0.map((b) => (b.runs ? (b.runs - b.errors) / b.runs : null)),
          sub: `${fmtNum(k.errors)} failed`,
          err: k.success_rate !== null && k.success_rate < 0.95,
        }),
        kpi({ label: "p50 latency", value: fmtMs(k.p50_ms), cur: k.p50_ms, before: prev?.p50_ms, better: "down", series: s0.map((b) => b.p50_ms) }),
        kpi({ label: "p95 latency", value: fmtMs(k.p95_ms), cur: k.p95_ms, before: prev?.p95_ms, better: "down", series: s0.map((b) => b.p95_ms) }),
        kpi({ label: "Tokens", value: fmtNum(k.tokens), cur: k.tokens, before: prev?.tokens, better: "none", series: s0.map((b) => b.tokens), sub: k.runs ? `${fmtNum(Math.round(k.tokens / k.runs))} per run` : "-" }),
        kpi({ label: "Cost", value: fmtCost(k.cost_usd), cur: k.cost_usd, before: prev?.cost_usd, better: "down", series: s0.map((b) => b.cost_usd), sub: "estimated from the price table" }),
      ),
    );

    const hourly = d.range.bucket_seconds < 86400;
    const label = (t) => {
      const dt = new Date(t * 1000);
      return hourly ? dt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    };
    const when = (t) => new Date(t * 1000).toLocaleString(undefined, hourly ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" } : { month: "short", day: "numeric" });
    const runsChart = h("div", { class: "chart" });
    const latChart = h("div", { class: "chart" });
    const tokChart = h("div", { class: "chart" });
    const costChart = h("div", { class: "chart" });
    const panel = (title, sub, chart) => h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", null, title), typeof sub === "string" ? h("span", { class: "hint" }, sub) : h("div", { class: "actions" }, sub)), h("div", { class: "panel-body" }, chart));
    body.appendChild(
      h(
        "div",
        { class: "charts" },
        panel("Runs", h("span", { class: "legend" }, h("span", null, h("i", { style: { background: "var(--span-model)" } }), "ok"), h("span", null, h("i", { style: { background: "var(--err)" } }), "failed")), runsChart),
        panel("Latency", h("span", { class: "legend" }, h("span", null, h("i", { class: "dash", style: { background: "var(--accent)" } }), "p50"), h("span", null, h("i", { class: "dash", style: { background: "var(--span-agent)" } }), "p95 (dashed)")), latChart),
        panel("Tokens", "prompt + completion", tokChart),
        panel("Cost", "USD, estimated", costChart),
      ),
    );
    const s = d.series;
    barChart(runsChart, {
      title: "Runs over time",
      integer: true,
      series: [{ key: "ok", cls: "bar" }, { key: "err", cls: "bar-err" }],
      rows: s.map((b) => ({ label: label(b.t), tip: `${when(b.t)}: ${b.runs} runs, ${b.errors} failed`, values: { ok: b.runs - b.errors, err: b.errors } })),
    });
    lineChart(latChart, {
      title: "Latency over time",
      fmtY: (v) => fmtMs(v),
      series: [{ key: "p50", cls: "line-1", ptCls: "pt-1" }, { key: "p95", cls: "line-2", ptCls: "pt-2" }],
      rows: s.map((b) => ({ label: label(b.t), tip: `${when(b.t)}: p50 ${fmtMs(b.p50_ms)}, p95 ${fmtMs(b.p95_ms)}`, values: { p50: b.p50_ms, p95: b.p95_ms } })),
    });
    barChart(tokChart, {
      title: "Tokens over time",
      integer: true,
      fmtY: (v) => fmtNum(Math.round(v)),
      series: [{ key: "tok", cls: "bar" }],
      rows: s.map((b) => ({ label: label(b.t), tip: `${when(b.t)}: ${fmtNum(b.tokens)} tokens`, values: { tok: b.tokens } })),
    });
    barChart(costChart, {
      title: "Cost over time",
      fmtY: (v) => fmtCost(v),
      series: [{ key: "c", cls: "bar" }],
      rows: s.map((b) => ({ label: label(b.t), tip: `${when(b.t)}: ${fmtCost(b.cost_usd)}`, values: { c: b.cost_usd } })),
    });

    const maxCalls = Math.max(1, ...d.top_tools.map((t) => t.calls));
    const toolHref = (name) => `#/traces?query=${encodeURIComponent(`tool:${name}`)}`;
    const toolsPanel = h(
      "section",
      { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", null, "Top tools"), h("span", { class: "hint" }, "by calls, with error rate")),
      d.top_tools.length
        ? h(
            "div",
            { class: "table-wrap" },
            h(
              "table",
              { class: "table" },
              h("thead", null, h("tr", null, h("th", null, "Tool"), h("th", { class: "num" }, "Calls"), h("th", { class: "num" }, "Error rate"), h("th", { class: "num hide-sm" }, "Avg latency"))),
              h(
                "tbody",
                null,
                d.top_tools.map((t) => {
                  const rate = t.error_rate ?? (t.calls ? t.errors / t.calls : 0);
                  return h(
                    "tr",
                    null,
                    h(
                      "td",
                      null,
                      h(
                        "div",
                        { class: "hbar" },
                        h("a", { class: "mono small", href: toolHref(t.name), title: `Traces that called ${t.name}`, style: { color: "var(--ink)" } }, t.name),
                        h("div", { class: "hbar-track", "aria-hidden": "true" }, h("i", { style: { width: `${((t.calls - t.errors) / maxCalls) * 100}%` } }), h("i", { class: "err", style: { width: `${(t.errors / maxCalls) * 100}%` } })),
                      ),
                    ),
                    h("td", { class: "num" }, fmtNum(t.calls)),
                    h("td", { class: "num" }, h("span", { class: "rate-bar" }, h("span", { style: rate > 0 ? { color: "var(--err)" } : null }, fmtPct(rate)), h("span", { class: "rate-track", "aria-hidden": "true" }, h("i", { style: { width: `${Math.min(1, rate) * 100}%` } })))),
                    h("td", { class: "num hide-sm" }, fmtMs(t.avg_ms)),
                  );
                }),
              ),
            ),
          )
        : h("p", { class: "hint", style: { padding: "var(--space-4)", margin: 0 } }, "No tool calls in this range."),
    );
    const modelsPanel = h(
      "section",
      { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", null, "Models")),
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "table" },
          h("thead", null, h("tr", null, h("th", null, "Model"), h("th", { class: "num" }, "Runs"), h("th", { class: "num" }, "Tokens"), h("th", { class: "num" }, "Cost"))),
          h("tbody", null, d.models.map((m) => h("tr", null, h("td", { class: "mono small" }, m.model), h("td", { class: "num" }, fmtNum(m.runs)), h("td", { class: "num" }, fmtNum(m.tokens)), h("td", { class: "num" }, fmtCost(m.cost_usd))))),
        ),
      ),
      d.recent_errors.length
        ? h(
            "div",
            { class: "panel-body", style: { borderTop: "1px solid var(--border)" } },
            h("span", { class: "label" }, "Recent failures"),
            h("ul", { style: { margin: "8px 0 0", paddingLeft: "1.1em", fontSize: "var(--text-sm)" } }, d.recent_errors.map((e) => h("li", null, h("a", { href: `#/traces/${e.trace_id}` }, e.error || e.name), h("span", { class: "hint" }, ` · ${fmtAgo(e.start_time)}`)))),
          )
        : null,
    );
    body.appendChild(h("div", { class: "two-col" }, toolsPanel, modelsPanel));
  }

  refresh.addEventListener("click", load);
  paintSeg();
  await load();
}
