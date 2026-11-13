// Command palette (Ctrl/Cmd+K): jump to a view, run an action, open a recent trace by id or
// name, open a chat, or start an eval suite. Keyboard-first: type, arrows, Enter.

import { api } from "./api.js";
import { toggleTheme } from "./theme.js";
import { clear, debounce, fmtAgo, fmtMs, h, icon, toast } from "./ui.js";

let ctx = null;
const dialog = document.getElementById("palette");
const input = document.getElementById("palette-input");
const list = document.getElementById("palette-list");
let items = [];
let active = 0;
let dynamic = { traces: [], suites: [], chats: [] };
let fetchToken = 0;

// Subsequence match with a bonus for word starts; 0 means no match.
function score(text, q) {
  if (!q) return 1;
  const t = text.toLowerCase();
  const idx = t.indexOf(q);
  if (idx >= 0) return 100 - idx + (idx === 0 || /\W/.test(t[idx - 1]) ? 50 : 0);
  let ti = 0;
  let s = 0;
  for (const ch of q) {
    const found = t.indexOf(ch, ti);
    if (found < 0) return 0;
    s += found === ti ? 3 : 1;
    ti = found + 1;
  }
  return s;
}

function staticCommands() {
  const go = ctx.routes.map((r) => ({
    group: "Go to",
    label: r.label,
    hint: `G ${r.key.toUpperCase()}`,
    icon: r.icon,
    keywords: `view page navigate ${r.id}`,
    run: () => (location.hash = `#/${r.id}`),
  }));
  return [
    { group: "Actions", label: "New chat", hint: "N", icon: "plus", keywords: "create conversation playground", run: () => ctx.newChat() },
    { group: "Actions", label: "Toggle theme", hint: "Shift T", icon: "moon", keywords: "dark light appearance colour color", run: () => toggleTheme() },
    { group: "Actions", label: "Show errors in traces", icon: "alert", keywords: "status:error failed traces filter", run: () => (location.hash = `#/traces?query=${encodeURIComponent("status:error")}`) },
    { group: "Actions", label: "Show slow traces", icon: "clock", keywords: "latency slow p95 traces filter", run: () => (location.hash = `#/traces?chip=slow`) },
    { group: "Actions", label: "Keyboard shortcuts", hint: "?", icon: "keyboard", keywords: "help keys", run: () => ctx.openShortcuts() },
    ...go,
  ];
}

function suiteCommands() {
  if (!dynamic.suites.length) return [];
  return dynamic.suites
    .filter((s) => !s.error)
    .map((s) => ({
      group: "Eval suites",
      label: `Run eval suite: ${s.name}`,
      sub: `${s.cases} cases · ${s.path}`,
      icon: "play",
      keywords: `eval run suite test ${s.path}`,
      run: async () => {
        try {
          const job = await api.post("/api/evals/runs", { suite: s.path });
          toast(`Started ${s.name}`);
          location.hash = `#/evals?suite=${encodeURIComponent(s.path)}&run=${encodeURIComponent(job.id)}`;
        } catch (err) {
          toast(`Could not start the run: ${err.message}`, { kind: "err" });
        }
      },
    }));
}

function traceCommands() {
  return dynamic.traces.map((t) => ({
    group: "Traces",
    label: t.input ? t.input.slice(0, 80) : t.name,
    sub: `${t.name} · ${t.trace_id.slice(0, 8)} · ${fmtMs(t.duration_ms)} · ${fmtAgo(t.start_time)}`,
    icon: t.status === "ok" ? "traces" : "alert",
    tone: t.status === "ok" ? "" : "err",
    keywords: "",
    always: true,
    run: () => (location.hash = `#/traces/${t.trace_id}`),
  }));
}

function chatCommands() {
  return dynamic.chats.map((c) => ({
    group: "Chats",
    label: c.title || "New chat",
    sub: `${c.turns} messages · ${fmtAgo(c.updated)}`,
    icon: "chat",
    keywords: "chat session conversation",
    run: () => (location.hash = `#/playground/${encodeURIComponent(c.id)}`),
  }));
}

function paint() {
  const q = input.value.trim().toLowerCase();
  const pool = [...staticCommands(), ...chatCommands(), ...suiteCommands()];
  const ranked = pool
    .map((c) => ({ c, s: Math.max(score(c.label, q), score(`${c.label} ${c.keywords || ""} ${c.sub || ""}`, q) * 0.6) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => (q ? b.s - a.s : 0));
  // Without a query show actions + navigation first, then recents. With one, best match first.
  const ordered = q ? ranked.map((x) => x.c) : ranked.map((x) => x.c).filter((c) => c.group !== "Eval suites" || dynamic.suites.length <= 4);
  items = q ? [...ordered.slice(0, 12), ...traceCommands()] : [...ordered.filter((c) => c.group !== "Chats"), ...traceCommands().slice(0, 5), ...ordered.filter((c) => c.group === "Chats").slice(0, 4)];
  if (q) {
    // keep groups contiguous in rank order of their best item
    const order = [];
    for (const it of items) if (!order.includes(it.group)) order.push(it.group);
    items.sort((a, b) => order.indexOf(a.group) - order.indexOf(b.group));
  }
  active = Math.min(active, Math.max(0, items.length - 1));
  clear(list);
  if (!items.length) {
    list.appendChild(h("li", { class: "palette-empty", role: "presentation" }, "No matches. Try a view name, an action, a trace id or text from a trace input."));
    input.removeAttribute("aria-activedescendant");
    return;
  }
  let group = null;
  items.forEach((it, i) => {
    if (it.group !== group) {
      group = it.group;
      list.appendChild(h("li", { class: "palette-group", role: "presentation" }, group));
    }
    const li = h(
      "li",
      {
        id: `pal-${i}`,
        class: `palette-item${it.tone ? ` palette-item--${it.tone}` : ""}`,
        role: "option",
        "aria-selected": i === active ? "true" : "false",
        onmousemove: () => {
          if (active !== i) setActive(i, false);
        },
        onclick: () => runItem(i),
      },
      h("span", { class: "pi-icon", html: icon(it.icon || "chevron") }),
      h("span", { class: "pi-text" }, h("span", { class: "pi-label" }, it.label), it.sub ? h("span", { class: "pi-sub" }, it.sub) : null),
      it.hint ? h("kbd", { class: "pi-hint" }, it.hint) : null,
    );
    list.appendChild(li);
  });
  setActive(active, true);
}

function setActive(i, scroll = true) {
  active = i;
  for (const li of list.querySelectorAll(".palette-item")) li.setAttribute("aria-selected", li.id === `pal-${i}` ? "true" : "false");
  input.setAttribute("aria-activedescendant", `pal-${i}`);
  if (scroll) document.getElementById(`pal-${i}`)?.scrollIntoView({ block: "nearest" });
}

function runItem(i) {
  const it = items[i];
  if (!it) return;
  dialog.close();
  it.run();
}

const fetchTraces = debounce(async () => {
  const token = ++fetchToken;
  const q = input.value.trim();
  const params = new URLSearchParams({ limit: q ? 8 : 5 });
  if (q) params.set("query", `"${q.replace(/"/g, "")}"`);
  try {
    const res = await api.get(`/api/traces/explore?${params}`);
    if (token !== fetchToken || !dialog.open) return;
    dynamic.traces = res.items;
    paint();
  } catch {
    /* palette still works without traces */
  }
}, 160);

export function openPalette() {
  if (!ctx || dialog.open) return;
  for (const d of document.querySelectorAll("dialog[open]")) d.close();
  input.value = "";
  active = 0;
  paint();
  dialog.showModal();
  input.focus();
  fetchTraces();
  api.get("/api/evals/suites").then((s) => {
    dynamic.suites = s;
    if (dialog.open) paint();
  }, () => {});
  api.get("/api/sessions").then((s) => {
    dynamic.chats = s.slice(0, 8);
    if (dialog.open) paint();
  }, () => {});
}

export function initPalette(context) {
  ctx = context;
  document.querySelector(".palette-icon").innerHTML = icon("search");
  input.addEventListener("input", () => {
    active = 0;
    paint();
    fetchTraces();
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || (ev.key === "n" && ev.ctrlKey)) {
      ev.preventDefault();
      if (items.length) setActive((active + 1) % items.length);
    } else if (ev.key === "ArrowUp" || (ev.key === "p" && ev.ctrlKey)) {
      ev.preventDefault();
      if (items.length) setActive((active - 1 + items.length) % items.length);
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      runItem(active);
    } else if (ev.key === "Home" && items.length) {
      setActive(0);
    } else if (ev.key === "End" && items.length) {
      setActive(items.length - 1);
    }
  });
  dialog.addEventListener("click", (ev) => {
    if (ev.target === dialog) dialog.close();
  });
}
