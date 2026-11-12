// Overview: KPIs over a time range, charts over time, top tools and models.

import { api } from "../api.js";
import { barChart, lineChart } from "../charts.js";
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
      h("div", null, h("h1", null, "Overview"), h("p", { class: "lede" }, "Agent runs recorded in the trace directory: volume, reliability, latency, tokens and cost.")),
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
    const fig = (label, val, sub, warn) =>
      h("div", { class: "figure" }, h("span", { class: "label" }, label), h("div", { class: "val", style: warn ? { color: "var(--color-err)" } : null }, val), h("div", { class: "sub" }, sub));
    body.appendChild(
      h(
        "div",
        { class: "figures" },
        fig("Runs", fmtNum(k.runs), `${fmtNum(k.tool_calls)} tool calls`),
        fig("Success rate", fmtPct(k.success_rate), `${fmtNum(k.errors)} failed`, k.success_rate !== null && k.success_rate < 0.95),
        fig("p50 latency", fmtMs(k.p50_ms), "per run"),
        fig("p95 latency", fmtMs(k.p95_ms), "per run"),
        fig("Tokens", fmtNum(k.tokens), k.runs ? `${fmtNum(Math.round(k.tokens / k.runs))} per run` : "-"),
        fig("Cost", fmtCost(k.cost_usd), "estimated from the price table"),
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
    const panel = (title, sub, chart) => h("div", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", null, title), h("span", { class: "hint" }, sub)), h("div", { class: "panel-body" }, chart));
    body.appendChild(
      h(
        "div",
        { class: "charts" },
        panel("Runs", "ok + failed per bucket", runsChart),
        panel("Latency", "p50 solid · p95 dashed", latChart),
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
    const toolsPanel = h(
      "div",
      { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", null, "Top tools"), h("span", { class: "hint" }, "by calls")),
      d.top_tools.length
        ? h(
            "div",
            { class: "table-wrap" },
            h(
              "table",
              { class: "table" },
              h("thead", null, h("tr", null, h("th", null, "Tool"), h("th", { class: "num" }, "Calls"), h("th", { class: "num" }, "Errors"), h("th", { class: "num" }, "Avg"))),
              h(
                "tbody",
                null,
                d.top_tools.map((t) =>
                  h(
                    "tr",
                    null,
                    h(
                      "td",
                      null,
                      h("div", { class: "hbar" }, h("span", { class: "mono small", style: { color: "var(--color-ink)" } }, t.name), h("div", { class: "hbar-track", title: `${t.calls} calls, ${t.errors} errors` }, h("i", { style: { width: `${((t.calls - t.errors) / maxCalls) * 100}%` } }), h("i", { class: "err", style: { width: `${(t.errors / maxCalls) * 100}%` } }))),
                    ),
                    h("td", { class: "num" }, fmtNum(t.calls)),
                    h("td", { class: "num", style: t.errors ? { color: "var(--color-err)" } : null }, fmtNum(t.errors)),
                    h("td", { class: "num" }, fmtMs(t.avg_ms)),
                  ),
                ),
              ),
            ),
          )
        : h("p", { class: "hint", style: { padding: "var(--space-4)", margin: 0 } }, "No tool calls in this range."),
    );
    const modelsPanel = h(
      "div",
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
            { class: "panel-body", style: { borderTop: "1px solid var(--color-rule)" } },
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
