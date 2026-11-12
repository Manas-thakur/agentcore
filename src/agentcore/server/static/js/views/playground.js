// Playground: multi-turn chat with streaming (SSE), server-side sessions, inline tool cards.

import { api, streamSSE } from "../api.js";
import { renderMarkdown } from "../md.js";
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
  jsonPre,
  loading,
  store,
  toast,
} from "../ui.js";

const EXAMPLES = ["What is 17 * 23 + 4?", "Compute (12 + 8) * 3 - 5.", "What is 2 ** 16 / 4?"];
const DEFAULTS = { model: "", tools: null, system_prompt: "", max_steps: 8 };

export async function render(root, { segments }) {
  const state = {
    settings: { ...DEFAULTS, ...store.get("pg.settings", {}) },
    sessions: [],
    sessionId: segments[0] || null,
    session: null,
    tools: [],
    running: null, // { controller, sessionId }
    pendingDeletes: new Map(),
  };

  const sessionList = h("ul", { class: "session-list", "aria-label": "Chats" });
  const titleEl = h("h1", null, "New chat");
  const thread = h("div", { class: "thread", "aria-live": "polite" });
  const threadInner = h("div", { class: "thread-inner" });
  thread.appendChild(threadInner);
  const input = h("textarea", {
    rows: 1,
    placeholder: "Message the agent...",
    "aria-label": "Message",
    maxlength: 100000,
  });
  const sendBtn = h("button", { class: "btn btn--primary", type: "submit", html: `${icon("send")}<span>Send</span>` });
  const composer = h(
    "form",
    { class: "composer" },
    h("div", { class: "composer-inner" }, input, sendBtn),
    h(
      "div",
      { class: "composer-hint" },
      h("span", { html: "<kbd>Enter</kbd> send · <kbd>Shift</kbd>+<kbd>Enter</kbd> new line" }),
      h("span", { class: "settings-summary" }),
    ),
  );
  const settingsSummary = composer.querySelector(".settings-summary");

  const settingsPanel = h("aside", { class: "pg-settings", "aria-label": "Run settings" });
  const sessionsBtn = h("button", { class: "icon-btn only-narrow", type: "button", "aria-label": "Show chats", html: icon("sidebar") });
  const settingsBtn = h("button", {
    class: "btn btn--ghost only-narrow settings-btn",
    type: "button",
    "aria-label": "Run settings",
    html: `${icon("sliders")}<span>Settings</span>`,
  });
  const newBtn = h("button", { class: "btn btn--sm", type: "button", html: `${icon("plus")}<span>New</span>` });

  const pg = h(
    "div",
    { class: "pg" },
    h(
      "aside",
      { class: "pg-sessions", "aria-label": "Chat history" },
      h("div", { class: "pg-sessions-head" }, h("h2", null, "Chats"), newBtn),
      sessionList,
    ),
    h("section", { class: "pg-main" }, h("div", { class: "pg-bar" }, sessionsBtn, titleEl, settingsBtn), thread, composer),
    settingsPanel,
  );
  root.appendChild(h("div", { class: "page page--full" }, pg));

  // --- drawers (narrow screens) ---------------------------------------------------------
  const closeDrawers = () => pg.classList.remove("sessions-open", "settings-open");
  sessionsBtn.addEventListener("click", () => pg.classList.toggle("sessions-open"));
  settingsBtn.addEventListener("click", () => pg.classList.toggle("settings-open"));
  const onKey = (ev) => {
    if (ev.key === "Escape") closeDrawers();
  };
  document.addEventListener("keydown", onKey);
  thread.addEventListener("click", closeDrawers);

  // --- settings panel ---------------------------------------------------------------------
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
    settingsSummary.textContent = `${state.settings.model || "server default"} · ${tools.length} tool${tools.length === 1 ? "" : "s"} · ${state.settings.max_steps} steps max`;
  }

  async function buildSettings() {
    clear(settingsPanel);
    settingsPanel.appendChild(h("h2", null, "Run settings"));
    const modelInput = h("input", {
      class: "input mono",
      list: "pg-models",
      value: state.settings.model,
      placeholder: "server default",
      spellcheck: "false",
      autocomplete: "off",
      id: "pg-model",
    });
    const datalist = h("datalist", { id: "pg-models" });
    modelInput.addEventListener("change", () => {
      state.settings.model = modelInput.value.trim();
      saveSettings();
    });
    settingsPanel.appendChild(
      h(
        "div",
        { class: "field" },
        h("label", { class: "label", for: "pg-model" }, "Model"),
        modelInput,
        datalist,
        h("span", { class: "hint" }, "Pick one or type any spec: mock, ollama:<model>, openai:<model>."),
      ),
    );
    const toolBox = h("div", { class: "tool-toggles" }, loading("Loading tools..."));
    settingsPanel.appendChild(h("div", { class: "field" }, h("span", { class: "label" }, "Tools"), toolBox));
    const sys = h("textarea", {
      class: "textarea",
      rows: 6,
      id: "pg-system",
      placeholder: "Default system prompt",
    });
    sys.value = state.settings.system_prompt;
    sys.addEventListener("change", () => {
      state.settings.system_prompt = sys.value;
      saveSettings();
    });
    settingsPanel.appendChild(h("div", { class: "field" }, h("label", { class: "label", for: "pg-system" }, "System prompt"), sys));
    const steps = h("input", { class: "input", type: "number", min: 1, max: 50, value: state.settings.max_steps, id: "pg-steps" });
    steps.addEventListener("change", () => {
      const v = Math.min(50, Math.max(1, parseInt(steps.value, 10) || 8));
      steps.value = v;
      state.settings.max_steps = v;
      saveSettings();
    });
    settingsPanel.appendChild(
      h("div", { class: "field" }, h("label", { class: "label", for: "pg-steps" }, "Max steps"), steps, h("span", { class: "hint" }, "Upper bound on model calls per turn.")),
    );
    settingsPanel.appendChild(
      h(
        "div",
        { class: "field" },
        h("button", {
          class: "btn btn--ghost btn--sm",
          type: "button",
          onclick: () => {
            state.settings = { ...DEFAULTS };
            saveSettings();
            buildSettings();
          },
        }, "Reset to defaults"),
      ),
    );

    api.get("/v1/models").then(
      (res) => {
        for (const m of res.data) datalist.appendChild(h("option", { value: m.id }, m.default ? "server default" : ""));
        if (!modelInput.placeholder || modelInput.placeholder === "server default") {
          const def = res.data.find((m) => m.default);
          if (def) modelInput.placeholder = `${def.id} (default)`;
        }
      },
      () => {},
    );
    try {
      state.tools = await api.get("/api/tools");
      clear(toolBox);
      if (!state.tools.length) toolBox.appendChild(h("p", { class: "hint" }, "No tools are enabled on this server."));
      const on = new Set(enabledTools());
      for (const t of state.tools) {
        const cb = h("input", { type: "checkbox", checked: on.has(t.name) });
        cb.addEventListener("change", () => {
          const current = new Set(enabledTools());
          if (cb.checked) current.add(t.name);
          else current.delete(t.name);
          state.settings.tools = state.tools.map((x) => x.name).filter((n) => current.has(n));
          saveSettings();
        });
        toolBox.appendChild(h("label", { class: "check", title: t.description }, cb, h("span", null, h("span", { class: "mono" }, t.name), h("span", { class: "hint" }, ` ${t.category}`))));
      }
      paintSummary();
    } catch (err) {
      clear(toolBox).appendChild(h("p", { class: "field-error" }, `Could not load tools: ${err.message}`));
    }
  }

  // --- sessions -------------------------------------------------------------------------
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
      sessionList.appendChild(h("li", null, h("p", { class: "hint", style: { padding: "8px" } }, "No chats yet. Your conversations are saved on the server.")));
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
            closeDrawers();
            if (s.id !== state.sessionId) openSession(s.id);
          },
        },
        h("span", { class: "session-title" }, s.title || "New chat"),
        h("span", { class: "session-meta" }, `${s.turns} msg · ${fmtAgo(s.updated)}`),
      );
      const del = h("button", {
        class: "icon-btn session-del",
        type: "button",
        "aria-label": `Delete chat "${s.title}"`,
        html: icon("trash"),
        onclick: () => deleteSession(s),
      });
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
    if (state.running) return;
    state.sessionId = null;
    state.session = null;
    titleEl.textContent = "New chat";
    setHash(null);
    paintSessions();
    paintThread();
    closeDrawers();
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

  // --- thread rendering -----------------------------------------------------------------
  function mockNotice() {
    // The offline mock model answers arithmetic and simple tool tasks only. Say so
    // up front so first-time users don't mistake its canned replies for a bug.
    const slot = h("div");
    if (state.settings.model && !/^mock\b/.test(state.settings.model)) return slot;
    if (store.get("pg.mockNoticeDismissed", false)) return slot;
    api
      .get("/api/config")
      .then((cfg) => {
        if (!/^mock\b/.test(String(cfg.default_model || ""))) return;
        const close = h("button", { class: "btn btn--ghost btn--sm", type: "button", "aria-label": "Dismiss" }, "Got it");
        close.addEventListener("click", () => {
          store.set("pg.mockNoticeDismissed", true);
          slot.remove();
        });
        slot.appendChild(
          h(
            "div",
            { class: "banner mock-notice", role: "note" },
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
              ". You can also pick a model under Settings in this chat.",
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
      h("p", null, "Answers stream in as they are generated. Tool calls appear inline with their arguments, results and timings, and every answer links to its trace."),
      mockNotice(),
      h(
        "div",
        { class: "examples" },
        EXAMPLES.map((q) =>
          h("button", { class: "example", type: "button", onclick: () => { input.value = q; send(); } }, q),
        ),
      ),
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

  function toolCard(part) {
    const status = part.status || "running";
    const args = part.arguments || {};
    const argsText = JSON.stringify(args);
    const details = h("details", { class: "toolcard", "data-status": status });
    const chipEl = h("span", { class: "chip" });
    const dur = h("span", { class: "tdur" });
    const body = h("div", { class: "toolcard-body" });
    details.append(
      h("summary", null, h("span", { html: icon("chevron", "chev") }), h("span", { class: "tname" }, part.name), h("span", { class: "targs" }, argsText), chipEl, dur),
      body,
    );
    const update = (p) => {
      const st = p.status || "running";
      details.dataset.status = st;
      chipEl.className = `chip${st === "ok" ? " chip--ok" : st === "error" ? " chip--err" : ""}`;
      clear(chipEl);
      if (st === "running") chipEl.append(h("span", { class: "spinner", "aria-hidden": "true" }), "running");
      else chipEl.append(st === "ok" ? "ok" : "error");
      dur.textContent = p.latency_ms !== undefined && p.latency_ms !== null ? fmtMs(p.latency_ms) : "";
      clear(body);
      body.append(h("div", null, h("span", { class: "label" }, "Arguments"), jsonPre(p.arguments || args)));
      if (st !== "running") {
        let out = p.output ?? "";
        try {
          out = JSON.parse(out);
        } catch {
          /* plain text */
        }
        body.append(h("div", null, h("span", { class: "label" }, st === "error" ? "Error" : "Result"), jsonPre(st === "error" ? (p.error || out) : out, { wrap: true })));
      }
      if (st === "error") details.open = true;
    };
    update(part);
    return { el: details, update };
  }

  function metaRow(t) {
    const items = [];
    if (t.model) items.push(h("span", null, t.model));
    if (t.steps) items.push(h("span", null, `${t.steps} step${t.steps === 1 ? "" : "s"}`));
    if (t.usage) items.push(h("span", null, `${fmtNum(t.usage.total_tokens)} tok`));
    if (t.duration_ms) items.push(h("span", null, fmtMs(t.duration_ms)));
    if (t.cost_usd) items.push(h("span", null, fmtCost(t.cost_usd)));
    if (t.status && t.status !== "ok") items.push(h("span", { class: t.status === "error" ? "chip chip--err" : "chip chip--warn" }, t.status));
    if (t.trace_id) items.push(h("a", { href: `#/traces/${t.trace_id}` }, "View trace"));
    if (t.content) {
      items.push(h("button", { class: "btn btn--ghost btn--sm", type: "button", "aria-label": "Copy answer", html: icon("copy"), onclick: () => copyText(t.content) }));
    }
    return h("div", { class: "msg-meta" }, items);
  }

  // Builds an assistant message; returns handles so streaming can update it in place.
  function assistantMsg(turn) {
    const body = h("div", { class: "msg-body" });
    const meta = h("div");
    const el = h("div", { class: "msg msg--assistant" }, h("div", { class: "msg-who" }, "Agent"), body, meta);
    const cards = new Map();
    let textEl = null;
    let textStep = null;
    let textBuf = "";
    let raf = 0;
    const flush = () => {
      raf = 0;
      if (textEl) textEl.innerHTML = renderMarkdown(textBuf);
    };
    const api_ = {
      el,
      text(step, chunk) {
        if (!textEl || textStep !== step) {
          textEl = h("div", { class: "md msg-text cursor" });
          textStep = step;
          textBuf = "";
          body.appendChild(textEl);
        }
        textBuf += chunk;
        if (!raf) raf = requestAnimationFrame(flush);
      },
      endText() {
        if (raf) cancelAnimationFrame(raf);
        flush();
        if (textEl) textEl.classList.remove("cursor");
      },
      tool(part) {
        this.endText();
        textEl = null;
        const card = toolCard(part);
        cards.set(part.id, card);
        body.appendChild(card.el);
      },
      toolEnd(data) {
        const card = cards.get(data.id);
        if (card) card.update({ ...data, status: data.success ? "ok" : "error" });
      },
      note(text, err = false) {
        this.endText();
        textEl = null;
        body.appendChild(h("div", { class: `msg-note${err ? " msg-note--err" : ""}` }, text));
      },
      finish(t) {
        this.endText();
        clear(meta).appendChild(metaRow(t));
        if (!body.childNodes.length && t.content) {
          body.appendChild(h("div", { class: "md msg-text", html: renderMarkdown(t.content) }));
        }
      },
    };
    for (const p of turn.parts || []) {
      if (p.type === "text") {
        api_.text(p.step ?? "s", p.content);
        api_.endText();
      } else if (p.type === "tool") {
        api_.tool(p);
        cards.get(p.id).update(p);
      } else if (p.type === "note") api_.note(p.content);
    }
    if (turn.error) api_.note(turn.error, true);
    if (turn.status !== "running") api_.finish(turn);
    return api_;
  }

  // --- sending --------------------------------------------------------------------------
  function setRunning(on) {
    input.disabled = false;
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
    const waiting = h("div", { class: "msg-note" }, h("span", { class: "spinner", style: { display: "inline-block", verticalAlign: "-2px", marginRight: "8px" } }), "Thinking...");
    msg.el.querySelector(".msg-body").appendChild(waiting);
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
          if (name !== "session" && waiting.isConnected) waiting.remove();
          switch (name) {
            case "session":
              state.sessionId = data.session_id;
              state.running.sessionId = data.session_id;
              turn.model = data.model;
              titleEl.textContent = data.title;
              setHash(data.session_id);
              loadSessions();
              break;
            case "run_start":
              turn.trace_id = data.trace_id;
              break;
            case "token":
              msg.text(data.step, data.content);
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
              msg.note("Stopped.");
              finished = true;
              break;
            case "error":
              turn.status = "error";
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
      if (waiting.isConnected) waiting.remove();
      if (err.name === "AbortError") {
        turn.status = "stopped";
        msg.note("Stopped.");
      } else {
        turn.status = "error";
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

  // --- boot -----------------------------------------------------------------------------
  buildSettings();
  paintSummary();
  await loadSessions();
  if (state.sessionId) await openSession(state.sessionId);
  else paintThread();
  input.focus();

  return () => {
    document.removeEventListener("keydown", onKey);
    if (state.running) state.running.controller.abort();
    for (const [id, timer] of state.pendingDeletes) {
      clearTimeout(timer);
      api.del(`/api/sessions/${encodeURIComponent(id)}`).catch(() => {});
    }
  };
}
