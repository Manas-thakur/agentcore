// Side peek: a resizable panel that opens beside a list (not a page change). Below 768px it
// becomes a full-screen sheet. Width is remembered per view.

import { h, icon, store } from "./ui.js";

const MIN = 360;

export function createPeek({ id, label, onClose, defaultWidth = 620 }) {
  const key = `peek.${id}.width`;
  let width = store.get(key, defaultWidth);
  const titleEl = h("div", { class: "peek-title" });
  const actions = h("div", { class: "peek-actions" });
  const closeBtn = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "Close panel (Esc)", title: "Close (Esc)", html: icon("x") });
  const body = h("div", { class: "peek-body" });
  const handle = h("div", {
    class: "peek-handle",
    role: "separator",
    tabindex: 0,
    "aria-orientation": "vertical",
    "aria-label": "Resize panel",
    "aria-valuemin": MIN,
  });
  const el = h(
    "aside",
    { class: "peek", "aria-label": label, hidden: true, tabindex: -1 },
    handle,
    h("header", { class: "peek-head" }, titleEl, actions, closeBtn),
    body,
  );

  const maxWidth = () => Math.max(MIN, Math.floor(window.innerWidth * 0.75));
  function apply() {
    width = Math.min(Math.max(width, MIN), maxWidth());
    el.style.setProperty("--peek-w", `${width}px`);
    handle.setAttribute("aria-valuenow", String(width));
    handle.setAttribute("aria-valuemax", String(maxWidth()));
  }
  apply();

  handle.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    handle.setPointerCapture(ev.pointerId);
    const startX = ev.clientX;
    const startW = width;
    el.classList.add("is-resizing");
    const move = (e) => {
      width = startW + (startX - e.clientX);
      apply();
    };
    const up = () => {
      el.classList.remove("is-resizing");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      store.set(key, width);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  });
  handle.addEventListener("keydown", (ev) => {
    const step = ev.shiftKey ? 80 : 24;
    if (ev.key === "ArrowLeft") width += step;
    else if (ev.key === "ArrowRight") width -= step;
    else return;
    ev.preventDefault();
    apply();
    store.set(key, width);
  });
  closeBtn.addEventListener("click", () => close());
  const onResize = () => apply();
  window.addEventListener("resize", onResize);

  let lastFocus = null;
  function open() {
    if (!el.hidden) return;
    lastFocus = document.activeElement;
    el.hidden = false;
    document.body.classList.add("peek-open");
  }
  function close({ silent = false } = {}) {
    if (el.hidden) return;
    el.hidden = true;
    document.body.classList.remove("peek-open");
    if (!silent && onClose) onClose();
    if (lastFocus && lastFocus.isConnected) lastFocus.focus({ preventScroll: true });
  }
  return {
    el,
    body,
    titleEl,
    actions,
    open,
    close,
    get isOpen() {
      return !el.hidden;
    },
    dispose() {
      window.removeEventListener("resize", onResize);
      document.body.classList.remove("peek-open");
    },
  };
}

// Accessible tabs (roving tabindex, arrow keys). Returns { el, select(i) }.
export function tabs(defs, { initial = 0, onChange, label = "Sections" } = {}) {
  const list = h("div", { class: "tabs", role: "tablist", "aria-label": label });
  const panel = h("div", { class: "tab-panel", role: "tabpanel", tabindex: 0 });
  const uid = Math.random().toString(36).slice(2, 8);
  const buttons = defs.map((d, i) =>
    h(
      "button",
      {
        class: "tab",
        type: "button",
        role: "tab",
        id: `tab-${uid}-${i}`,
        "aria-controls": `tabp-${uid}`,
        onclick: () => select(i),
      },
      d.label,
      d.badge !== undefined && d.badge !== null ? h("span", { class: "tab-badge" }, String(d.badge)) : null,
    ),
  );
  panel.id = `tabp-${uid}`;
  list.append(...buttons);
  list.addEventListener("keydown", (ev) => {
    const cur = buttons.indexOf(document.activeElement);
    if (cur < 0) return;
    let next = cur;
    if (ev.key === "ArrowRight") next = (cur + 1) % buttons.length;
    else if (ev.key === "ArrowLeft") next = (cur - 1 + buttons.length) % buttons.length;
    else if (ev.key === "Home") next = 0;
    else if (ev.key === "End") next = buttons.length - 1;
    else return;
    ev.preventDefault();
    select(next);
    buttons[next].focus();
  });
  let current = -1;
  function select(i) {
    current = i;
    buttons.forEach((b, j) => {
      b.setAttribute("aria-selected", j === i ? "true" : "false");
      b.tabIndex = j === i ? 0 : -1;
    });
    panel.setAttribute("aria-labelledby", buttons[i].id);
    panel.replaceChildren();
    const content = defs[i].render();
    if (content) panel.append(content);
    if (onChange) onChange(i);
  }
  select(initial);
  return {
    el: h("div", { class: "tabs-wrap" }, list, panel),
    select,
    get current() {
      return current;
    },
  };
}
