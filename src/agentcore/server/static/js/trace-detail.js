// Trace detail used by the traces side peek: metadata pills, a nested span tree with latency
// bars proportional to the root span, and Preview / Attributes / JSON tabs for the selected span.

import { api } from "./api.js";
import { renderMarkdown } from "./md.js";
import { tabs } from "./peek.js";
import { clear, copyText, fmtCost, fmtMs, fmtNum, fmtTime, h, icon, jsonPre, store } from "./ui.js";

const cache = new Map();

export async function loadTrace(id, { fresh = false } = {}) {
  if (!fresh && cache.has(id)) return cache.get(id);
  const data = await api.get(`/api/traces/${encodeURIComponent(id)}`);
  cache.set(id, data);
  if (cache.size > 40) cache.delete(cache.keys().next().value);
  return data;
}

export function kindOf(name) {
  if (name.startsWith("agent.run") || name.startsWith("graph.run") || name === "tool.invoke") return "agent";
  if (name === "agent.step" || name.startsWith("graph.node") || name === "agent.reflect") return "step";
  if (name === "model.generate") return "model";
  if (name.startsWith("tool.")) return "tool";
  return "other";
}

function spanLabel(sp) {
  const a = sp.attributes || {};
  if (sp.name === "agent.step") return { name: `step ${a.step ?? ""}`.trim(), sub: "" };
  if (sp.name === "model.generate") {
    const tok = a["tokens.total"] ? `${fmtNum(a["tokens.total"])} tok` : "";
    return { name: "model.generate", sub: [a.model, tok].filter(Boolean).join(" · ") };
  }
  if (sp.name.startsWith("tool.") && a["tool.name"]) return { name: a["tool.name"], sub: sp.name };
  return { name: sp.name, sub: "" };
}

function buildTree(spans) {
  const byId = new Map(spans.map((s) => [s.span_id, { span: s, children: [] }]));
  const roots = [];
  for (const s of spans) {
    const node = byId.get(s.span_id);
    if (s.parent_id && byId.has(s.parent_id)) byId.get(s.parent_id).children.push(node);
    else roots.push(node);
  }
  const sortRec = (nodes) => {
    nodes.sort((a, b) => a.span.start_time - b.span.start_time);
    nodes.forEach((n) => sortRec(n.children));
  };
  sortRec(roots);
  return roots;
}

function parseMaybeJson(v) {
  if (typeof v !== "string") return v;
  const t = v.trim();
  if (!t || !/^[[{]/.test(t)) return v;
  try {
    return JSON.parse(t);
  } catch {
    return v;
  }
}

function ioBlock(label, content, { copy } = {}) {
  return h(
    "div",
    { class: "io-block" },
    h(
      "div",
      { class: "io-label" },
      h("span", { class: "grow" }, label),
      copy !== undefined ? h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": `Copy ${label.toLowerCase()}`, html: icon("copy"), onclick: () => copyText(typeof copy === "string" ? copy : JSON.stringify(copy, null, 2)) }) : null,
    ),
    content,
  );
}

function textBox(text, { md = false } = {}) {
  if (md) return h("div", { class: "io-text md", html: renderMarkdown(text || "") });
  return h("div", { class: "io-text" }, text || "");
}

export function argsList(args) {
  const entries = Object.entries(args || {});
  if (!entries.length) return h("p", { class: "hint", style: { margin: 0 } }, "No arguments.");
  return h(
    "dl",
    { class: "args" },
    entries.map(([k, v]) => [h("dt", null, k), h("dd", null, typeof v === "string" ? v : JSON.stringify(v, null, 2))]),
  );
}

export function resultBox(output) {
  const parsed = parseMaybeJson(output);
  if (parsed !== null && typeof parsed === "object") return jsonPre(parsed, { wrap: true });
  return h("div", { class: "io-text mono", style: { fontSize: "var(--text-xs)" } }, String(output ?? ""));
}

function chatMessages(msgs) {
  return h(
    "div",
    { class: "chat-msgs" },
    msgs.map((m) =>
      h(
        "div",
        { class: "chat-msg" },
        h("header", null, h("span", null, m.role), m.name ? h("span", { class: "mono" }, m.name) : null),
        m.content ? h("div", { class: "c" }, m.content) : null,
        m.tool_calls && m.tool_calls.length ? jsonPre(m.tool_calls, { wrap: true }) : null,
      ),
    ),
  );
}

function preview(sp, all) {
  const a = sp.attributes || {};
  const wrap = h("div");
  if (sp.error) wrap.appendChild(h("div", { class: "banner banner--err", role: "alert" }, h("strong", null, "Error"), h("div", null, sp.error)));
  const kind = kindOf(sp.name);
  if (sp.name === "model.generate") {
    const msgs = a["input.messages"];
    if (Array.isArray(msgs)) wrap.appendChild(ioBlock(`Input · ${msgs.length} messages`, chatMessages(msgs), { copy: msgs }));
    const out = a["output.content"];
    const calls = a["output.tool_calls"] || [];
    const outEl = h("div", { class: "chat-msgs" });
    if (out) outEl.appendChild(h("div", { class: "chat-msg" }, h("header", null, "assistant"), h("div", { class: "c" }, out)));
    for (const c of calls) {
      outEl.appendChild(h("div", { class: "chat-msg" }, h("header", null, h("span", null, "tool call"), h("span", { class: "mono" }, c.name)), h("div", { class: "c" }, argsList(c.arguments))));
    }
    if (!out && !calls.length) outEl.appendChild(h("p", { class: "hint" }, "(empty response)"));
    wrap.appendChild(ioBlock("Output", outEl, { copy: out || calls }));
    wrap.appendChild(
      ioBlock(
        "Usage",
        h("dl", { class: "kv kv--table" }, [
          [h("dt", null, "model"), h("dd", { class: "mono" }, a.model || "-")],
          [h("dt", null, "tokens"), h("dd", null, `${fmtNum(a["tokens.prompt"] || 0)} in · ${fmtNum(a["tokens.completion"] || 0)} out`)],
          [h("dt", null, "cost"), h("dd", null, fmtCost(a["cost.usd"] || 0))],
          [h("dt", null, "latency"), h("dd", null, fmtMs(a["latency.ms"] ?? sp.duration_ms))],
        ]),
      ),
    );
    return wrap;
  }
  if (kind === "tool" && ("tool.arguments" in a || "tool.output" in a)) {
    wrap.appendChild(ioBlock("Arguments", argsList(a["tool.arguments"]), { copy: a["tool.arguments"] || {} }));
    wrap.appendChild(ioBlock(sp.status === "error" ? "Error output" : "Result", resultBox(a["tool.output"]), { copy: String(a["tool.output"] ?? "") }));
    return wrap;
  }
  if (kind === "agent" || kind === "step") {
    if (a.task) wrap.appendChild(ioBlock("Input", textBox(a.task), { copy: a.task }));
    // Tool calls made under this span, in order: name(args) -> result
    const ids = new Set([sp.span_id]);
    const under = [];
    for (const s of all) {
      if (s.parent_id && ids.has(s.parent_id)) {
        ids.add(s.span_id);
        if (s.name === "tool.execute") under.push(s);
      }
    }
    if (under.length) {
      wrap.appendChild(
        ioBlock(
          `Tool calls · ${under.length}`,
          h(
            "div",
            { class: "chat-msgs" },
            under.map((t) =>
              h(
                "div",
                { class: "chat-msg" },
                h("header", null, h("span", { class: "mono" }, t.attributes["tool.name"] || "tool"), h("span", null, fmtMs(t.duration_ms)), t.status !== "ok" ? h("span", { style: { color: "var(--err)" } }, "error") : null),
                h("div", { class: "c" }, argsList(t.attributes["tool.arguments"]), h("div", { style: { marginTop: "6px" } }, resultBox(t.attributes["tool.output"]))),
              ),
            ),
          ),
        ),
      );
    }
    if (a.output) wrap.appendChild(ioBlock("Output", textBox(a.output, { md: true }), { copy: a.output }));
    if (!a.task && !a.output && !under.length) wrap.appendChild(h("p", { class: "hint" }, "Nothing to preview for this span. See Attributes."));
    return wrap;
  }
  wrap.appendChild(attributes(sp, null));
  return wrap;
}

function attributes(sp, t0) {
  const basics = [
    ["span id", sp.span_id],
    ["parent", sp.parent_id || "-"],
    ["status", sp.status],
    ["duration", fmtMs(sp.duration_ms)],
  ];
  if (t0 !== null) basics.push(["offset", `+${fmtMs((sp.start_time - t0) * 1000)}`]);
  basics.push(["started", fmtTime(sp.start_time)]);
  const rows = [...basics, ...Object.entries(sp.attributes || {})];
  const wrap = h("div");
  wrap.appendChild(
    h(
      "dl",
      { class: "kv kv--table" },
      rows.map(([k, v]) => [
        h("dt", null, k),
        h("dd", null, v !== null && typeof v === "object" ? jsonPre(v, { wrap: true }) : typeof v === "string" && v.length > 140 ? h("div", { style: { whiteSpace: "pre-wrap" } }, v) : String(v)),
      ]),
    ),
  );
  if (sp.events && sp.events.length) {
    wrap.appendChild(h("h4", { class: "section-title" }, `Events · ${sp.events.length}`));
    wrap.appendChild(jsonPre(sp.events, { wrap: true }));
  }
  return wrap;
}

function jsonView(sp) {
  let formatted = store.get("trace.jsonFormatted", true);
  const holder = h("div");
  const seg = h("div", { class: "segmented", role: "group", "aria-label": "JSON format" });
  const paint = () => {
    clear(seg);
    for (const [val, label] of [[true, "Formatted"], [false, "Raw"]]) {
      seg.appendChild(h("button", { type: "button", "aria-pressed": String(formatted === val), onclick: () => { formatted = val; store.set("trace.jsonFormatted", val); paint(); } }, label));
    }
    clear(holder).appendChild(formatted ? jsonPre(sp, { wrap: true }) : h("pre", { class: "code wrap" }, JSON.stringify(sp)));
  };
  paint();
  return h(
    "div",
    null,
    h("div", { class: "json-bar" }, seg, h("span", { class: "grow" }), h("button", { class: "btn btn--sm btn--ghost", type: "button", html: `${icon("copy")}<span>Copy</span>`, onclick: () => copyText(JSON.stringify(sp, null, 2)) })),
    holder,
  );
}

export function metaPills(data) {
  const s = data.summary || {};
  const models = data.spans.filter((x) => x.name === "model.generate");
  const prompt = models.reduce((acc, m) => acc + (m.attributes["tokens.prompt"] || 0), 0);
  const completion = models.reduce((acc, m) => acc + (m.attributes["tokens.completion"] || 0), 0);
  const pill = (label, value, opts = {}) =>
    h(opts.href ? "a" : "span", { class: `pill${opts.err ? " pill--err" : ""}`, href: opts.href, title: opts.title || `${label}: ${value}` }, h("b", null, label), h("span", { class: "v" }, value));
  const session = s.attributes && s.attributes["session.id"];
  return h(
    "div",
    { class: "pills" },
    pill("Latency", fmtMs(s.duration_ms)),
    pill("Model", s.model || "-"),
    pill("Tokens", fmtNum(s.total_tokens ?? prompt + completion), { title: `${fmtNum(prompt)} prompt · ${fmtNum(completion)} completion` }),
    pill("Cost", fmtCost(s.cost_usd ?? 0)),
    s.attributes && s.attributes.steps !== undefined ? pill("Steps", String(s.attributes.steps)) : null,
    pill("Tools", String(s.tool_calls ?? 0), { err: !!s.tool_errors, title: s.tool_errors ? `${s.tool_errors} failed` : undefined }),
    session ? pill("Session", session, { href: `#/playground/${encodeURIComponent(session)}`, title: "Open this chat in the Playground" }) : null,
    pill("Started", fmtTime(s.start_time)),
  );
}

// Render the whole detail into `host`. Returns { selectTab(i), focusTree() }.
export function renderTraceDetail(host, data, { tab = 0, onTab } = {}) {
  clear(host);
  const spans = data.spans;
  const t0 = Math.min(...spans.map((x) => x.start_time));
  const t1 = Math.max(...spans.map((x) => x.end_time || x.start_time));
  const total = Math.max((t1 - t0) * 1000, 0.001);
  const s = data.summary || {};
  const top = h("div", { class: "peek-section" }, metaPills(data));
  if (s.error) top.appendChild(h("div", { class: "banner banner--err", role: "alert", style: { margin: "var(--space-3) 0 0" } }, h("strong", null, "Error"), h("div", null, s.error)));
  host.appendChild(top);

  const roots = buildTree(spans);
  const collapsed = new Set();
  const tree = h("ul", { class: "tree", role: "tree", "aria-label": "Spans" });
  const treePane = h("div", { class: "tree-pane" }, tree);
  const detailPane = h("div", { class: "detail-pane" });
  host.appendChild(h("div", { class: "trace-split" }, treePane, detailPane));
  let selected = (roots[0] && roots[0].span.span_id) || null;
  let currentTab = tab;
  let rows = [];

  function paintTree() {
    clear(tree);
    rows = [];
    const walk = (node, depth, guides) => {
      const sp = node.span;
      const kind = kindOf(sp.name);
      const { name, sub } = spanLabel(sp);
      const has = node.children.length > 0;
      const open = !collapsed.has(sp.span_id);
      const left = ((sp.start_time - t0) * 1000) / total;
      const width = Math.max(sp.duration_ms / total, 0.004);
      const toggle = has
        ? h("button", {
            class: "tree-toggle",
            type: "button",
            tabindex: -1,
            "aria-expanded": String(open),
            "aria-label": open ? "Collapse" : "Expand",
            html: icon("chevron"),
            onclick: (e) => {
              e.stopPropagation();
              if (open) collapsed.add(sp.span_id);
              else collapsed.delete(sp.span_id);
              paintTree();
            },
          })
        : h("span", { class: "tree-spacer" });
      const li = h(
        "li",
        {
          class: "tree-row",
          role: "treeitem",
          "aria-level": depth + 1,
          "aria-selected": String(sp.span_id === selected),
          "aria-expanded": has ? String(open) : undefined,
          tabindex: sp.span_id === selected ? 0 : -1,
          "data-id": sp.span_id,
          title: `${sp.name} · ${fmtMs(sp.duration_ms)}`,
          onclick: () => select(sp.span_id, true),
        },
        h(
          "span",
          { class: "tree-name" },
          h("span", { class: "tree-indent" }, guides.map(() => h("i"))),
          toggle,
          h("span", { class: "kind-dot", "data-kind": kind, "data-status": sp.status, "aria-hidden": "true" }),
          h("span", { class: "nm" }, name),
          sub ? h("span", { class: "sub" }, sub) : null,
          sp.status !== "ok" ? h("span", { class: "sr-only" }, "(error)") : null,
        ),
        h("span", { class: "tree-bar", "aria-hidden": "true" }, h("i", { "data-kind": kind, "data-status": sp.status, style: { left: `${Math.min(left, 0.995) * 100}%`, width: `${Math.min(width, 1 - Math.min(left, 0.995)) * 100}%` } })),
        h("span", { class: "tree-ms" }, fmtMs(sp.duration_ms)),
      );
      rows.push({ id: sp.span_id, el: li, node, open, has });
      tree.appendChild(li);
      if (has && open) node.children.forEach((c) => walk(c, depth + 1, [...guides, 1]));
    };
    roots.forEach((r) => walk(r, 0, []));
  }

  tree.addEventListener("keydown", (ev) => {
    const i = rows.findIndex((r) => r.id === selected);
    if (i < 0) return;
    const r = rows[i];
    let target = null;
    if (ev.key === "ArrowDown") target = rows[Math.min(rows.length - 1, i + 1)];
    else if (ev.key === "ArrowUp") target = rows[Math.max(0, i - 1)];
    else if (ev.key === "Home") target = rows[0];
    else if (ev.key === "End") target = rows[rows.length - 1];
    else if (ev.key === "ArrowRight" && r.has && !r.open) {
      collapsed.delete(r.id);
      paintTree();
      rows.find((x) => x.id === selected)?.el.focus();
    } else if (ev.key === "ArrowLeft" && r.has && r.open) {
      collapsed.add(r.id);
      paintTree();
      rows.find((x) => x.id === selected)?.el.focus();
    } else return;
    ev.preventDefault();
    ev.stopPropagation();
    if (target) select(target.id, true);
  });

  let tabsCtl = null;
  function paintDetail() {
    const sp = spans.find((x) => x.span_id === selected) || spans[0];
    clear(detailPane);
    const { name } = spanLabel(sp);
    detailPane.appendChild(
      h(
        "div",
        { class: "detail-head" },
        h("span", { class: "kind-dot", "data-kind": kindOf(sp.name), "data-status": sp.status, "aria-hidden": "true" }),
        h("h3", null, name),
        h("span", { class: "meta" }, `${sp.name} · ${fmtMs(sp.duration_ms)} · +${fmtMs((sp.start_time - t0) * 1000)}`),
        h("span", { class: "grow" }),
        sp.status !== "ok" ? h("span", { class: "chip chip--err" }, "error") : null,
      ),
    );
    tabsCtl = tabs(
      [
        { label: "Preview", render: () => preview(sp, spans) },
        { label: "Attributes", badge: Object.keys(sp.attributes || {}).length, render: () => attributes(sp, t0) },
        { label: "JSON", render: () => jsonView(sp) },
      ],
      {
        initial: currentTab,
        label: "Span detail",
        onChange: (i) => {
          currentTab = i;
          if (onTab) onTab(i);
        },
      },
    );
    detailPane.appendChild(tabsCtl.el);
  }

  function select(id, focus = false) {
    selected = id;
    for (const r of rows) {
      r.el.setAttribute("aria-selected", String(r.id === id));
      r.el.tabIndex = r.id === id ? 0 : -1;
    }
    if (focus) rows.find((r) => r.id === id)?.el.focus({ preventScroll: false });
    paintDetail();
  }

  paintTree();
  paintDetail();
  return {
    selectTab(i) {
      if (tabsCtl) tabsCtl.select(i);
    },
    focusTree() {
      rows.find((r) => r.id === selected)?.el.focus();
    },
  };
}
