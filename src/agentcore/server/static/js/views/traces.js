// Traces: filterable list + detail view with a span waterfall, attributes, model I/O, export.

import { api, download, request } from "../api.js";
import { renderMarkdown } from "../md.js";
import {
  clear,
  copyText,
  debounce,
  emptyState,
  errorState,
  fmtAgo,
  fmtCost,
  fmtMs,
  fmtNum,
  fmtTime,
  h,
  icon,
  jsonPre,
  loading,
  statusDot,
  store,
  toast,
} from "../ui.js";

const PAGE = 50;

export async function render(root, { segments, params }) {
  if (segments[0]) return renderDetail(root, segments[0]);
  return renderList(root, params);
}

// --- list -----------------------------------------------------------------------------------
async function renderList(root, params) {
  const saved = store.get("traces.filters", {});
  const f = { q: "", status: "", model: "", kind: "", since: "", until: "", ...saved, ...params };
  const page = h("div", { class: "page" });
  root.appendChild(page);
  const countEl = h("p", { class: "lede" }, " ");
  const refresh = h("button", { class: "btn", type: "button", html: `${icon("refresh")}<span>Refresh</span>` });
  page.appendChild(
    h("div", { class: "page-head" }, h("div", null, h("h1", null, "Traces"), countEl), h("div", { class: "actions" }, refresh)),
  );

  const field = (label, control, id) => h("div", { class: "field" }, h("label", { class: "label", for: id }, label), control);
  const q = h("input", { class: "input", type: "search", id: "tf-q", placeholder: "Search input, output, id, error...", value: f.q });
  const status = h("select", { class: "select", id: "tf-status" }, opt("", "Any status"), opt("ok", "OK"), opt("error", "Error"));
  const model = h("select", { class: "select", id: "tf-model" }, opt("", "Any model"));
  const kind = h("select", { class: "select", id: "tf-kind" }, opt("", "All traces"), opt("agent", "Agent runs"), opt("eval", "Eval runs"));
  const since = h("input", { class: "input", type: "date", id: "tf-since", value: f.since });
  const until = h("input", { class: "input", type: "date", id: "tf-until", value: f.until });
  const reset = h("button", { class: "btn btn--ghost", type: "button" }, "Clear");
  status.value = f.status;
  kind.value = f.kind;
  page.appendChild(
    h(
      "div",
      { class: "filters", role: "search" },
      field("Search", q, "tf-q"),
      field("Status", status, "tf-status"),
      field("Model", model, "tf-model"),
      field("Kind", kind, "tf-kind"),
      field("From", since, "tf-since"),
      field("To", until, "tf-until"),
      h("div", { class: "field" }, reset),
    ),
  );
  const body = h("div", { class: "panel" });
  page.appendChild(body);

  let offset = 0;
  let rows = [];
  let total = 0;
  let ctrl = null;

  api.get("/api/traces/facets").then(
    (facets) => {
      for (const m of facets.models) model.appendChild(opt(m, m));
      model.value = f.model;
    },
    () => {},
  );

  function query() {
    const p = new URLSearchParams({ limit: PAGE, offset });
    if (f.q) p.set("q", f.q);
    if (f.status) p.set("status", f.status);
    if (f.model) p.set("model", f.model);
    if (f.kind) p.set("kind", f.kind);
    if (f.since) p.set("since", f.since);
    if (f.until) p.set("until", `${f.until}T23:59:59`);
    return `/api/traces?${p}`;
  }

  async function load(append = false) {
    if (!append) {
      offset = 0;
      rows = [];
      clear(body).appendChild(loading("Loading traces..."));
    }
    if (ctrl) ctrl.abort();
    ctrl = new AbortController();
    try {
      const resp = await request(query(), { raw: true, signal: ctrl.signal });
      const items = await resp.json();
      total = Number(resp.headers.get("X-Total-Count") || items.length);
      rows = rows.concat(items);
      offset = rows.length;
      paint();
    } catch (err) {
      if (err.name === "AbortError") return;
      clear(body).appendChild(errorState(err, () => load()));
    }
  }

  function paint() {
    const filtered = f.q || f.status || f.model || f.kind || f.since || f.until;
    countEl.textContent = total ? `${fmtNum(total)} trace${total === 1 ? "" : "s"}${filtered ? " match the filters" : ""}` : " ";
    clear(body);
    if (!rows.length) {
      body.appendChild(
        filtered
          ? emptyState("No traces match", "Try a wider date range or clear the filters.", h("button", { class: "btn", type: "button", onclick: () => reset.click() }, "Clear filters"))
          : emptyState("No traces yet", "Every agent run writes a trace. Send a message in the Playground or run an eval suite.", h("a", { class: "btn btn--primary", href: "#/playground" }, "Open Playground")),
      );
      return;
    }
    const table = h(
      "table",
      { class: "table" },
      h(
        "thead",
        null,
        h("tr", null, h("th", null, "Status"), h("th", null, "Run"), h("th", { class: "hide-sm" }, "Input"), h("th", { class: "hide-sm" }, "Model"), h("th", null, "Started"), h("th", { class: "num" }, "Duration"), h("th", { class: "num hide-sm" }, "Tokens"), h("th", { class: "num hide-sm" }, "Cost"), h("th", { class: "num hide-sm" }, "Tools")),
      ),
      h(
        "tbody",
        null,
        rows.map((t) =>
          h(
            "tr",
            { class: "clickable", tabindex: 0, onclick: () => (location.hash = `#/traces/${t.trace_id}`), onkeydown: (e) => e.key === "Enter" && (location.hash = `#/traces/${t.trace_id}`) },
            h("td", null, statusDot(t.status)),
            h("td", null, h("a", { class: "trace-name rowlink", href: `#/traces/${t.trace_id}`, onclick: (e) => e.stopPropagation() }, t.name), h("div", { class: "hint mono" }, t.trace_id.slice(0, 12))),
            h("td", { class: "trunc trace-input hide-sm", title: t.input }, t.input || "-"),
            h("td", { class: "mono small hide-sm" }, t.model || "-"),
            h("td", { class: "nowrap small", title: fmtTime(t.start_time) }, fmtAgo(t.start_time)),
            h("td", { class: "num" }, fmtMs(t.duration_ms)),
            h("td", { class: "num hide-sm" }, fmtNum(t.total_tokens)),
            h("td", { class: "num hide-sm" }, fmtCost(t.cost_usd)),
            h("td", { class: "num hide-sm" }, t.tool_errors ? `${t.tool_calls} (${t.tool_errors} err)` : String(t.tool_calls)),
          ),
        ),
      ),
    );
    body.appendChild(h("div", { class: "table-wrap" }, table));
    if (rows.length < total) {
      body.appendChild(h("div", { class: "load-more" }, h("button", { class: "btn", type: "button", onclick: () => load(true) }, `Load more (${fmtNum(total - rows.length)} left)`)));
    }
  }

  const apply = () => {
    Object.assign(f, { q: q.value.trim(), status: status.value, model: model.value, kind: kind.value, since: since.value, until: until.value });
    store.set("traces.filters", { status: f.status, model: f.model, kind: f.kind });
    load();
  };
  q.addEventListener("input", debounce(apply, 250));
  for (const el of [status, model, kind, since, until]) el.addEventListener("change", apply);
  reset.addEventListener("click", () => {
    q.value = "";
    status.value = model.value = kind.value = since.value = until.value = "";
    apply();
  });
  refresh.addEventListener("click", () => load());
  await load();
}

function opt(value, label) {
  return h("option", { value }, label);
}

// --- detail ---------------------------------------------------------------------------------
function kindOf(name) {
  if (name.startsWith("agent.run") || name.startsWith("graph.run") || name === "tool.invoke") return "agent";
  if (name === "agent.step" || name.startsWith("graph.node")) return "step";
  if (name === "model.generate") return "model";
  if (name.startsWith("tool.")) return "tool";
  return "other";
}

function flatten(spans) {
  const byId = new Map(spans.map((s) => [s.span_id, { span: s, children: [] }]));
  const roots = [];
  for (const s of spans) {
    const node = byId.get(s.span_id);
    if (s.parent_id && byId.has(s.parent_id)) byId.get(s.parent_id).children.push(node);
    else roots.push(node);
  }
  const out = [];
  const walk = (node, depth) => {
    out.push({ ...node.span, depth, childCount: node.children.length });
    node.children.sort((a, b) => a.span.start_time - b.span.start_time).forEach((c) => walk(c, depth + 1));
  };
  roots.sort((a, b) => a.span.start_time - b.span.start_time).forEach((r) => walk(r, 0));
  return out;
}

async function renderDetail(root, traceId) {
  const page = h("div", { class: "page" });
  root.appendChild(page);
  page.appendChild(loading("Loading trace..."));
  let data;
  try {
    data = await api.get(`/api/traces/${encodeURIComponent(traceId)}`);
  } catch (err) {
    clear(page).appendChild(
      err.status === 404
        ? emptyState("Trace not found", `No trace matches "${traceId}". It may have been deleted from the trace directory.`, h("a", { class: "btn", href: "#/traces" }, "All traces"))
        : errorState(err, () => { clear(root); renderDetail(root, traceId); }),
    );
    return;
  }
  clear(page);
  const spans = flatten(data.spans);
  const s = data.summary || {};
  const t0 = Math.min(...data.spans.map((x) => x.start_time));
  const t1 = Math.max(...data.spans.map((x) => x.end_time || x.start_time));
  const total = Math.max((t1 - t0) * 1000, 0.001);
  const models = data.spans.filter((x) => x.name === "model.generate");
  const prompt = models.reduce((a, m) => a + (m.attributes["tokens.prompt"] || 0), 0);
  const completion = models.reduce((a, m) => a + (m.attributes["tokens.completion"] || 0), 0);

  page.appendChild(h("a", { class: "back", href: "#/traces", html: `${icon("back")}<span>All traces</span>` }));
  const exportBtn = h("button", { class: "btn", type: "button", html: `${icon("download")}<span>Export JSON</span>` });
  exportBtn.addEventListener("click", () => download(`/api/traces/${data.trace_id}/export`, `trace-${data.trace_id}.json`).catch((e) => toast(`Export failed: ${e.message}`, { kind: "err" })));
  page.appendChild(
    h(
      "div",
      { class: "page-head" },
      h(
        "div",
        null,
        h("h1", null, s.name || "trace"),
        h("p", { class: "lede mono" }, data.trace_id, " ", h("button", { class: "btn btn--ghost btn--sm", type: "button", "aria-label": "Copy trace id", html: icon("copy"), onclick: () => copyText(data.trace_id) })),
      ),
      h("div", { class: "actions" }, statusDot(s.status || "ok"), exportBtn),
    ),
  );
  const fig = (label, val, sub) => h("div", { class: "figure" }, h("span", { class: "label" }, label), h("div", { class: "val" }, val), sub ? h("div", { class: "sub" }, sub) : null);
  page.appendChild(
    h(
      "div",
      { class: "figures" },
      fig("Duration", fmtMs(s.duration_ms ?? total), fmtTime(s.start_time)),
      fig("Model", s.model || "-", `${models.length} call${models.length === 1 ? "" : "s"}`),
      fig("Tokens", fmtNum(s.total_tokens ?? prompt + completion), `${fmtNum(prompt)} in · ${fmtNum(completion)} out`),
      fig("Cost", fmtCost(s.cost_usd ?? 0), "estimated"),
      fig("Spans", String(data.spans.length), `${s.tool_calls ?? 0} tool calls`),
    ),
  );
  if (s.error) page.appendChild(h("div", { class: "banner banner--err", role: "alert" }, h("strong", null, "Error"), h("span", null, s.error)));
  if (s.input || s.output) {
    page.appendChild(
      h(
        "div",
        { class: "io-grid" },
        h("div", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", null, "Input")), h("div", { class: "panel-body", style: { whiteSpace: "pre-wrap" } }, s.input || "-")),
        h("div", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", null, "Output")), h("div", { class: "panel-body md", html: renderMarkdown(s.output || "-") })),
      ),
    );
  }

  // waterfall
  const detail = h("div", { class: "panel span-detail" });
  const wf = h("div", { class: "wf", role: "listbox", "aria-label": "Spans" });
  const ticks = h("div", { class: "ticks" });
  for (let k = 0; k <= 4; k++) {
    ticks.appendChild(h("span", { class: "tick", style: { left: `${k * 25}%` } }, fmtMs((total * k) / 4)));
  }
  wf.appendChild(h("div", { class: "wf-axis" }, h("div", { class: "wf-name" }, h("span", { class: "label" }, "Span")), ticks));
  const rowsEls = [];
  spans.forEach((sp, i) => {
    const left = ((sp.start_time - t0) * 1000 / total) * 100;
    const width = Math.max((sp.duration_ms / total) * 100, 0.25);
    const label = sp.attributes["tool.name"] ? `${sp.name} ${sp.attributes["tool.name"]}` : sp.attributes.step && sp.name === "agent.step" ? `${sp.name} ${sp.attributes.step}` : sp.name;
    const grid = [25, 50, 75].map((p) => h("span", { class: "wf-grid", style: { left: `${p}%` } }));
    const row = h(
      "button",
      {
        class: "wf-row",
        type: "button",
        role: "option",
        "aria-selected": "false",
        title: `${label} · ${fmtMs(sp.duration_ms)}`,
        onclick: () => select(i),
      },
      h(
        "span",
        { class: "wf-name", style: { paddingLeft: `${8 + sp.depth * 14}px` } },
        sp.status === "error" ? h("span", { class: "err-mark", "aria-label": "error" }, "!") : null,
        h("span", { class: "nm" }, label),
        h("span", { class: "ms" }, fmtMs(sp.duration_ms)),
      ),
      h("span", { class: "wf-track" }, grid, h("span", { class: "wf-bar", "data-kind": kindOf(sp.name), "data-status": sp.status, style: { left: `${Math.min(left, 99.5)}%`, width: `${Math.min(width, 100 - Math.min(left, 99.5))}%` } })),
    );
    rowsEls.push(row);
    wf.appendChild(row);
  });
  wf.addEventListener("keydown", (ev) => {
    const cur = rowsEls.findIndex((r) => r.getAttribute("aria-selected") === "true");
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const next = Math.max(0, Math.min(rowsEls.length - 1, cur + (ev.key === "ArrowDown" ? 1 : -1)));
      select(next);
      rowsEls[next].focus();
    }
  });
  const legend = h(
    "div",
    { class: "legend" },
    [["agent", "run"], ["step", "step"], ["model", "model call"], ["tool", "tool"]].map(([k, l]) => h("span", null, h("i", { class: "wf-bar", "data-kind": k, style: { position: "static", height: "10px", width: "10px" } }), l)),
    h("span", null, h("i", { style: { background: "var(--color-err)" } }), "error"),
  );
  page.appendChild(
    h(
      "div",
      { class: "wf-layout" },
      h("div", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", null, "Timeline"), h("div", { class: "actions" }, legend)), wf),
      detail,
    ),
  );

  function select(i) {
    rowsEls.forEach((r, j) => r.setAttribute("aria-selected", j === i ? "true" : "false"));
    paintSpan(spans[i]);
  }

  function paintSpan(sp) {
    clear(detail);
    const a = { ...sp.attributes };
    const head = h("div", { class: "panel-head" }, h("h3", { class: "mono" }, sp.name), h("div", { class: "actions" }, statusDot(sp.status)));
    const bodyEl = h("div", { class: "panel-body" });
    detail.append(head, bodyEl);
    const kv = (pairs) => h("dl", { class: "kv" }, pairs.map(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
    const basics = [
      ["duration", fmtMs(sp.duration_ms)],
      ["offset", `+${fmtMs((sp.start_time - t0) * 1000)}`],
      ["span id", h("span", { class: "mono" }, sp.span_id)],
    ];
    if (sp.parent_id) basics.push(["parent", h("span", { class: "mono" }, sp.parent_id)]);
    if (sp.error) basics.push(["error", h("span", { style: { color: "var(--color-err)" } }, sp.error)]);
    bodyEl.appendChild(kv(basics));

    if (sp.name === "model.generate") {
      bodyEl.appendChild(h("h4", { class: "section-title" }, "Usage"));
      bodyEl.appendChild(
        kv([
          ["model", a.model || "-"],
          ["tokens", `${fmtNum(a["tokens.prompt"] || 0)} in · ${fmtNum(a["tokens.completion"] || 0)} out`],
          ["cost", fmtCost(a["cost.usd"] || 0)],
          ["latency", fmtMs(a["latency.ms"])],
        ]),
      );
      const msgs = a["input.messages"];
      if (Array.isArray(msgs)) {
        bodyEl.appendChild(h("h4", { class: "section-title" }, `Model input (${msgs.length} messages)`));
        bodyEl.appendChild(
          h(
            "div",
            { class: "msglist" },
            msgs.map((m) =>
              h(
                "div",
                { class: "m" },
                h("span", { class: "label" }, m.role + (m.name ? ` · ${m.name}` : "")),
                m.content ? h("div", { class: "c" }, m.content) : null,
                m.tool_calls ? jsonPre(m.tool_calls) : null,
              ),
            ),
          ),
        );
      }
      if ("output.content" in a || a["output.tool_calls"]) {
        bodyEl.appendChild(h("h4", { class: "section-title" }, "Model output"));
        if (a["output.content"]) bodyEl.appendChild(h("div", { class: "msglist" }, h("div", { class: "m" }, h("div", { class: "c" }, a["output.content"]))));
        if (a["output.tool_calls"] && a["output.tool_calls"].length) bodyEl.appendChild(jsonPre(a["output.tool_calls"]));
        if (!a["output.content"] && !(a["output.tool_calls"] || []).length) bodyEl.appendChild(h("p", { class: "hint" }, "(empty response)"));
      }
      for (const k of ["model", "tokens.prompt", "tokens.completion", "tokens.total", "cost.usd", "latency.ms", "input.messages", "output.content", "output.tool_calls"]) delete a[k];
    }
    if (sp.name.startsWith("tool.") && ("tool.arguments" in a || "tool.output" in a)) {
      bodyEl.appendChild(h("h4", { class: "section-title" }, "Tool call"));
      let out = a["tool.output"];
      try {
        out = JSON.parse(out);
      } catch {
        /* text */
      }
      bodyEl.appendChild(kv([["arguments", jsonPre(a["tool.arguments"] ?? {})], ["output", jsonPre(out ?? "", { wrap: true })]]));
      delete a["tool.arguments"];
      delete a["tool.output"];
    }
    const rest = Object.entries(a);
    if (rest.length) {
      bodyEl.appendChild(h("h4", { class: "section-title" }, "Attributes"));
      bodyEl.appendChild(kv(rest.map(([k, v]) => [k, typeof v === "object" && v !== null ? jsonPre(v) : typeof v === "string" && v.length > 120 ? h("div", { style: { whiteSpace: "pre-wrap" } }, v) : String(v)])));
    }
    if (sp.events && sp.events.length) {
      bodyEl.appendChild(h("h4", { class: "section-title" }, "Events"));
      bodyEl.appendChild(jsonPre(sp.events));
    }
  }

  // pick the most interesting span by default: first error, else first model call
  const initial = Math.max(0, spans.findIndex((x) => x.status === "error") >= 0 ? spans.findIndex((x) => x.status === "error") : spans.findIndex((x) => x.name === "model.generate"));
  select(initial);
}
