// Playground: multi-turn chat streamed over SSE with server-side sessions. Each reply starts
// with a collapsible run summary ("Worked for 1.2s · 2 tool calls · 183 tokens") that expands
// into a step timeline; run settings live in a collapsible right-hand panel.

import { api, streamSSE } from "../api.js";
import { renderMarkdown } from "../md.js";
import { argsList, resultBox } from "../trace-detail.js";
import {
  clear,
  copyText,
  errorState,
  fmtAgo,
  fmtCost,
  fmtMs,
  fmtNum,
  h,
  icon,
  isTyping,
  loading,
  plural,
  store,
  toast,
} from "../ui.js";

const EXAMPLES = ["What is 17 * 23 + 4?", "Compute (12 + 8) * 3 - 5.", "What is 2 ** 16 / 4?", "What time is it?"];
const DEFAULTS = { model: "", tools: null, system_prompt: "", max_steps: 8 };

function compactArgs(args) {
  const entries = Object.entries(args || {});
  if (!entries.length) return "()";
  return entries.map(([k, v]) => `${k}: ${typeof v === "string" ? JSON.stringify(v) : JSON.stringify(v)}`).join(", ");
}

function oneLine(s, n = 120) {
  const t = String(s ?? "").replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

export async function render(root, { segments }) {
  const state = {
    settings: { ...DEFAULTS, ...store.get("pg.settings", {}) },
    sessions: [],
    sessionId: segments[0] || null,
    session: null,
    tools: [],
    defaultModel: "",
    running: null, // { controller, sessionId }
    pendingDeletes: new Map(),
  };

  const sessionList = h("ul", { class: "session-list", "aria-label": "Chats" });
  const titleEl = h("h1", null, "New chat");
  const thread = h("div", { class: "thread" });
  const threadInner = h("div", { class: "thread-inner", role: "log", "aria-live": "polite", "aria-relevant": "additions" });
  thread.appendChild(threadInner);
  const input = h("textarea", { rows: 1, placeholder: "Message the agent...", "aria-label": "Message", maxlength: 100000, "aria-keyshortcuts": "/" });
  const sendBtn = h("button", { class: "btn btn--primary", type: "submit", html: `${icon("send")}<span>Send</span>` });
  const settingsSummary = h("button", { class: "btn btn--ghost btn--sm settings-summary", type: "button", title: "Run settings (.)" });
  const composer = h(
    "form",
    { class: "composer" },
    h("div", { class: "composer-inner" }, input, sendBtn),
    h("div", { class: "composer-hint" }, h("span", { html: "<kbd>Enter</kbd> send · <kbd>Shift</kbd> <kbd>Enter</kbd> new line" }), h("span", { class: "grow" }), settingsSummary),
  );

  const settingsPanel = h("aside", { class: "pg-settings", id: "pg-settings", "aria-label": "Run settings" });
  const sessionsBtn = h("button", { class: "icon-btn only-narrow", type: "button", "aria-label": "Show chats", html: icon("sidebar") });
  const settingsBtn = h("button", {
    class: "icon-btn settings-btn",
    type: "button",
    "aria-label": "Run settings",
    "aria-controls": "pg-settings",
    title: "Run settings (.)",
    html: icon("panel"),
  });
  const newBtn = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "New chat (N)", title: "New chat (N)", html: icon("plus") });

  const pg = h(
    "div",
    { class: "pg" },
    h("aside", { class: "pg-sessions", "aria-label": "Chat history" }, h("div", { class: "pg-sessions-head" }, h("h2", null, "Chats"), newBtn), sessionList),
    h("section", { class: "pg-main", "aria-label": "Conversation" }, h("div", { class: "pg-bar" }, sessionsBtn, titleEl, settingsBtn), thread, composer),
    settingsPanel,
  );
  root.appendChild(h("div", { class: "page page--full" }, pg));

  // --- panels ---------------------------------------------------------------------------------
  const narrow = () => matchMedia("(max-width: 1024px)").matches;
  let settingsOpen = narrow() ? false : store.get("pg.settingsOpen", true);
  function paintSettingsOpen() {
    settingsPanel.dataset.collapsed = String(!settingsOpen);
    settingsBtn.setAttribute("aria-expanded", String(settingsOpen));
    settingsBtn.classList.toggle("is-on", settingsOpen);
  }
  function toggleSettings(on = !settingsOpen) {
    settingsOpen = on;
    if (!narrow()) store.set("pg.settingsOpen", on);
    paintSettingsOpen();
    if (on && narrow()) settingsPanel.querySelector("input, textarea, button")?.focus();
  }
  paintSettingsOpen();
  settingsBtn.addEventListener("click", () => toggleSettings());
  settingsSummary.addEventListener("click", () => toggleSettings(true));
  sessionsBtn.addEventListener("click", () => pg.classList.toggle("sessions-open"));
  const closeDrawers = () => {
    pg.classList.remove("sessions-open");
    if (narrow() && settingsOpen) toggleSettings(false);
  };
  const onKey = (ev) => {
    if (ev.target instanceof Element && ev.target.closest("dialog[open]")) return;
    if (ev.key === "Escape") {
      closeDrawers();
      return;
    }
    if (ev.ctrlKey || ev.metaKey || ev.altKey || isTyping(ev)) return;
    if (ev.key === "/") {
      ev.preventDefault();
      input.focus();
    } else if (ev.key === ".") {
      ev.preventDefault();
      toggleSettings();
    }
  };
  document.addEventListener("keydown", onKey);
  thread.addEventListener("click", () => pg.classList.remove("sessions-open"));
  const onNewChat = () => newChat();
  window.addEventListener("agentcore:new-chat", onNewChat);

  // --- settings panel ---------------------------------------------------------------------------
  function saveSettings() {
    store.set("pg.settings", state.settings);
    paintSummary();
  }
  function enabledTools() {
    const all = state.tools.map((t) => t.name);
    return state.settings.tools === null ? all : state.settings.tools.filter((t) => all.includes(t));
  }
  function paintSummary() {
    const tools = enabledTools();
    const model = state.settings.model || state.defaultModel || "server default";
    const text = `${model} · ${plural(tools.length, "tool")} · ${state.settings.max_steps} steps`;
    settingsSummary.textContent = text;
  }

  async function buildSettings() {
    clear(settingsPanel);
    const closeBtn = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Close run settings", html: icon("x"), onclick: () => toggleSettings(false) });
    settingsPanel.appendChild(h("div", { class: "ps-head" }, h("h2", null, "Run settings"), closeBtn));

    const modelInput = h("input", { class: "input mono", list: "pg-models", value: state.settings.model, placeholder: "server default", spellcheck: "false", autocomplete: "off", id: "pg-model" });
    const datalist = h("datalist", { id: "pg-models" });
    modelInput.addEventListener("change", () => {
      state.settings.model = modelInput.value.trim();
      saveSettings();
    });
    settingsPanel.appendChild(
      h(
        "section",
        { class: "ps-section" },
        h("div", { class: "ps-label" }, h("label", { class: "label", for: "pg-model" }, "Model")),
        modelInput,
        datalist,
        h("p", { class: "ps-help" }, "Pick one or type any spec: mock, ollama:<model>, openai:<model>."),
      ),
    );

    const toolBox = h("div", { class: "tool-toggles", role: "group", "aria-labelledby": "pg-tools-label" }, loading("Loading tools..."));
    const toolCount = h("span", { class: "val" });
    settingsPanel.appendChild(h("section", { class: "ps-section" }, h("div", { class: "ps-label" }, h("span", { class: "label", id: "pg-tools-label" }, "Tools"), toolCount), toolBox));

    const stepsVal = h("span", { class: "val" }, String(state.settings.max_steps));
    const range = h("input", { class: "range", type: "range", min: 1, max: 20, value: Math.min(20, state.settings.max_steps), id: "pg-steps-range", "aria-label": "Max steps" });
    const steps = h("input", { class: "input", type: "number", min: 1, max: 50, value: state.settings.max_steps, id: "pg-steps", "aria-label": "Max steps (exact)" });
    const setSteps = (v) => {
      const n = Math.min(50, Math.max(1, parseInt(v, 10) || 8));
      state.settings.max_steps = n;
      steps.value = n;
      range.value = Math.min(20, n);
      stepsVal.textContent = String(n);
      saveSettings();
    };
    range.addEventListener("input", () => setSteps(range.value));
    steps.addEventListener("change", () => setSteps(steps.value));
    settingsPanel.appendChild(
      h(
        "section",
        { class: "ps-section" },
        h("div", { class: "ps-label" }, h("label", { class: "label", for: "pg-steps-range" }, "Max steps"), stepsVal),
        h("div", { class: "steps-row" }, range, steps),
        h("p", { class: "ps-help" }, "Upper bound on model calls per turn."),
      ),
    );

    const sys = h("textarea", { class: "textarea", rows: 6, id: "pg-system", placeholder: "Use the server's default system prompt" });
    sys.value = state.settings.system_prompt;
    const sysCount = h("span", { class: "val" }, state.settings.system_prompt ? `${state.settings.system_prompt.length} chars` : "default");
    sys.addEventListener("input", () => (sysCount.textContent = sys.value ? `${sys.value.length} chars` : "default"));
    sys.addEventListener("change", () => {
      state.settings.system_prompt = sys.value;
      saveSettings();
    });
    settingsPanel.appendChild(h("section", { class: "ps-section" }, h("div", { class: "ps-label" }, h("label", { class: "label", for: "pg-system" }, "System prompt"), sysCount), sys));
    settingsPanel.appendChild(
      h(
        "section",
        { class: "ps-section" },
        h("button", {
          class: "btn btn--sm",
          type: "button",
          onclick: () => {
            state.settings = { ...DEFAULTS };
            saveSettings();
            buildSettings();
          },
        }, "Reset to defaults"),
        h("p", { class: "ps-help" }, "Settings apply to the next message and are saved in this browser."),
      ),
    );

    api.get("/v1/models").then(
      (res) => {
        for (const m of res.data) datalist.appendChild(h("option", { value: m.id }, m.default ? "server default" : ""));
        const def = res.data.find((m) => m.default);
        if (def) {
          state.defaultModel = def.id;
          modelInput.placeholder = `${def.id} (server default)`;
          paintSummary();
        }
      },
      () => {},
    );
    try {
      state.tools = await api.get("/api/tools");
      clear(toolBox);
      if (!state.tools.length) toolBox.appendChild(h("p", { class: "hint" }, "No tools are enabled on this server."));
      const on = new Set(enabledTools());
      const paintCount = () => (toolCount.textContent = `${enabledTools().length}/${state.tools.length}`);
      for (const t of state.tools) {
        const cb = h("input", { type: "checkbox", class: "switch", role: "switch", checked: on.has(t.name), id: `pg-tool-${t.name}` });
        cb.addEventListener("change", () => {
          const current = new Set(enabledTools());
          if (cb.checked) current.add(t.name);
          else current.delete(t.name);
          state.settings.tools = state.tools.map((x) => x.name).filter((n) => current.has(n));
          saveSettings();
          paintCount();
        });
        toolBox.appendChild(
          h("label", { class: "tool-toggle", for: `pg-tool-${t.name}`, title: t.description }, h("span", { class: "tt-text" }, h("span", { class: "tt-name" }, t.name), h("span", { class: "tt-desc" }, t.description || t.category)), cb),
        );
      }
      paintCount();
      paintSummary();
    } catch (err) {
      clear(toolBox).appendChild(h("p", { class: "field-error" }, `Could not load tools: ${err.message}`));
    }
  }

  // --- sessions ---------------------------------------------------------------------------------
  async function loadSessions() {
    try {
      state.sessions = (await api.get("/api/sessions")).filter((s) => !state.pendingDeletes.has(s.id));
      paintSessions();
    } catch (err) {
      clear(sessionList).appendChild(h("li", null, h("p", { class: "field-error small" }, err.message)));
    }
  }
  function paintSessions() {
    clear(sessionList);
    if (!state.sessions.length) {
      sessionList.appendChild(h("li", null, h("p", { class: "hint", style: { padding: "8px" } }, "No chats yet. Conversations are saved on the server.")));
      return;
    }
    for (const s of state.sessions) {
      const item = h(
        "button",
        {
          class: "session-item",
          type: "button",
          "aria-current": s.id === state.sessionId ? "true" : "false",
          onclick: () => {
            pg.classList.remove("sessions-open");
            if (s.id !== state.sessionId) openSession(s.id);
          },
        },
        h("span", { class: "session-title" }, s.title || "New chat"),
        h("span", { class: "session-meta" }, `${plural(s.turns, "message")} · ${fmtAgo(s.updated)}`),
      );
      const del = h("button", { class: "icon-btn session-del", type: "button", "aria-label": `Delete chat "${s.title}"`, html: icon("trash"), onclick: () => deleteSession(s) });
      sessionList.appendChild(h("li", null, item, del));
    }
  }
  function deleteSession(s) {
    if (state.running && state.running.sessionId === s.id) {
      toast("Stop the running turn before deleting this chat.", { kind: "err" });
      return;
    }
    state.sessions = state.sessions.filter((x) => x.id !== s.id);
    const timer = setTimeout(async () => {
      state.pendingDeletes.delete(s.id);
      try {
        await api.del(`/api/sessions/${encodeURIComponent(s.id)}`);
      } catch (err) {
        toast(`Delete failed: ${err.message}`, { kind: "err" });
        loadSessions();
      }
    }, 5000);
    state.pendingDeletes.set(s.id, timer);
    if (s.id === state.sessionId) newChat();
    paintSessions();
    toast("Chat deleted", {
      timeout: 5000,
      action: {
        label: "Undo",
        run: () => {
          clearTimeout(timer);
          state.pendingDeletes.delete(s.id);
          loadSessions();
        },
      },
    });
  }

  function setHash(id) {
    history.replaceState(null, "", id ? `#/playground/${encodeURIComponent(id)}` : "#/playground");
  }

  function newChat() {
    if (state.running) {
      toast("Wait for the current turn to finish or stop it first.");
      return;
    }
    state.sessionId = null;
    state.session = null;
    titleEl.textContent = "New chat";
    setHash(null);
    paintSessions();
    paintThread();
    pg.classList.remove("sessions-open");
    input.focus();
  }

  async function openSession(id) {
    if (state.running) {
      toast("Wait for the current turn to finish or stop it first.");
      return;
    }
    state.sessionId = id;
    setHash(id);
    paintSessions();
    clear(threadInner).appendChild(loading("Loading chat..."));
    try {
      state.session = await api.get(`/api/sessions/${encodeURIComponent(id)}`);
      titleEl.textContent = state.session.title || "Chat";
      paintThread();
    } catch (err) {
      if (err.status === 404) {
        toast("That chat no longer exists.");
        newChat();
        return;
      }
      clear(threadInner).appendChild(errorState(err, () => openSession(id)));
    }
  }

  // --- thread rendering ---------------------------------------------------------------------------
  function mockNotice() {
    const slot = h("div");
    if (state.settings.model && !/^mock\b/.test(state.settings.model)) return slot;
    if (store.get("pg.mockNoticeDismissed", false)) return slot;
    api
      .get("/api/config")
      .then((cfg) => {
        if (!/^mock\b/.test(String(cfg.default_model || ""))) return;
        const close = h("button", { class: "btn btn--ghost btn--sm", type: "button" }, "Got it");
        close.addEventListener("click", () => {
          store.set("pg.mockNoticeDismissed", true);
          slot.remove();
        });
        slot.appendChild(
          h(
            "div",
            { class: "banner banner--warn mock-notice", role: "note" },
            h(
              "div",
              null,
              h("strong", null, "You're using the offline mock model. "),
              "It handles arithmetic and simple tool calls so you can explore without a model server. For real answers, restart with ",
              h("code", null, "agentcore serve --model ollama:qwen2.5:7b"),
              ", or set ",
              h("code", null, "OPENAI_BASE_URL"),
              " and use ",
              h("code", null, "--model openai:<name>"),
              ". You can also pick a model in Run settings.",
            ),
            close,
          ),
        );
      })
      .catch(() => {});
    return slot;
  }

  function intro() {
    return h(
      "div",
      { class: "intro" },
      h("h2", null, "Ask the agent something"),
      h("p", null, "Replies stream in. Each one starts with a short run summary you can expand into the full step timeline: model calls, tool arguments and results, timings. Every reply links to its trace."),
      mockNotice(),
      h("div", { class: "examples" }, EXAMPLES.map((q) => h("button", { class: "example", type: "button", onclick: () => { input.value = q; send(); } }, q))),
    );
  }

  function paintThread() {
    clear(threadInner);
    const turns = (state.session && state.session.messages) || [];
    if (!turns.length) {
      threadInner.appendChild(intro());
      return;
    }
    for (const t of turns) {
      if (t.role === "user") threadInner.appendChild(userMsg(t.content));
      else threadInner.appendChild(assistantMsg(t).el);
    }
    requestAnimationFrame(() => (thread.scrollTop = thread.scrollHeight));
  }

  function userMsg(text) {
    return h("div", { class: "msg msg--user" }, h("div", { class: "msg-who" }, "You"), h("div", { class: "msg-body" }, text));
  }

  function contextChips(ctx) {
    if (!ctx) return null;
    const chips = [];
    chips.push(h("span", { class: "ctx-chip", title: "System prompt" }, `${ctx.system_prompt === "custom" ? "Custom" : "Default"} system prompt`));
    if (ctx.memory_messages) chips.push(h("span", { class: "ctx-chip", title: "Earlier messages from this chat" }, `${plural(ctx.memory_messages, "earlier message")}`));
    for (const t of ctx.tools || []) chips.push(h("span", { class: "ctx-chip mono", title: "Tool available to the model" }, t));
    if (!(ctx.tools || []).length) chips.push(h("span", { class: "ctx-chip" }, "no tools"));
    return h("div", { class: "ctx" }, h("span", null, "Added to context"), chips);
  }

  function metaRow(t) {
    const items = [];
    if (t.model) items.push(h("span", { class: "mono" }, t.model));
    if (t.cost_usd) items.push(h("span", null, fmtCost(t.cost_usd)));
    if (t.status && t.status !== "ok" && t.status !== "running") items.push(h("span", { class: t.status === "error" ? "chip chip--err" : "chip chip--warn" }, t.status));
    if (t.trace_id) items.push(h("a", { href: `#/traces/${t.trace_id}` }, "View trace"));
    if (t.content) items.push(h("button", { class: "btn btn--ghost btn--sm", type: "button", "aria-label": "Copy answer", title: "Copy answer", html: icon("copy"), onclick: () => copyText(t.content) }));
    return h("div", { class: "msg-meta" }, items);
  }

  // Builds an assistant message; returns handles so streaming can update it in place.
  function assistantMsg(turn) {
    const parts = (turn.parts || []).map((p) => ({ ...p }));
    const info = { status: turn.status || "ok", steps: turn.steps || 0, started: performance.now(), context: turn.context, ...turn };
    const textEl = h("div", { class: "md msg-text" });
    const notes = h("div");
    const meta = h("div", { class: "msg-foot" });
    const rs = h("div", { class: "rs", "data-open": "false" });
    const toggle = h("button", { class: "rs-toggle", type: "button", "aria-expanded": "false" });
    const rsBody = h("div", { class: "rs-body", hidden: true });
    rs.append(toggle, rsBody);
    const body = h("div", { class: "msg-body" }, rs, textEl, notes);
    const el = h("div", { class: "msg msg--assistant" }, body, meta);
    const openDetails = new Set();
    let raf = 0;
    let timer = 0;

    toggle.addEventListener("click", () => {
      const open = rs.dataset.open !== "true";
      rs.dataset.open = String(open);
      toggle.setAttribute("aria-expanded", String(open));
      rsBody.hidden = !open;
      if (open) paintTimeline();
    });

    const toolParts = () => parts.filter((p) => p.type === "tool");
    const maxToolStep = () => Math.max(-1, ...toolParts().map((p) => p.step ?? 0));
    // Text after the last tool call is the answer; earlier text is the model "thinking aloud".
    const answerText = () => parts.filter((p) => p.type === "text" && (p.step ?? 0) > maxToolStep()).map((p) => p.content).join("");

    function paintText() {
      raf = 0;
      const txt = answerText() || (info.status !== "running" && !parts.some((p) => p.type === "text") ? info.content || "" : "");
      textEl.innerHTML = renderMarkdown(txt);
      textEl.classList.toggle("cursor", info.status === "running" && !!txt);
      textEl.hidden = !txt && info.status !== "running";
    }

    function summaryLine() {
      const tools = toolParts();
      const failed = tools.filter((p) => p.status === "error").length;
      const running = info.status === "running";
      const elapsed = running ? performance.now() - info.started : info.duration_ms;
      const lead = running ? "Working" : info.status === "stopped" ? "Stopped" : info.status === "error" ? "Failed" : "Worked";
      const dur = elapsed ? `${running ? "" : info.status === "ok" ? " for " : " after "}${fmtMs(elapsed)}` : "";
      const bits = [];
      if (tools.length) bits.push(plural(tools.length, "tool call"));
      else if (info.steps) bits.push(plural(info.steps, "step"));
      const tok = info.usage ? info.usage.total_tokens : parts.filter((p) => p.type === "model").reduce((a, p) => a + (p.tokens || 0), 0);
      if (tok) bits.push(`${fmtNum(tok)} tokens`);
      clear(toggle).append(
        ...[
          running ? h("span", { class: "spinner", "aria-hidden": "true" }) : h("span", { html: icon("chevron", "chev") }),
          h("span", { class: "lead" }, `${lead}${dur}`),
          bits.length ? h("span", { class: "bits" }, `· ${bits.join(" · ")}`) : null,
          failed ? h("span", { class: "err" }, `· ${failed} failed`) : null,
        ].filter(Boolean),
      );
      toggle.setAttribute("aria-label", `${toggle.textContent.replace(/\s+/g, " ").trim()}. ${rs.dataset.open === "true" ? "Hide" : "Show"} steps`);
    }

    function tlItem(kind, { title, sub, meta, status, mono, children } = {}) {
      return h(
        "li",
        { class: "tl-item", "data-kind": kind, "data-status": status },
        h("span", { class: "tl-dot", "aria-hidden": "true" }),
        h("div", { class: "tl-line" }, h("span", { class: `tl-title${mono ? " mono" : ""}` }, title), sub ? h("span", { class: "tl-sub", title: sub }, sub) : h("span", { class: "tl-sub" }), meta ? h("span", { class: "tl-meta" }, meta) : null),
        children || null,
      );
    }

    function paintTimeline() {
      if (rs.dataset.open !== "true") return;
      clear(rsBody);
      const ctx = contextChips(info.context);
      if (ctx) rsBody.appendChild(ctx);
      const list = h("ol", { class: "timeline", "aria-label": "Steps" });
      const stepNums = [...new Set(parts.map((p) => p.step).filter((s) => typeof s === "number"))].sort((a, b) => a - b);
      if (!stepNums.length && info.steps) for (let i = 1; i <= info.steps; i++) stepNums.push(i);
      const maxTool = maxToolStep();
      for (const step of stepNums) {
        const model = parts.find((p) => p.type === "model" && p.step === step);
        const thought = parts.filter((p) => p.type === "text" && p.step === step && step <= maxTool).map((p) => p.content).join("");
        const tools = parts.filter((p) => p.type === "tool" && p.step === step);
        const pending = !model && info.status === "running";
        list.appendChild(
          tlItem("model", {
            title: "Model call",
            sub: `step ${step}${model && model.tool_calls ? ` · requested ${plural(model.tool_calls, "tool")}` : ""}`,
            meta: model ? [model.latency_ms ? fmtMs(model.latency_ms) : "", model.tokens ? `${fmtNum(model.tokens)} tok` : ""].filter(Boolean).join(" · ") : pending ? "running" : "",
            status: pending && !tools.length ? "running" : undefined,
            children: thought ? h("div", { class: "tl-text" }, oneLine(thought, 400)) : null,
          }),
        );
        for (const t of tools) {
          const key = t.id || `${step}-${t.name}`;
          const open = openDetails.has(key);
          const more = h("button", { class: "tl-more", type: "button", "aria-expanded": String(open) }, open ? "Hide details" : "Details");
          const detail = open
            ? h(
                "div",
                { class: "tl-detail" },
                h("div", null, h("div", { class: "io-label" }, "Arguments"), argsList(t.arguments)),
                t.status && t.status !== "running" ? h("div", null, h("div", { class: "io-label" }, t.status === "error" ? "Error" : "Result"), resultBox(t.status === "error" ? t.error || t.output : t.output)) : null,
              )
            : null;
          more.addEventListener("click", () => {
            if (openDetails.has(key)) openDetails.delete(key);
            else openDetails.add(key);
            paintTimeline();
          });
          const result = t.status === "running" ? "running…" : t.status === "error" ? `error: ${oneLine(t.error || t.output, 80)}` : `→ ${oneLine(t.output, 80)}`;
          list.appendChild(
            tlItem("tool", {
              title: t.name,
              mono: true,
              sub: compactArgs(t.arguments),
              meta: t.latency_ms !== undefined && t.latency_ms !== null ? fmtMs(t.latency_ms) : "",
              status: t.status === "error" ? "error" : t.status === "running" ? "running" : undefined,
              children: h("div", { class: "tl-text", style: { display: "flex", gap: "8px", alignItems: "baseline" } }, h("span", { class: "mono", style: { fontSize: "var(--text-xs)", color: t.status === "error" ? "var(--err)" : "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 } }, result), more),
            }),
          );
          if (detail) list.lastChild.appendChild(detail);
        }
      }
      if (info.status !== "running") {
        const label = info.status === "ok" ? "Final answer" : info.status === "stopped" ? "Stopped" : info.status === "error" ? "Failed" : `Ended: ${info.status}`;
        list.appendChild(tlItem("final", { title: label, sub: info.status === "ok" ? oneLine(info.content || answerText(), 90) : info.error || "", meta: info.duration_ms ? fmtMs(info.duration_ms) : "", status: info.status === "ok" ? undefined : "error" }));
      }
      rsBody.appendChild(list);
      if (info.trace_id) rsBody.appendChild(h("div", { class: "rs-foot" }, h("a", { href: `#/traces/${info.trace_id}` }, "Open the full trace")));
    }

    function refresh() {
      summaryLine();
      paintTimeline();
    }

    const handle = {
      el,
      context(ctx) {
        info.context = ctx;
        refresh();
      },
      step(n) {
        info.steps = Math.max(info.steps, n);
        refresh();
      },
      text(step, chunk) {
        const last = parts[parts.length - 1];
        if (last && last.type === "text" && last.step === step) last.content += chunk;
        else parts.push({ type: "text", step, content: chunk });
        if (!raf) raf = requestAnimationFrame(paintText);
      },
      model(data) {
        parts.push({ type: "model", step: data.step, latency_ms: data.latency_ms, tokens: data.usage ? data.usage.total_tokens : 0, tool_calls: (data.tool_calls || []).length });
        refresh();
      },
      tool(part) {
        parts.push({ type: "tool", ...part });
        paintText();
        refresh();
      },
      toolEnd(data) {
        const p = parts.find((x) => x.type === "tool" && x.id === data.id);
        if (p) Object.assign(p, { status: data.success ? "ok" : "error", output: data.output, error: data.error, latency_ms: data.latency_ms });
        refresh();
      },
      note(text, err = false) {
        notes.appendChild(h("div", { class: `msg-note${err ? " msg-note--err" : ""}` }, text));
      },
      finish(t) {
        if (raf) cancelAnimationFrame(raf);
        clearInterval(timer);
        Object.assign(info, t);
        if (info.status === "running") info.status = "error";
        if (!info.duration_ms) info.duration_ms = performance.now() - info.started;
        paintText();
        refresh();
        clear(meta).appendChild(metaRow(info));
      },
    };
    if (info.status === "running") {
      timer = setInterval(summaryLine, 100);
    }
    for (const p of turn.parts || []) if (p.type === "note") handle.note(p.content);
    if (turn.error) handle.note(turn.error, true);
    paintText();
    summaryLine();
    if (info.status !== "running") clear(meta).appendChild(metaRow(info));
    return handle;
  }

  // --- sending --------------------------------------------------------------------------------------
  function setRunning(on) {
    sendBtn.innerHTML = on ? `${icon("stop")}<span>Stop</span>` : `${icon("send")}<span>Send</span>`;
    sendBtn.classList.toggle("btn--primary", !on);
    sendBtn.classList.toggle("btn--danger", on);
    sendBtn.type = on ? "button" : "submit";
    sendBtn.setAttribute("aria-label", on ? "Stop the running turn" : "Send message");
    newBtn.disabled = on;
  }

  async function stop() {
    const run = state.running;
    if (!run) return;
    sendBtn.disabled = true;
    try {
      if (run.sessionId) await api.post(`/api/sessions/${encodeURIComponent(run.sessionId)}/stop`);
    } catch {
      /* fall through to abort */
    }
    setTimeout(() => {
      if (state.running === run) run.controller.abort();
    }, 2500);
  }

  async function send() {
    const text = input.value.trim();
    if (!text || state.running) return;
    input.value = "";
    autosize();
    if (!state.session || !state.session.messages || !state.session.messages.length) clear(threadInner);
    threadInner.appendChild(userMsg(text));
    const msg = assistantMsg({ status: "running", parts: [] });
    threadInner.appendChild(msg.el);
    thread.scrollTop = thread.scrollHeight;
    const controller = new AbortController();
    state.running = { controller, sessionId: state.sessionId };
    setRunning(true);
    const turn = { status: "running", model: state.settings.model };
    const tools = enabledTools();
    const body = {
      message: text,
      session_id: state.sessionId,
      model: state.settings.model || null,
      tools: state.tools.length ? tools : null,
      system_prompt: state.settings.system_prompt || null,
      max_steps: state.settings.max_steps,
    };
    const stick = () => {
      if (thread.scrollHeight - thread.scrollTop - thread.clientHeight < 160) thread.scrollTop = thread.scrollHeight;
    };
    let finished = false;
    try {
      await streamSSE("/api/chat", body, {
        signal: controller.signal,
        onEvent(name, data) {
          switch (name) {
            case "session":
              state.sessionId = data.session_id;
              state.running.sessionId = data.session_id;
              turn.model = data.model;
              titleEl.textContent = data.title;
              setHash(data.session_id);
              msg.context(data.context);
              loadSessions();
              break;
            case "run_start":
              turn.trace_id = data.trace_id;
              break;
            case "step_start":
              msg.step(data.step);
              break;
            case "token":
              msg.text(data.step, data.content);
              break;
            case "model_response":
              msg.model(data);
              break;
            case "tool_start":
              msg.tool({ ...data, status: "running" });
              break;
            case "tool_end":
              msg.toolEnd(data);
              break;
            case "reflection":
              msg.note(data.content);
              break;
            case "done":
              Object.assign(turn, data, { status: data.stop_reason === "final" ? "ok" : data.stop_reason, content: data.output });
              if (data.stop_reason !== "final") msg.note(data.output);
              finished = true;
              break;
            case "stopped":
              turn.status = "stopped";
              finished = true;
              break;
            case "error":
              turn.status = "error";
              turn.error = data.message;
              msg.note(data.message, true);
              finished = true;
              break;
            default:
              break;
          }
          stick();
        },
      });
    } catch (err) {
      if (err.name === "AbortError") {
        turn.status = "stopped";
      } else {
        turn.status = "error";
        turn.error = err.message;
        msg.note(err.message, true);
      }
      finished = true;
    } finally {
      if (!finished) {
        turn.status = "error";
        msg.note("The stream ended unexpectedly.", true);
      }
      msg.finish(turn);
      state.running = null;
      sendBtn.disabled = false;
      setRunning(false);
      stick();
      if (state.sessionId) {
        try {
          state.session = await api.get(`/api/sessions/${encodeURIComponent(state.sessionId)}`);
        } catch {
          /* keep the streamed view */
        }
      }
      loadSessions();
      input.focus();
    }
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      send();
    } else if (ev.key === "Escape") {
      input.blur();
    }
  });
  composer.addEventListener("submit", (ev) => {
    ev.preventDefault();
    send();
  });
  sendBtn.addEventListener("click", (ev) => {
    if (state.running) {
      ev.preventDefault();
      stop();
    }
  });
  newBtn.addEventListener("click", newChat);

  // --- boot -------------------------------------------------------------------------------------------
  buildSettings();
  paintSummary();
  await loadSessions();
  if (state.sessionId) await openSession(state.sessionId);
  else paintThread();
  input.focus();

  return () => {
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("agentcore:new-chat", onNewChat);
    if (state.running) state.running.controller.abort();
    for (const [id, timer] of state.pendingDeletes) {
      clearTimeout(timer);
      api.del(`/api/sessions/${encodeURIComponent(id)}`).catch(() => {});
    }
  };
}
