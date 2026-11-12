// Tools: list the server's enabled tools, show their JSON Schema, and invoke one directly.

import { api } from "../api.js";
import { chip, clear, emptyState, errorState, fmtMs, h, icon, jsonPre, loading } from "../ui.js";

export async function render(root, { segments }) {
  const page = h("div", { class: "page" });
  root.appendChild(page);
  page.appendChild(
    h(
      "div",
      { class: "page-head" },
      h("div", null, h("h1", null, "Tools"), h("p", { class: "lede" }, "Tools enabled on this server. Schemas are generated from type hints and docstrings; invoke one directly to check it before the agent does.")),
    ),
  );
  const list = h("nav", { class: "panel", "aria-label": "Tools", style: { padding: "var(--space-2)" } });
  const detail = h("div");
  page.appendChild(h("div", { class: "tools-layout" }, list, detail));
  list.appendChild(loading("Loading tools..."));

  let tools;
  try {
    tools = await api.get("/api/tools");
  } catch (err) {
    clear(list).appendChild(errorState(err));
    return;
  }
  clear(list);
  if (!tools.length) {
    clear(page.querySelector(".tools-layout")).appendChild(emptyState("No tools enabled", "Start the server with --tools calculator,current_time or list tools in agentcore.toml."));
    return;
  }
  for (const t of tools) {
    list.appendChild(
      h(
        "button",
        { class: "tool-item", type: "button", "data-name": t.name, onclick: () => select(t.name) },
        h("span", { class: "mono" }, t.name),
        h("span", { class: "d" }, t.description),
      ),
    );
  }

  function select(name) {
    const t = tools.find((x) => x.name === name) || tools[0];
    history.replaceState(null, "", `#/tools/${encodeURIComponent(t.name)}`);
    for (const b of list.querySelectorAll(".tool-item")) b.setAttribute("aria-current", b.dataset.name === t.name ? "true" : "false");
    paint(t);
  }

  function paint(t) {
    clear(detail);
    const props = (t.parameters && t.parameters.properties) || {};
    const required = new Set((t.parameters && t.parameters.required) || []);
    const controls = {};
    const form = h("form", { class: "panel-body", novalidate: true });
    const rawArea = h("textarea", { class: "textarea mono", rows: 8, spellcheck: "false", "aria-label": "Arguments as JSON" });
    let rawMode = false;
    const toggle = h("button", { class: "btn btn--ghost btn--sm", type: "button" }, "Edit as JSON");
    const errorEl = h("p", { class: "field-error", hidden: true, role: "alert" });
    const fieldsWrap = h("div");

    for (const [name, schema] of Object.entries(props)) {
      const id = `arg-${name}`;
      const type = Array.isArray(schema.type) ? schema.type.find((x) => x !== "null") : schema.type || (schema.anyOf ? (schema.anyOf.find((x) => x.type !== "null") || {}).type : undefined);
      let control;
      if (schema.enum) {
        control = h("select", { class: "select", id }, required.has(name) ? null : h("option", { value: "" }, "(not set)"), schema.enum.map((v) => h("option", { value: JSON.stringify(v) }, String(v))));
        if (schema.default !== undefined) control.value = JSON.stringify(schema.default);
        control._read = () => (control.value === "" ? undefined : JSON.parse(control.value));
      } else if (type === "boolean") {
        control = h("input", { type: "checkbox", id, checked: schema.default === true });
        control._read = () => control.checked;
      } else if (type === "integer" || type === "number") {
        control = h("input", { class: "input", type: "number", id, step: type === "integer" ? 1 : "any", value: schema.default ?? "" });
        control._read = () => (control.value === "" ? undefined : Number(control.value));
      } else if (type === "object" || type === "array") {
        control = h("textarea", { class: "textarea mono", id, rows: 3, spellcheck: "false", placeholder: type === "array" ? "[ ]" : "{ }" });
        if (schema.default !== undefined) control.value = JSON.stringify(schema.default);
        control._read = () => {
          if (!control.value.trim()) return undefined;
          try {
            return JSON.parse(control.value);
          } catch {
            throw new Error(`${name}: not valid JSON`);
          }
        };
      } else {
        const long = /code|text|content|body|query|expression/i.test(name);
        control = long ? h("textarea", { class: "textarea", id, rows: name === "code" ? 5 : 2, spellcheck: "false" }) : h("input", { class: "input", id, type: "text", spellcheck: "false" });
        if (schema.default !== undefined && schema.default !== null) control.value = String(schema.default);
        control._read = () => (control.value === "" ? undefined : control.value);
      }
      controls[name] = control;
      const labelText = h("label", { class: "label", for: id }, name, required.has(name) ? h("span", { class: "req", "aria-hidden": "true" }, "*") : null);
      fieldsWrap.appendChild(
        type === "boolean"
          ? h("div", { class: "field" }, h("label", { class: "check", for: id }, control, h("span", { class: "mono" }, name)), schema.description ? h("span", { class: "hint" }, schema.description) : null)
          : h("div", { class: "field" }, labelText, control, h("span", { class: "hint" }, [type, schema.description].filter(Boolean).join(" · "))),
      );
    }
    if (!Object.keys(props).length) fieldsWrap.appendChild(h("p", { class: "hint" }, "This tool takes no arguments."));

    function collect() {
      if (rawMode) {
        try {
          const v = JSON.parse(rawArea.value || "{}");
          if (typeof v !== "object" || Array.isArray(v) || v === null) throw new Error("arguments must be a JSON object");
          return v;
        } catch (err) {
          throw new Error(`Invalid JSON: ${err.message}`);
        }
      }
      const out = {};
      for (const [name, c] of Object.entries(controls)) {
        c.removeAttribute("aria-invalid");
        const v = c._read();
        if (v !== undefined) out[name] = v;
        else if (required.has(name)) {
          c.setAttribute("aria-invalid", "true");
          throw new Error(`${name} is required`);
        }
      }
      return out;
    }

    toggle.addEventListener("click", () => {
      try {
        if (!rawMode) rawArea.value = JSON.stringify(collect(), null, 2);
      } catch {
        rawArea.value = "{}";
      }
      rawMode = !rawMode;
      fieldsWrap.hidden = rawMode;
      rawArea.hidden = !rawMode;
      toggle.textContent = rawMode ? "Edit as form" : "Edit as JSON";
    });
    rawArea.hidden = true;

    const runBtn = h("button", { class: "btn btn--primary", type: "submit", html: `${icon("play")}<span>Invoke</span>` });
    const result = h("div", { class: "panel-body", "aria-live": "polite" }, h("p", { class: "hint", style: { margin: 0 } }, "Results appear here. Each invocation is traced like an agent tool call."));
    form.append(fieldsWrap, rawArea, errorEl, h("div", { style: { display: "flex", gap: "var(--space-2)", marginTop: "var(--space-4)", alignItems: "center" } }, runBtn, toggle));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      errorEl.hidden = true;
      let args;
      try {
        args = collect();
      } catch (err) {
        errorEl.textContent = err.message;
        errorEl.hidden = false;
        return;
      }
      runBtn.classList.add("is-busy");
      runBtn.disabled = true;
      clear(result).appendChild(loading("Running..."));
      try {
        const r = await api.post(`/api/tools/${encodeURIComponent(t.name)}/invoke`, { arguments: args });
        clear(result);
        let out = r.output;
        if (typeof out === "string") {
          try {
            out = JSON.parse(out);
          } catch {
            /* plain text */
          }
        }
        result.append(
          h("div", { class: "result-head" }, r.success ? chip("ok", "ok") : chip(r.error_type || "error", "err"), h("span", { class: "hint mono" }, `${fmtMs(r.latency_ms)} · ${r.attempts} attempt${r.attempts === 1 ? "" : "s"}`), r.trace_id ? h("a", { href: `#/traces/${r.trace_id}`, style: { marginLeft: "auto", fontSize: "var(--text-sm)" } }, "View trace") : null),
          jsonPre(r.success ? out : r.error, { wrap: true }),
        );
      } catch (err) {
        clear(result).appendChild(h("p", { class: "field-error" }, err.message));
      } finally {
        runBtn.classList.remove("is-busy");
        runBtn.disabled = false;
      }
    });

    detail.append(
      h(
        "div",
        { class: "panel", style: { marginBottom: "var(--space-4)" } },
        h("div", { class: "panel-head" }, h("h2", { class: "mono" }, t.name), h("div", { class: "actions" }, chip(t.category), chip(t.source, t.source === "custom" ? "accent" : ""), t.timeout ? chip(`timeout ${t.timeout}s`) : null)),
        h("div", { class: "panel-body" }, h("p", { style: { margin: 0, color: "var(--color-ink)" } }, t.description || "No description.")),
      ),
      h(
        "div",
        { class: "tool-grid" },
        h("div", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", null, "Try it")), form, h("div", { style: { borderTop: "1px solid var(--color-rule)" } }, result)),
        h("div", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", null, "JSON Schema")), h("div", { class: "panel-body" }, jsonPre(t.parameters, { wrap: true }))),
      ),
    );
  }

  select(segments[0] || tools[0].name);
}
