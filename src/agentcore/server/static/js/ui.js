// DOM + formatting helpers shared by every view. No innerHTML with untrusted data:
// `h()` builds elements and sets text through textContent.

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "html") el.innerHTML = v; // only for trusted, generated markup (icons, md.js)
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

// --- icons (inline SVG strings we author; safe for innerHTML) ----------------------------
const P = {
  chat: '<path d="M4 5h16v11H9l-5 4z"/>',
  traces: '<path d="M4 6h10M7 12h9M10 18h10"/>',
  evals: '<path d="M9 3h6M10 3v6l-5 10a1.5 1.5 0 0 0 1.3 2h11.4a1.5 1.5 0 0 0 1.3-2L14 9V3"/><path d="M7.5 15h9"/>',
  overview: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  tools: '<path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3z"/><path d="M14.5 6.5 17 4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  send: '<path d="M5 12h13M13 6l6 6-6 6"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  back: '<path d="m15 6-6 6 6 6"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
  play: '<path d="M7 5v14l11-7z"/>',
  sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  sidebar: '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M9 4v16"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3"/>',
};

export function icon(name, cls = "") {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${P[name] || ""}</svg>`;
}

export function iconEl(name, cls = "") {
  const span = document.createElement("span");
  span.innerHTML = icon(name, cls);
  return span.firstElementChild;
}

// --- formatting -------------------------------------------------------------------------
export function fmtMs(ms) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "-";
  if (ms === 0) return "0 ms";
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

export function fmtNum(n) {
  if (n === null || n === undefined) return "-";
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e3).toFixed(1)}k`;
  return Number(n).toLocaleString();
}

export function fmtCost(usd) {
  if (usd === null || usd === undefined) return "-";
  if (usd === 0) return "$0";
  const trim = (x) => x.replace(/(\.\d*?[1-9])0+$/, "$1").replace(/\.0+$/, "");
  if (usd < 0.01) return `$${trim(usd.toFixed(5))}`;
  if (usd < 1) {
    const cents = usd * 100;
    return Math.abs(cents - Math.round(cents)) < 1e-9 ? `$${usd.toFixed(2)}` : `$${trim(usd.toFixed(4))}`;
  }
  return `$${usd.toFixed(2)}`;
}

export function fmtPct(x) {
  if (x === null || x === undefined) return "-";
  return `${(x * 100).toFixed(x === 1 || x === 0 ? 0 : 1)}%`;
}

export function fmtTime(epochSec) {
  if (!epochSec) return "-";
  const d = new Date(epochSec * 1000);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtAgo(epochSec) {
  if (!epochSec) return "-";
  const s = Math.max(0, Date.now() / 1000 - epochSec);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  if (s < 86400 * 14) return `${Math.round(s / 86400)}d ago`;
  return new Date(epochSec * 1000).toLocaleDateString();
}

export function isoAgo(iso) {
  if (!iso) return "-";
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso : fmtAgo(t / 1000);
}

export function shortId(id, n = 8) {
  return id ? String(id).slice(0, n) : "";
}

// --- JSON with light syntax colouring (escaped first) -----------------------------------
export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function jsonPre(value, { wrap = false } = {}) {
  let text;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  if (text === undefined) text = "undefined";
  const pre = h("pre", { class: `code${wrap ? " wrap" : ""}` });
  if (typeof value === "string") {
    pre.textContent = text;
    return pre;
  }
  pre.innerHTML = escapeHtml(text).replace(
    /(&quot;(?:\\.|[^&\\]|&(?!quot;))*?&quot;)(\s*:)?|\b(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b|\b(true|false|null)\b/g,
    (m, str, colon, num, lit) => {
      if (str) return colon ? `<span class="tok-key">${str}</span>${colon}` : `<span class="tok-str">${str}</span>`;
      if (num) return `<span class="tok-num">${num}</span>`;
      if (lit) return `<span class="tok-lit">${lit}</span>`;
      return m;
    },
  );
  return pre;
}

// --- states -----------------------------------------------------------------------------
export function loading(text = "Loading...") {
  return h("div", { class: "loading", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), text);
}

export function emptyState(title, body, action) {
  return h("div", { class: "state" }, h("h3", null, title), body ? h("p", null, body) : null, action || null);
}

export function errorState(err, retry) {
  const msg = err && err.message ? err.message : String(err);
  return h(
    "div",
    { class: "state state--error", role: "alert" },
    h("h3", null, "Something went wrong"),
    h("p", null, msg),
    retry ? h("button", { class: "btn", type: "button", onclick: retry }, "Try again") : null,
  );
}

export function chip(text, kind = "") {
  return h("span", { class: `chip${kind ? ` chip--${kind}` : ""}` }, text);
}

export function statusDot(status) {
  const ok = status === "ok";
  return h("span", { class: `status-dot ${ok ? "ok" : "err"}` }, h("span", { class: "dot" }), h("span", { class: "txt" }, ok ? "ok" : "error"));
}

// --- toasts -----------------------------------------------------------------------------
export function toast(message, { kind = "", action, timeout = 4000 } = {}) {
  const host = document.getElementById("toasts");
  const el = h("div", { class: `toast${kind ? ` toast--${kind}` : ""}` }, h("span", null, message));
  if (action) {
    el.appendChild(
      h("button", { type: "button", onclick: () => { action.run(); el.remove(); } }, action.label),
    );
  }
  host.appendChild(el);
  setTimeout(() => el.remove(), timeout);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied");
  } catch {
    toast("Copy failed: clipboard not available", { kind: "err" });
  }
}

// --- persisted preferences (best effort) --------------------------------------------------
export const store = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem(`agentcore.${key}`);
      return v === null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      if (value === undefined || value === null) localStorage.removeItem(`agentcore.${key}`);
      else localStorage.setItem(`agentcore.${key}`, JSON.stringify(value));
    } catch {
      /* storage unavailable: preferences just do not persist */
    }
  },
};

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}
