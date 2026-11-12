// App shell: hash router, navigation rail, theme, server status.

import { api } from "./api.js";
import { initTheme } from "./theme.js";
import { clear, errorState, h, icon } from "./ui.js";

const ROUTES = [
  { id: "playground", label: "Playground", icon: "chat", load: () => import("./views/playground.js") },
  { id: "traces", label: "Traces", icon: "traces", load: () => import("./views/traces.js") },
  { id: "evals", label: "Evals", icon: "evals", load: () => import("./views/evals.js") },
  { id: "overview", label: "Overview", icon: "overview", load: () => import("./views/overview.js") },
  { id: "tools", label: "Tools", icon: "tools", load: () => import("./views/tools.js") },
  { id: "settings", label: "Settings", icon: "settings", load: () => import("./views/settings.js") },
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
  for (const r of ROUTES) {
    nav.appendChild(h("a", { href: `#/${r.id}`, "data-route": r.id, html: `${icon(r.icon)}<span>${r.label}</span>` }));
  }
}

function markNav(route) {
  for (const a of nav.querySelectorAll("a")) {
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
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeNav();
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
window.addEventListener("hashchange", render);
refreshHealth();
setInterval(refreshHealth, 30000);
if (!location.hash) history.replaceState(null, "", "#/playground");
render();

// keep a reference for debugging in devtools
window.agentcore = { api, app, navigate };
