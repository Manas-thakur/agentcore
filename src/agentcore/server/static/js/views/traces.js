// Traces explorer: query bar (status:error -model:mock latency:>2s ...), faceted sidebar with
// per-value counts, a volume histogram (drag to narrow the time range), quick filters, a dense
// sortable table, and a resizable side peek with the span tree. Keyboard: / j k Enter Esc 1-3.

import { download } from "../api.js";
import { api } from "../api.js";
import { histogram } from "../charts.js";
import { createPeek } from "../peek.js";
import { describe, FIELDS, quote, removeToken, selected, setValues, tokenAt, tokenize, toggleValue, validate } from "../query.js";
import { loadTrace, renderTraceDetail } from "../trace-detail.js";
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
  isTyping,
  loading,
  plural,
  statusDot,
  store,
  toast,
} from "../ui.js";

const PAGE = 100;
const RANGES = [
  { id: "1h", label: "1h", secs: 3600 },
  { id: "24h", label: "24h", secs: 86400 },
  { id: "7d", label: "7d", secs: 7 * 86400 },
  { id: "all", label: "All", secs: null },
];
const FACET_LABELS = { status: "Status", kind: "Source", model: "Model", tool: "Tool", name: "Root name" };
const COLUMNS = [
  { key: "time", label: "Time", sort: "time" },
  { key: "name", label: "Name", sort: "name" },
  { key: "status", label: "Status", sort: "status" },
  { key: "latency", label: "Latency", sort: "latency", num: true },
  { key: "tokens", label: "Tokens", sort: "tokens", num: true, cls: "hide-sm" },
  { key: "cost", label: "Cost", sort: "cost", num: true, cls: "hide-sm" },
  { key: "model", label: "Model", sort: "model", cls: "hide-sm" },
  { key: "input", label: "Input", cls: "col-input" },
];

function fmtLatencyExpr(ms) {
  if (ms >= 1000) return `>${(ms / 1000).toFixed(ms >= 10000 ? 0 : 2).replace(/\.?0+$/, "")}s`;
  return `>${Math.max(1, Math.round(ms))}ms`;
}

export async function render(root, { segments, params }) {
  const st = {
    query: params.query ?? store.get("traces.query", ""),
    range: params.range || (params.since || params.until ? null : store.get("traces.range", "all")),
    since: params.since ? Number(params.since) : null,
    until: params.until ? Number(params.until) : null,
    sort: params.sort || "time",
    order: params.order || "desc",
    open: segments[0] || null,
    tab: Number(params.tab || 0) || 0,
    rows: [],
    total: 0,
    data: null,
    active: -1,
    error: null,
  };
  let ctrl = null;
  let disposed = false;

  // --- skeleton ---------------------------------------------------------------------------
  const countEl = h("span", { class: "tx-count", "aria-live": "polite" });
  const rangeSeg = h("div", { class: "segmented", role: "group", "aria-label": "Time range" });
  const refreshBtn = h("button", { class: "icon-btn", type: "button", "aria-label": "Refresh", title: "Refresh", html: icon("refresh") });
  const filtersBtn = h("button", { class: "btn btn--sm only-narrow-tx", type: "button", "aria-controls": "tx-facets", "aria-expanded": "false", html: `${icon("filter")}<span>Filters</span>` });
  const titlebar = h("div", { class: "tx-titlebar" }, h("h1", null, "Traces"), countEl, h("div", { class: "actions" }, filtersBtn, rangeSeg, refreshBtn));

  const qInput = h("input", {
    type: "text",
    id: "tx-query",
    value: st.query,
    placeholder: "Filter: status:error -model:mock tool:calculator latency:>1s or free text",
    "aria-label": "Trace query",
    autocomplete: "off",
    spellcheck: "false",
    role: "combobox",
    "aria-expanded": "false",
    "aria-controls": "tx-suggest",
    "aria-autocomplete": "list",
    "aria-describedby": "tx-qmsg",
    "aria-keyshortcuts": "/",
  });
  const qClear = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Clear query", html: icon("x") });
  const qHelp = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Query syntax help", title: "Query syntax", html: icon("help") });
  const qBox = h("div", { class: "qbar-box" }, h("span", { html: icon("search") }), qInput, qClear, qHelp);
  qBox.firstChild.replaceWith(qBox.firstChild.firstChild);
  const suggest = h("ul", { class: "qsuggest", id: "tx-suggest", role: "listbox", hidden: true, "aria-label": "Suggestions" });
  const qMsg = h("div", { class: "qbar-msg", id: "tx-qmsg", "aria-live": "polite" });
  const qbar = h("div", { class: "qbar", role: "search" }, qBox, suggest, qMsg);
  const filtersRow = h("div", { class: "tx-filters" });

  const facetsEl = h("aside", { class: "facets", id: "tx-facets", "aria-label": "Filters" });
  const histoEl = h("div", { class: "chart-host" });
  const histoHead = h("div", { class: "tx-histo-head" });
  const histoWrap = h("div", { class: "tx-histo" }, histoHead, histoEl);
  const tableHost = h("div", { class: "tx-table" });
  const main = h("div", { class: "tx-main" }, histoWrap, tableHost);
  const body = h("div", { class: "tx-body" }, facetsEl, main);

  const peek = createPeek({ id: "traces", label: "Trace detail", onClose: () => { st.open = null; syncUrl(); markRows(); } });
  const tx = h("div", { class: "tx" }, h("div", { class: "tx-top" }, titlebar, qbar, filtersRow), h("div", { class: "tx-split" }, body, peek.el));
  root.appendChild(h("div", { class: "page page--full" }, tx));

  // --- url + persistence ----------------------------------------------------------------------
  function syncUrl() {
    const p = new URLSearchParams();
    if (st.query) p.set("query", st.query);
    if (st.range && st.range !== "all") p.set("range", st.range);
    if (st.since) p.set("since", String(Math.round(st.since)));
    if (st.until) p.set("until", String(Math.round(st.until)));
    if (st.sort !== "time") p.set("sort", st.sort);
    if (st.order !== "desc") p.set("order", st.order);
    if (st.open && st.tab) p.set("tab", String(st.tab));
    const path = st.open ? `#/traces/${encodeURIComponent(st.open)}` : "#/traces";
    history.replaceState(null, "", `${path}${p.toString() ? `?${p}` : ""}`);
    store.set("traces.query", st.query || null);
    store.set("traces.range", st.range || "all");
  }

  function window_() {
    if (st.since || st.until) return { since: st.since, until: st.until };
    const r = RANGES.find((x) => x.id === st.range);
    if (r && r.secs) return { since: Date.now() / 1000 - r.secs, until: null };
    return { since: null, until: null };
  }

  // --- loading --------------------------------------------------------------------------------
  function showQueryError(message) {
    // Half-typed clauses ("model:", "latency:>") get a neutral hint, real mistakes an error.
    const soft = /missing a (value|number)/.test(message);
    st.error = message;
    qBox.toggleAttribute("data-invalid", !soft);
    if (soft) qInput.removeAttribute("aria-invalid");
    else qInput.setAttribute("aria-invalid", "true");
    qMsg.className = soft ? "qbar-msg hint" : "qbar-msg err";
    qMsg.textContent = soft ? `Keep typing: ${message}` : message;
  }

  async function load({ append = false } = {}) {
    const invalid = validate(st.query);
    if (invalid) {
      showQueryError(invalid);
      return;
    }
    if (ctrl) ctrl.abort();
    ctrl = new AbortController();
    const w = window_();
    const p = new URLSearchParams({ limit: PAGE, offset: append ? st.rows.length : 0, sort: st.sort, order: st.order });
    if (st.query) p.set("query", st.query);
    if (w.since) p.set("since", String(w.since));
    if (w.until) p.set("until", String(w.until));
    if (!append && !st.data) clear(tableHost).appendChild(loading("Loading traces..."));
    tableHost.setAttribute("aria-busy", "true");
    try {
      const data = await api.get(`/api/traces/explore?${p}`, { signal: ctrl.signal });
      if (disposed) return;
      st.error = null;
      qBox.removeAttribute("data-invalid");
      qInput.removeAttribute("aria-invalid");
      qMsg.className = "qbar-msg";
      qMsg.textContent = "";
      st.data = data;
      st.total = data.total;
      st.rows = append ? st.rows.concat(data.items) : data.items;
      if (!append) st.active = st.open ? st.rows.findIndex((r) => r.trace_id === st.open) : Math.min(st.active, st.rows.length - 1);
      paintAll();
    } catch (err) {
      if (err.name === "AbortError" || disposed) return;
      if (err.status === 400) {
        showQueryError(err.message);
        return;
      }
      clear(tableHost).appendChild(errorState(err, () => load()));
    } finally {
      tableHost.removeAttribute("aria-busy");
    }
  }

  function paintAll() {
    paintCount();
    paintRange();
    paintFilters();
    paintFacets();
    paintHisto();
    paintTable();
  }

  function paintCount() {
    const d = st.data;
    if (!d) return;
    countEl.textContent = `${fmtNum(d.total)} of ${fmtNum(d.stats.count)} ${d.stats.count === 1 ? "trace" : "traces"}`;
  }

  function paintRange() {
    clear(rangeSeg);
    for (const r of RANGES) {
      rangeSeg.appendChild(
        h("button", {
          type: "button",
          "aria-pressed": String(!st.since && !st.until && st.range === r.id),
          onclick: () => {
            st.range = r.id;
            st.since = st.until = null;
            syncUrl();
            load();
          },
        }, r.label),
      );
    }
  }

  // --- query bar ------------------------------------------------------------------------------
  function setQuery(q, { now = true } = {}) {
    st.query = q.trim();
    if (qInput.value.trim() !== st.query) qInput.value = st.query ? `${st.query} ` : "";
    syncUrl();
    if (now) load();
  }
  const typed = debounce(() => {
    st.query = qInput.value.trim();
    syncUrl();
    load();
  }, 350);

  function quickChips() {
    const d = st.data;
    const stats = d ? d.stats : null;
    const chips = [];
    const errorsOn = selected(st.query, "status").includes("error") && selected(st.query, "status").length === 1;
    chips.push(
      h("button", {
        class: "qchip",
        type: "button",
        "aria-pressed": String(errorsOn),
        title: "Only failed traces (status:error)",
        onclick: () => setQuery(setValues(st.query, "status", errorsOn ? [] : ["error"])),
        html: `${icon("alert")}<span>Errors</span>${stats ? `<span class="n">${fmtNum(stats.errors)}</span>` : ""}`,
      }),
    );
    const latTok = tokenize(st.query).find((t) => t.key === "latency" && !t.neg && t.value.startsWith(">"));
    const p95 = stats && stats.p95_ms ? fmtLatencyExpr(stats.p95_ms) : null;
    chips.push(
      h("button", {
        class: "qchip",
        type: "button",
        "aria-pressed": String(!!latTok),
        disabled: !p95 && !latTok,
        title: p95 ? `Slower than p95 (latency:${p95})` : "Slow traces",
        onclick: () => setQuery(latTok ? removeToken(st.query, latTok.raw) : `${st.query} latency:${p95}`),
        html: `${icon("clock")}<span>Slow</span><span class="n">${latTok ? latTok.value.slice(1) : p95 ? `p95 ${p95.slice(1)}` : ""}</span>`,
      }),
    );
    const costTok = tokenize(st.query).find((t) => (t.key === "cost" || t.key === "tokens") && !t.neg && t.value.startsWith(">"));
    let expensive = null;
    if (stats) {
      if (stats.p90_cost_usd > 0) expensive = `cost:>${stats.p90_cost_usd}`;
      else if (stats.p90_tokens > 0) expensive = `tokens:>${Math.round(stats.p90_tokens)}`;
    }
    chips.push(
      h("button", {
        class: "qchip",
        type: "button",
        "aria-pressed": String(!!costTok),
        disabled: !expensive && !costTok,
        title: expensive ? `Top 10% by ${expensive.startsWith("cost") ? "cost" : "tokens (no priced models)"}: ${expensive}` : "Expensive traces",
        onclick: () => setQuery(costTok ? removeToken(st.query, costTok.raw) : `${st.query} ${expensive}`),
        html: `${icon("coin")}<span>Expensive</span>`,
      }),
    );
    return chips;
  }

  function paintFilters() {
    clear(filtersRow);
    filtersRow.append(...quickChips());
    const tokens = tokenize(st.query);
    const pills = tokens.map((t) => {
      const d = describe(t);
      return h(
        "span",
        { class: "fpill" },
        h("span", { class: "f" }, d.field),
        h("span", { class: "o" }, d.op),
        h("span", { class: "v", title: d.value }, d.value),
        h("button", { type: "button", "aria-label": `Remove filter ${t.raw}`, html: icon("x"), onclick: () => setQuery(removeToken(st.query, t.raw)) }),
      );
    });
    const w = st.since || st.until;
    if (pills.length || w) filtersRow.appendChild(h("span", { class: "sep", "aria-hidden": "true" }));
    if (w) {
      filtersRow.appendChild(
        h(
          "span",
          { class: "fpill" },
          h("span", { class: "f" }, "time"),
          h("span", { class: "o" }, "between"),
          h("span", { class: "v" }, `${fmtTime(st.since)} – ${st.until ? fmtTime(st.until) : "now"}`),
          h("button", { type: "button", "aria-label": "Clear time range", html: icon("x"), onclick: () => { st.since = st.until = null; syncUrl(); load(); } }),
        ),
      );
    }
    filtersRow.append(...pills);
    if (pills.length + (w ? 1 : 0) > 1) {
      filtersRow.appendChild(h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: () => { st.since = st.until = null; setQuery(""); } }, "Clear all"));
    }
  }

  // autocomplete ---------------------------------------------------------------------------
  let sugg = [];
  let suggActive = -1;
  function computeSuggestions() {
    const caret = qInput.selectionStart ?? qInput.value.length;
    const tok = tokenAt(qInput.value, caret);
    const facets = (st.data && st.data.facets) || {};
    if (!tok) {
      return document.activeElement === qInput && !qInput.value.trim() ? FIELDS.map((f) => ({ insert: `${f.name}:`, label: `${f.name}:`, desc: f.hint, replace: null, keepOpen: true })) : [];
    }
    if (!tok.key) {
      const word = tok.value.toLowerCase();
      if (!word || word.startsWith('"')) return [];
      return FIELDS.filter((f) => f.name.startsWith(word) && f.name !== word).map((f) => ({ insert: `${tok.neg ? "-" : ""}${f.name}:`, label: `${tok.neg ? "-" : ""}${f.name}:`, desc: f.hint, replace: tok, keepOpen: true }));
    }
    const f = FIELDS.find((x) => x.name === tok.key);
    if (!f) return [];
    const parts = tok.value.split(",");
    const last = parts[parts.length - 1].toLowerCase();
    const head = parts.slice(0, -1);
    const pool = f.kind === "text" ? (facets[f.name] || []).filter((v) => v.value !== null).map((v) => ({ v: v.value, n: v.count })) : [];
    for (const v of f.values || []) if (!pool.some((p) => p.v === v)) pool.push({ v, n: null });
    return pool
      .filter((p) => !head.includes(p.v) && p.v.toLowerCase().startsWith(last.replace(/^"/, "")) && p.v.toLowerCase() !== last)
      .slice(0, 10)
      .map((p) => {
        const val = head.length ? [...head, p.v].join(",") : quote(p.v);
        return { insert: `${tok.neg ? "-" : ""}${f.name}:${val} `, label: p.v, desc: p.n !== null ? `${fmtNum(p.n)} traces` : f.hint, replace: tok };
      });
  }
  function paintSuggest() {
    sugg = computeSuggestions();
    clear(suggest);
    if (!sugg.length) {
      suggest.hidden = true;
      qInput.setAttribute("aria-expanded", "false");
      qInput.removeAttribute("aria-activedescendant");
      return;
    }
    suggActive = Math.min(Math.max(suggActive, -1), sugg.length - 1);
    sugg.forEach((s, i) => {
      suggest.appendChild(
        h(
          "li",
          { id: `tx-sg-${i}`, role: "option", "aria-selected": String(i === suggActive), onmousedown: (e) => { e.preventDefault(); accept(i); } },
          h("span", { class: "k" }, s.label),
          h("span", { class: "d" }, s.desc || ""),
        ),
      );
    });
    suggest.hidden = false;
    qInput.setAttribute("aria-expanded", "true");
    if (suggActive >= 0) qInput.setAttribute("aria-activedescendant", `tx-sg-${suggActive}`);
    else qInput.removeAttribute("aria-activedescendant");
  }
  function closeSuggest() {
    suggest.hidden = true;
    sugg = [];
    suggActive = -1;
    qInput.setAttribute("aria-expanded", "false");
    qInput.removeAttribute("aria-activedescendant");
  }
  function accept(i) {
    const s = sugg[i];
    if (!s) return;
    const v = qInput.value;
    let next;
    let caret;
    if (s.replace) {
      next = v.slice(0, s.replace.start) + s.insert + v.slice(s.replace.end).replace(/^\s+/, "");
      caret = s.replace.start + s.insert.length;
    } else {
      const sep = v && !/\s$/.test(v) ? " " : "";
      next = v + sep + s.insert;
      caret = next.length;
    }
    qInput.value = next;
    qInput.setSelectionRange(caret, caret);
    suggActive = -1;
    if (s.keepOpen) {
      paintSuggest();
    } else {
      closeSuggest();
      st.query = qInput.value.trim();
      syncUrl();
      load();
    }
  }

  qInput.addEventListener("input", () => {
    suggActive = -1;
    paintSuggest();
    typed();
  });
  qInput.addEventListener("focus", () => paintSuggest());
  qInput.addEventListener("click", () => paintSuggest());
  qInput.addEventListener("blur", () => setTimeout(closeSuggest, 100));
  qInput.addEventListener("keydown", (ev) => {
    const open = !suggest.hidden && sugg.length;
    if (ev.key === "ArrowDown" && open) {
      ev.preventDefault();
      suggActive = (suggActive + 1) % sugg.length;
      paintSuggest();
    } else if (ev.key === "ArrowUp" && open) {
      ev.preventDefault();
      suggActive = suggActive <= 0 ? sugg.length - 1 : suggActive - 1;
      paintSuggest();
    } else if ((ev.key === "Tab" || ev.key === "Enter") && open && suggActive >= 0) {
      ev.preventDefault();
      accept(suggActive);
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      closeSuggest();
      st.query = qInput.value.trim();
      syncUrl();
      load();
    } else if (ev.key === "Escape") {
      ev.stopPropagation();
      if (open) closeSuggest();
      else qInput.blur();
    }
  });
  qClear.addEventListener("click", () => {
    qInput.value = "";
    setQuery("");
    qInput.focus();
  });
  qHelp.addEventListener("click", () => {
    clear(qMsg);
    qMsg.className = "qbar-msg";
    qMsg.append(
      "Fields: ",
      ...FIELDS.flatMap((f, i) => [i ? ", " : "", h("code", null, f.name)]),
      ". Prefix with ",
      h("code", null, "-"),
      " to exclude, use ",
      h("code", null, ","),
      " for any-of, ",
      h("code", null, "*"),
      " as a wildcard, ",
      h("code", null, ">"),
      " / ",
      h("code", null, "<="),
      " for numbers (",
      h("code", null, "latency:>1.5s"),
      "). Anything else searches id, name, model, input, output and error.",
    );
  });

  // --- facets -----------------------------------------------------------------------------------
  function paintFacets() {
    const facets = (st.data && st.data.facets) || {};
    const keepScroll = facetsEl.scrollTop;
    clear(facetsEl);
    const closeSheet = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Close filters", html: icon("x"), onclick: () => toggleSheet(false) });
    facetsEl.appendChild(h("div", { class: "facets-head" }, h("h2", null, "Filters"), closeSheet));
    let any = false;
    for (const field of ["status", "kind", "model", "tool", "name"]) {
      const values = facets[field] || [];
      const inc = selected(st.query, field);
      const exc = selected(st.query, field, true);
      if (!values.length && !inc.length && !exc.length) continue;
      any = true;
      const max = Math.max(1, ...values.map((v) => v.count));
      const shown = [...values.filter((v) => v.value !== null)];
      for (const v of [...inc, ...exc]) if (!shown.some((x) => x.value === v)) shown.push({ value: v, count: 0 });
      const headId = `facet-${field}`;
      const list = h("ul", { "aria-labelledby": headId });
      for (const v of shown) {
        const checked = inc.includes(v.value);
        const excluded = exc.includes(v.value);
        const cb = h("input", { type: "checkbox", checked, "aria-label": `${FACET_LABELS[field]} ${v.value}` });
        cb.addEventListener("change", () => setQuery(toggleValue(st.query, field, v.value)));
        list.appendChild(
          h(
            "li",
            null,
            h(
              "label",
              { class: `fv${excluded ? " is-excluded" : ""}`, title: `${v.value} · ${v.count}` },
              cb,
              h("span", { class: `nm${field === "status" || field === "kind" ? "" : " mono"}` }, field === "status" ? h("span", { class: `status-dot ${v.value === "ok" ? "ok" : "err"}` }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", { class: "txt" }, v.value)) : v.value),
              h("span", { class: "ct" }, fmtNum(v.count)),
              h("button", {
                class: "ex",
                type: "button",
                "aria-label": excluded ? `Stop excluding ${v.value}` : `Exclude ${v.value}`,
                title: excluded ? "Stop excluding" : "Exclude",
                html: icon(excluded ? "plus" : "minus"),
                onclick: (e) => {
                  e.preventDefault();
                  setQuery(toggleValue(st.query, field, v.value, true));
                },
              }),
              h("span", { class: "bar", style: { width: `${(v.count / max) * 100}%` }, "aria-hidden": "true" }),
            ),
          ),
        );
      }
      const more = values.find((v) => v.value === null);
      if (more) list.appendChild(h("li", { class: "hint", style: { padding: "2px 4px" } }, `+ ${fmtNum(more.count)} in other values (use the query bar)`));
      facetsEl.appendChild(
        h(
          "section",
          { class: "facet" },
          h(
            "h3",
            { id: headId },
            FACET_LABELS[field],
            inc.length || exc.length ? h("button", { type: "button", onclick: () => setQuery(setValues(setValues(st.query, field, []), field, [], true)) }, "Clear") : null,
          ),
          list,
        ),
      );
    }
    if (!any) facetsEl.appendChild(h("p", { class: "hint", style: { padding: "var(--space-4)" } }, "Facets appear once there are traces."));
    facetsEl.scrollTop = keepScroll;
    const n = ["status", "kind", "model", "tool", "name"].reduce((a, f) => a + selected(st.query, f).length + selected(st.query, f, true).length, 0);
    filtersBtn.querySelector("span").textContent = n ? `Filters (${n})` : "Filters";
  }
  function toggleSheet(on) {
    tx.classList.toggle("facets-open", on);
    filtersBtn.setAttribute("aria-expanded", String(on));
    if (on) facetsEl.querySelector("input, button")?.focus();
  }
  filtersBtn.addEventListener("click", () => toggleSheet(!tx.classList.contains("facets-open")));

  // --- histogram --------------------------------------------------------------------------------
  function paintHisto() {
    const d = st.data;
    if (!d) return;
    const hist = d.histogram;
    const n = hist.buckets.reduce((a, b) => a + b.count, 0);
    const errs = hist.buckets.reduce((a, b) => a + b.errors, 0);
    clear(histoHead).append(
      ...[
      h("span", null, `${plural(n, "trace")} over time`),
      errs ? h("span", { style: { color: "var(--err)" } }, `· ${fmtNum(errs)} failed`) : null,
      h("span", { class: "grow" }),
      h("span", { class: "hint only-wide" }, "Drag to zoom"),
      st.since || st.until ? h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: () => { st.since = st.until = null; syncUrl(); load(); } }, "Reset zoom") : null,
      ].filter(Boolean),
    );
    const span = hist.bucket_seconds;
    histogram(histoEl, {
      buckets: hist.buckets,
      start: hist.start,
      end: hist.end,
      fmtTip: (b) => `${fmtTime(b.t)} – ${fmtTime(b.t + span)}: ${b.count} trace${b.count === 1 ? "" : "s"}${b.errors ? `, ${b.errors} failed` : ""}`,
      onSelect: (a, b) => {
        st.since = a;
        st.until = b;
        st.range = null;
        syncUrl();
        load();
      },
    });
  }

  // --- table ------------------------------------------------------------------------------------
  function paintTable() {
    clear(tableHost);
    const d = st.data;
    if (!st.rows.length) {
      const filtered = st.query || st.since || st.until || (st.range && st.range !== "all");
      tableHost.appendChild(
        filtered
          ? emptyState("No traces match", "Remove a filter, widen the time range, or check the query.", h("button", { class: "btn", type: "button", onclick: () => { st.since = st.until = null; st.range = "all"; setQuery(""); } }, "Clear filters"))
          : emptyState("No traces yet", "Every agent run writes a trace. Send a message in the Playground or run an eval suite.", h("a", { class: "btn btn--primary", href: "#/playground" }, "Open Playground")),
      );
      return;
    }
    const p95 = d && d.stats ? d.stats.p95_ms : 0;
    const maxLat = Math.max(1, ...st.rows.map((r) => r.duration_ms));
    const head = h(
      "tr",
      null,
      COLUMNS.map((c) => {
        const sorted = st.sort === c.sort;
        return h(
          "th",
          { class: [c.num ? "num" : "", c.cls || ""].join(" ").trim() || undefined, "aria-sort": sorted ? (st.order === "asc" ? "ascending" : "descending") : undefined, scope: "col" },
          c.sort
            ? h("button", {
                class: "th-sort",
                type: "button",
                onclick: () => {
                  if (st.sort === c.sort) st.order = st.order === "desc" ? "asc" : "desc";
                  else {
                    st.sort = c.sort;
                    st.order = c.sort === "name" || c.sort === "model" || c.sort === "status" ? "asc" : "desc";
                  }
                  syncUrl();
                  load();
                },
                html: `<span>${c.label}</span>${icon(sorted && st.order === "asc" ? "up" : "down")}`,
              })
            : c.label,
        );
      }),
    );
    const tbody = h("tbody");
    st.rows.forEach((t, i) => {
      const slow = p95 && t.duration_ms >= p95 && st.rows.length > 2;
      const tr = h(
        "tr",
        {
          "data-id": t.trace_id,
          tabindex: -1,
          "aria-label": `${t.name}, ${t.status}, ${fmtMs(t.duration_ms)}, ${fmtAgo(t.start_time)}`,
          onclick: () => {
            st.active = i;
            openTrace(t.trace_id);
          },
        },
        h("td", { class: "cell-time", title: fmtTime(t.start_time) }, fmtAgo(t.start_time)),
        h("td", { class: "cell-name" }, t.name),
        h("td", null, statusDot(t.status)),
        h("td", { class: "num" }, h("span", { class: "lat" }, fmtMs(t.duration_ms), h("span", { class: `lat-bar${slow ? " slow" : ""}`, "aria-hidden": "true" }, h("i", { style: { width: `${(t.duration_ms / maxLat) * 100}%` } })))),
        h("td", { class: "num hide-sm" }, fmtNum(t.total_tokens)),
        h("td", { class: "num hide-sm" }, fmtCost(t.cost_usd)),
        h("td", { class: "cell-model hide-sm" }, t.model || "-"),
        h("td", { class: "cell-input col-input", title: t.input }, t.input || h("span", { class: "hint" }, "-")),
      );
      tbody.appendChild(tr);
    });
    tableHost.appendChild(h("table", { class: "table", "aria-label": "Traces", "aria-rowcount": st.total + 1 }, h("thead", null, head), tbody));
    if (st.rows.length < st.total) {
      tableHost.appendChild(h("div", { class: "tx-foot" }, `Showing ${fmtNum(st.rows.length)} of ${fmtNum(st.total)}`, h("button", { class: "btn btn--sm", type: "button", onclick: () => load({ append: true }) }, "Load more")));
    } else if (st.rows.length > 12) {
      tableHost.appendChild(h("div", { class: "tx-foot" }, `All ${fmtNum(st.total)} traces shown`));
    }
    markRows();
  }

  function markRows() {
    const trs = tableHost.querySelectorAll("tbody tr");
    trs.forEach((tr, i) => {
      tr.classList.toggle("is-active", i === st.active);
      tr.classList.toggle("is-open", tr.dataset.id === st.open);
      tr.tabIndex = i === st.active || (st.active < 0 && i === 0) ? 0 : -1;
    });
  }

  function moveActive(delta) {
    if (!st.rows.length) return;
    st.active = st.active < 0 ? (delta > 0 ? 0 : st.rows.length - 1) : Math.max(0, Math.min(st.rows.length - 1, st.active + delta));
    markRows();
    const tr = tableHost.querySelectorAll("tbody tr")[st.active];
    if (tr) {
      tr.scrollIntoView({ block: "nearest" });
      if (!peek.isOpen) tr.focus({ preventScroll: true });
    }
    if (peek.isOpen) openTrace(st.rows[st.active].trace_id, { keepFocus: true });
  }

  // --- peek ---------------------------------------------------------------------------------------
  let peekToken = 0;
  let detailCtl = null;
  async function openTrace(id, { keepFocus = false } = {}) {
    st.open = id;
    const idx = st.rows.findIndex((r) => r.trace_id === id);
    if (idx >= 0) st.active = idx;
    syncUrl();
    markRows();
    peek.open();
    const token = ++peekToken;
    clear(peek.titleEl).append(h("span", { class: "spinner", "aria-hidden": "true" }), h("h2", null, id.slice(0, 12)));
    clear(peek.actions);
    peek.body.className = "peek-body peek-body--split";
    if (!peek.body.childNodes.length) peek.body.appendChild(loading("Loading trace..."));
    let data;
    try {
      data = await loadTrace(id);
    } catch (err) {
      if (token !== peekToken) return;
      clear(peek.titleEl).appendChild(h("h2", null, "Trace"));
      clear(peek.body).appendChild(err.status === 404 ? emptyState("Trace not found", `No trace matches "${id}". It may have been deleted from the trace directory.`) : errorState(err, () => openTrace(id)));
      return;
    }
    if (token !== peekToken || disposed) return;
    const s = data.summary || {};
    clear(peek.titleEl).append(statusDot(s.status || "ok"), h("h2", { title: s.name }, s.name || "trace"));
    const pos = st.rows.findIndex((r) => r.trace_id === data.trace_id);
    const prev = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Previous trace (K)", title: "Previous (K)", html: icon("up"), disabled: pos <= 0, onclick: () => moveActive(-1) });
    const next = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Next trace (J)", title: "Next (J)", html: icon("down"), disabled: pos < 0 || pos >= st.rows.length - 1, onclick: () => moveActive(1) });
    const copyBtn = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Copy trace id", title: `Copy id ${data.trace_id}`, html: icon("copy"), onclick: () => copyText(data.trace_id) });
    const exportBtn = h("button", {
      class: "icon-btn icon-btn--sm",
      type: "button",
      "aria-label": "Export trace as JSON",
      title: "Export JSON",
      html: icon("download"),
      onclick: () => download(`/api/traces/${data.trace_id}/export`, `trace-${data.trace_id}.json`).catch((e) => toast(`Export failed: ${e.message}`, { kind: "err" })),
    });
    peek.actions.append(h("span", { class: "hint mono", style: { marginRight: "4px" } }, pos >= 0 ? `${pos + 1}/${st.total}` : ""), prev, next, copyBtn, exportBtn);
    detailCtl = renderTraceDetail(peek.body, data, {
      tab: st.tab,
      onTab: (i) => {
        st.tab = i;
        syncUrl();
      },
    });
    if (!keepFocus && document.activeElement && !peek.el.contains(document.activeElement) && document.activeElement !== qInput) detailCtl.focusTree();
  }

  // --- keyboard -------------------------------------------------------------------------------------
  const onKey = (ev) => {
    if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.target instanceof Element && ev.target.closest("dialog[open]")) return;
    if (ev.key === "Escape") {
      if (tx.classList.contains("facets-open")) {
        toggleSheet(false);
        return;
      }
      if (peek.isOpen) {
        ev.preventDefault();
        peek.close();
      }
      return;
    }
    if (isTyping(ev)) return;
    if (ev.key === "/") {
      ev.preventDefault();
      qInput.focus();
      qInput.select();
    } else if (ev.key === "j" || ev.key === "ArrowDown") {
      if (ev.key === "ArrowDown" && peek.el.contains(ev.target)) return;
      ev.preventDefault();
      moveActive(1);
    } else if (ev.key === "k" || ev.key === "ArrowUp") {
      if (ev.key === "ArrowUp" && peek.el.contains(ev.target)) return;
      ev.preventDefault();
      moveActive(-1);
    } else if (ev.key === "Enter" && !ev.target.closest("button, a, input, .tree, .tabs, .peek-handle")) {
      if (st.active >= 0 && st.rows[st.active]) {
        ev.preventDefault();
        openTrace(st.rows[st.active].trace_id);
      }
    } else if (peek.isOpen && ["1", "2", "3"].includes(ev.key) && detailCtl) {
      ev.preventDefault();
      detailCtl.selectTab(Number(ev.key) - 1);
    } else if (ev.key === "r") {
      load();
    }
  };
  document.addEventListener("keydown", onKey);
  refreshBtn.addEventListener("click", () => load());

  // --- boot -----------------------------------------------------------------------------------------
  if (params.chip === "slow") {
    // palette shortcut: apply the p95 filter once stats are in
    await load();
    const p95 = st.data && st.data.stats.p95_ms;
    if (p95) setQuery(`${st.query} latency:${fmtLatencyExpr(p95)}`);
  } else {
    syncUrl();
    await load();
  }
  if (st.open) openTrace(st.open);

  return () => {
    disposed = true;
    if (ctrl) ctrl.abort();
    document.removeEventListener("keydown", onKey);
    peek.dispose();
    if (histoEl._ro) histoEl._ro.disconnect();
  };
}
