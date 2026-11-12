// Settings: appearance, API key, local preferences, and the server's effective configuration.

import { api, getApiKey, promptForKey, setApiKey } from "../api.js";
import { getThemePref, setThemePref } from "../theme.js";
import { chip, clear, errorState, h, icon, jsonPre, loading, toast } from "../ui.js";

// Element.append() would turn null into the text "null"; skip empty slots.
const append = (el, ...kids) => el.append(...kids.filter((k) => k !== null && k !== undefined));

export async function render(root) {
  const page = h("div", { class: "page" });
  root.appendChild(page);
  page.appendChild(h("div", { class: "page-head" }, h("div", null, h("h1", null, "Settings"), h("p", { class: "lede" }, "Browser preferences are stored locally. Server settings come from agentcore.toml, environment variables and CLI flags."))));
  const wrap = h("div", { class: "settings" });
  page.appendChild(wrap);

  // appearance
  const seg = h("div", { class: "segmented", role: "group", "aria-label": "Theme" });
  const paintSeg = () => {
    clear(seg);
    const pref = getThemePref();
    for (const [value, label] of [["system", "System"], ["light", "Light"], ["dark", "Dark"]]) {
      seg.appendChild(h("button", { type: "button", "aria-pressed": pref === value ? "true" : "false", onclick: () => { setThemePref(value); paintSeg(); } }, label));
    }
  };
  paintSeg();
  const onTheme = () => paintSeg();
  window.addEventListener("themechange", onTheme);

  // API key
  const keyStatus = h("span");
  const keyActions = h("div", { class: "inline-form" });
  const paintKey = (health) => {
    clear(keyStatus);
    clear(keyActions);
    const has = !!getApiKey();
    keyStatus.append(health && health.auth ? chip("required by server", "accent") : chip("not required", ""), " ", has ? chip("key saved", "ok") : chip("no key saved"));
    append(
      keyActions,
      h("button", { class: "btn", type: "button", html: `${icon("key")}<span>${has ? "Change key" : "Enter key"}</span>`, onclick: async () => { if (await promptForKey("")) { toast("API key saved"); paintKey(health); } } }),
      has ? h("button", { class: "btn btn--ghost", type: "button", onclick: () => { setApiKey(""); toast("API key removed from this browser"); paintKey(health); } }, "Forget key") : null,
    );
  };

  const resetPrefs = h("button", {
    class: "btn",
    type: "button",
    onclick: () => {
      try {
        for (const k of Object.keys(localStorage)) {
          if (k.startsWith("agentcore.") && k !== "agentcore.apiKey" && k !== "agentcore.theme") localStorage.removeItem(k);
        }
      } catch {
        /* ignore */
      }
      toast("Playground, trace filter and eval preferences reset");
    },
  }, "Reset preferences");

  const row = (title, desc, control) => h("div", { class: "setting-row" }, h("div", null, h("h3", null, title), desc ? h("p", null, desc) : null), h("div", null, control));
  const local = h(
    "section",
    { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", null, "This browser")),
    h(
      "div",
      { class: "panel-body", style: { paddingTop: 0, paddingBottom: 0 } },
      row("Theme", "Follows your operating system unless you pick one.", seg),
      row("API key", "Needed only when the server sets AGENTCORE_API_KEY. Sent as a bearer token.", h("div", { style: { display: "grid", gap: "var(--space-3)" } }, keyStatus, keyActions)),
      row("Preferences", "Playground settings, trace filters and the selected eval suite.", resetPrefs),
    ),
  );
  wrap.appendChild(local);

  const server = h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", null, "Server"), h("div", { class: "actions" }, h("a", { class: "btn btn--sm", href: "/docs", target: "_blank", rel: "noopener", html: `<span>API docs</span>${icon("external")}` }))), h("div", { class: "panel-body" }, loading()));
  wrap.appendChild(server);

  let health = null;
  try {
    health = await (await fetch("/health")).json();
  } catch {
    /* offline */
  }
  paintKey(health);
  const body = server.querySelector(".panel-body");
  try {
    const cfg = await api.get("/api/config");
    clear(body);
    const kv = (pairs) => h("dl", { class: "kv" }, pairs.map(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
    const list = (xs) => (xs && xs.length ? xs.join(", ") : "-");
    body.append(
      kv([
        ["version", `${cfg.version} (python ${cfg.python})`],
        ["config file", cfg.config_file || "none (defaults + env)"],
        ["default model", h("span", { class: "mono" }, cfg.default_model)],
        ["extra models", list(cfg.models)],
        ["enabled tools", h("span", { class: "mono" }, list(cfg.enabled_tools))],
        ["custom tools", list(cfg.custom_tools)],
        ["trace dir", h("span", { class: "mono" }, cfg.trace_dir)],
        ["state dir", h("span", { class: "mono" }, cfg.state_dir)],
        ["eval dirs", h("span", { class: "mono" }, list(cfg.eval_dirs))],
        ["auth", cfg.server.auth_enabled ? "API key required" : "open (no API key)"],
        ["CORS origins", list(cfg.server.cors_origins)],
        ["max request body", `${Math.round(cfg.server.max_body_bytes / 1024)} KB`],
      ]),
      h("h4", { class: "section-title" }, "Raw"),
      jsonPre(cfg),
    );
  } catch (err) {
    clear(body).appendChild(errorState(err));
  }
  return () => window.removeEventListener("themechange", onTheme);
}
