// App shell: hash router, sectioned sidebar, global keyboard shortcuts, command palette,
// theme and server status.

import { api } from "./api.js";
import { initPalette, openPalette } from "./palette.js";
import { initTheme, toggleTheme } from "./theme.js";
import { clear, errorState, h, icon, isTyping, modKey } from "./ui.js";

export const ROUTES = [
  { id: "playground", label: "Playground", icon: "chat", section: "Build", key: "p", load: () => import("./views/playground.js") },
  { id: "tools", label: "Tools", icon: "tools", section: "Build", key: "l", load: () => import("./views/tools.js") },
  { id: "traces", label: "Traces", icon: "traces", section: "Observe", key: "t", load: () => import("./views/traces.js") },
  { id: "overview", label: "Overview", icon: "overview", section: "Observe", key: "o", load: () => import("./views/overview.js") },
  { id: "evals", label: "Evals", icon: "evals", section: "Evaluate", key: "e", load: () => import("./views/evals.js") },
  { id: "settings", label: "Settings", icon: "settings", section: null, key: "s", load: () => import("./views/settings.js") },
];

// Shown in the "?" dialog. View-specific keys are handled by the views themselves.
export const SHORTCUTS = [
  {
    group: "Everywhere",
    keys: [
      [[modKey, "K"], "Command palette: views, actions, traces, eval suites"],
      [["?"], "Show this help"],
      [["N"], "New chat"],
      [["G", "P"], "Go to Playground"],
      [["G", "T"], "Go to Traces"],
      [["G", "E"], "Go to Evals"],
      [["G", "O"], "Go to Overview"],
      [["G", "L"], "Go to Tools"],
      [["G", "S"], "Go to Settings"],
      [["Shift", "T"], "Toggle light / dark theme"],
    ],
  },
  {
    group: "Traces",
    keys: [
      [["/"], "Focus the query bar"],
      [["J"], "Next trace"],
      [["K"], "Previous trace"],
      [["Enter"], "Open the selected trace in the side peek"],
      [["Esc"], "Close the side peek"],
      [["1", "2", "3"], "Peek tabs: Preview, Attributes, JSON"],
    ],
  },
  {
    group: "Playground",
    keys: [
      [["Enter"], "Send message"],
      [["Shift", "Enter"], "New line"],
      [["/"], "Focus the composer"],
      [["."], "Show / hide run settings"],
    ],
  },
  {
    group: "Evals",
    keys: [
      [["←", "↑", "→", "↓"], "Move between matrix cells"],
      [["Enter"], "Open the case in the side peek"],
    ],
  },
];

const view = document.getElementById("view");
const nav = document.getElementById("nav");
let cleanup = null;
let renderToken = 0;

const app = { health: null };

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, query = ""] = raw.split("?");
  const segments = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
  const params = Object.fromEntries(new URLSearchParams(query));
  return { route: segments[0] || "playground", segments: segments.slice(1), params };
}

export function navigate(hash, { replace = false } = {}) {
  if (replace) history.replaceState(null, "", hash);
  else location.hash = hash;
  if (replace) render();
}

function buildNav() {
  clear(nav);
  let section = undefined;
  let list = null;
  for (const r of ROUTES) {
    if (!r.section) continue;
    if (r.section !== section) {
      section = r.section;
      const id = `nav-sec-${section.toLowerCase()}`;
      nav.appendChild(h("h2", { class: "nav-section", id }, section));
      list = h("ul", { class: "nav-list", "aria-labelledby": id });
      nav.appendChild(list);
    }
    list.appendChild(
      h(
        "li",
        null,
        h("a", {
          href: `#/${r.id}`,
          "data-route": r.id,
          "aria-keyshortcuts": `G ${r.key.toUpperCase()}`,
          html: `${icon(r.icon)}<span>${r.label}</span><kbd class="nav-key" aria-hidden="true">G ${r.key.toUpperCase()}</kbd>`,
        }),
      ),
    );
  }
  const settings = document.getElementById("nav-settings");
  settings.innerHTML = `${icon("settings")}<span>Settings</span>`;
  const help = document.getElementById("shortcuts-btn");
  help.innerHTML = `${icon("keyboard")}<span>Shortcuts</span><kbd class="nav-key" aria-hidden="true">?</kbd>`;
  help.addEventListener("click", openShortcuts);
}

function markNav(route) {
  for (const a of document.querySelectorAll("#nav a, #nav-settings")) {
    if (a.dataset.route === route) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

async function render() {
  const { route, segments, params } = parseHash();
  const def = ROUTES.find((r) => r.id === route);
  closeNav();
  if (!def) {
    navigate("#/playground", { replace: true });
    return;
  }
  markNav(route);
  document.title = `${def.label} · AgentCore`;
  const token = ++renderToken;
  if (cleanup) {
    try {
      cleanup();
    } catch {
      /* ignore */
    }
    cleanup = null;
  }
  try {
    const mod = await def.load();
    if (token !== renderToken) return;
    clear(view);
    view.dataset.route = route;
    view.scrollTop = 0;
    cleanup = (await mod.render(view, { segments, params, navigate })) || null;
  } catch (err) {
    if (token !== renderToken) return;
    clear(view);
    view.appendChild(h("div", { class: "page" }, errorState(err, render)));
  }
}

// --- mobile navigation --------------------------------------------------------------------
const menuBtn = document.getElementById("menu-btn");
const scrim = document.getElementById("scrim");
menuBtn.innerHTML = icon("menu");
function openNav() {
  document.body.classList.add("nav-open");
  scrim.hidden = false;
  menuBtn.setAttribute("aria-expanded", "true");
  nav.querySelector("a")?.focus();
}
function closeNav() {
  if (!document.body.classList.contains("nav-open")) return;
  document.body.classList.remove("nav-open");
  scrim.hidden = true;
  menuBtn.setAttribute("aria-expanded", "false");
}
menuBtn.addEventListener("click", () => (document.body.classList.contains("nav-open") ? closeNav() : openNav()));
scrim.addEventListener("click", closeNav);

// --- shortcuts help -------------------------------------------------------------------------
const shortcutsDialog = document.getElementById("shortcuts");
function openShortcuts() {
  if (shortcutsDialog.open) return;
  const groups = document.getElementById("shortcut-groups");
  clear(groups);
  for (const g of SHORTCUTS) {
    groups.appendChild(
      h(
        "section",
        { class: "shortcut-group" },
        h("h3", null, g.group),
        h(
          "dl",
          null,
          g.keys.map(([keys, desc]) => [h("dt", null, keys.map((k) => h("kbd", null, k))), h("dd", null, desc)]),
        ),
      ),
    );
  }
  shortcutsDialog.showModal();
}
document.getElementById("shortcuts-close").innerHTML = icon("x");
document.getElementById("shortcuts-close").addEventListener("click", () => shortcutsDialog.close());
shortcutsDialog.addEventListener("click", (ev) => {
  if (ev.target === shortcutsDialog) shortcutsDialog.close();
});

export function newChat() {
  if (location.hash.replace(/\?.*$/, "") === "#/playground") window.dispatchEvent(new CustomEvent("agentcore:new-chat"));
  else location.hash = "#/playground";
}

// --- global keyboard ------------------------------------------------------------------------
let gPending = 0;
document.addEventListener("keydown", (ev) => {
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && ev.key.toLowerCase() === "k") {
    ev.preventDefault();
    openPalette();
    return;
  }
  if (ev.key === "Escape") closeNav();
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey || isTyping(ev)) return;
  if (ev.target instanceof Element && ev.target.closest("dialog[open]")) return;
  if (gPending && Date.now() - gPending < 1200) {
    gPending = 0;
    const r = ROUTES.find((x) => x.key === ev.key.toLowerCase());
    if (r) {
      ev.preventDefault();
      location.hash = `#/${r.id}`;
    }
    return;
  }
  gPending = 0;
  if (ev.key === "?") {
    ev.preventDefault();
    openShortcuts();
  } else if (ev.key === "g") {
    gPending = Date.now();
  } else if (ev.key === "n") {
    ev.preventDefault();
    newChat();
  } else if (ev.key === "T" && ev.shiftKey) {
    ev.preventDefault();
    toggleTheme();
  }
});

// --- server status --------------------------------------------------------------------------
async function refreshHealth() {
  const el = document.getElementById("server-status");
  const dot = el.querySelector(".dot");
  const text = el.querySelector(".server-text");
  try {
    const resp = await fetch("/health");
    const health = await resp.json();
    app.health = health;
    dot.className = "dot ok";
    text.textContent = `${health.model}${health.auth ? " · key" : ""}`;
    el.title = `Server v${health.version} · model ${health.model} · tools: ${health.tools.join(", ")}`;
  } catch {
    dot.className = "dot err";
    text.textContent = "server offline";
    el.title = "Cannot reach the server";
  }
}

buildNav();
initTheme();
initPalette({ routes: ROUTES, openShortcuts, newChat });
for (const b of document.querySelectorAll("[data-palette]")) b.addEventListener("click", () => openPalette());
document.querySelector(".jump .jump-icon").innerHTML = icon("search");
document.querySelector(".jump .kbd-hint").textContent = `${modKey} K`;
document.querySelector(".topbar .palette-btn").innerHTML = icon("search");
window.addEventListener("hashchange", render);
refreshHealth();
setInterval(refreshHealth, 30000);
if (!location.hash) history.replaceState(null, "", "#/playground");
render();

// keep a reference for debugging in devtools
window.agentcore = { api, app, navigate };
