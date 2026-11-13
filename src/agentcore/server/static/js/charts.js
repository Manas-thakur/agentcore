// Inline-SVG charts sized to their container (re-rendered on resize). No dependencies.

const NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, text) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  if (text !== undefined) el.textContent = text;
  return el;
}

// Upper bound for 4 evenly spaced ticks with "nice" step sizes (1, 2, 2.5, 5 x 10^n).
function niceMax(v, integer = false) {
  if (!(v > 0)) return integer ? 4 : 1;
  const raw = v / 4;
  const exp = 10 ** Math.floor(Math.log10(raw));
  const f = raw / exp;
  let step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp;
  if (integer) step = Math.max(1, Math.ceil(step));
  return step * 4;
}

function tooltip(host) {
  let tip = host.querySelector(".chart-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "chart-tip";
    tip.hidden = true;
    host.appendChild(tip);
  }
  return {
    show(x, y, text) {
      tip.textContent = text;
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
      tip.hidden = false;
    },
    hide() {
      tip.hidden = true;
    },
  };
}

function observe(host, draw) {
  draw();
  if (host._ro) host._ro.disconnect();
  let w = host.clientWidth;
  host._ro = new ResizeObserver(() => {
    if (Math.abs(host.clientWidth - w) > 4) {
      w = host.clientWidth;
      draw();
    }
  });
  host._ro.observe(host);
}

function frame(host, height, maxY, fmtY, labels) {
  const width = Math.max(260, host.clientWidth);
  const pad = { l: 48, r: 8, t: 10, b: 24 };
  const root = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img" });
  const iw = width - pad.l - pad.r;
  const ih = height - pad.t - pad.b;
  const axis = svg("g", { class: "axis" });
  for (let k = 0; k <= 4; k++) {
    const y = pad.t + ih - (ih * k) / 4;
    root.appendChild(svg("line", { class: "gridline", x1: pad.l, x2: width - pad.r, y1: y, y2: y }));
    axis.appendChild(svg("text", { x: pad.l - 8, y: y + 3.5, "text-anchor": "end" }, fmtY((maxY * k) / 4)));
  }
  const n = labels.length;
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 70))));
  labels.forEach((lab, i) => {
    const last = i === n - 1;
    if (!last && (i % every !== 0 || n - 1 - i < every * 0.75)) return;
    const x = pad.l + (iw * (i + 0.5)) / n;
    axis.appendChild(svg("text", { x, y: height - 6, "text-anchor": "middle" }, lab));
  });
  root.appendChild(axis);
  return { root, pad, iw, ih, width };
}

// Stacked bars: series = [{key, cls}], rows = [{label, tip, values:{key:n}}]
export function barChart(host, { rows, series, height = 200, fmtY = (v) => String(Math.round(v)), title, integer = false }) {
  observe(host, () => {
    host.replaceChildren();
    const totals = rows.map((r) => series.reduce((s, sr) => s + (r.values[sr.key] || 0), 0));
    const maxY = niceMax(Math.max(0, ...totals), integer);
    const { root, pad, iw, ih } = frame(host, height, maxY, fmtY, rows.map((r) => r.label));
    if (title) root.setAttribute("aria-label", title);
    const tip = tooltip(host);
    const n = rows.length || 1;
    const bw = Math.max(2, Math.min(36, (iw / n) * 0.62));
    rows.forEach((r, i) => {
      let acc = 0;
      const x = pad.l + (iw * (i + 0.5)) / n - bw / 2;
      for (const sr of series) {
        const v = r.values[sr.key] || 0;
        if (!v) continue;
        const h = (ih * v) / maxY;
        const y = pad.t + ih - ((ih * acc) / maxY) - h;
        acc += v;
        const rect = svg("rect", { class: sr.cls, x, y, width: bw, height: Math.max(1, h), rx: 1.5 });
        rect.addEventListener("mouseenter", () => tip.show(x + bw / 2, y, r.tip));
        rect.addEventListener("mouseleave", () => tip.hide());
        rect.appendChild(svg("title", {}, r.tip));
        root.appendChild(rect);
      }
    });
    host.appendChild(root);
  });
}

// Lines: series = [{key, cls, ptCls, name}], rows = [{label, tip, values:{key:n}}]
export function lineChart(host, { rows, series, height = 200, fmtY = (v) => String(Math.round(v)), title }) {
  observe(host, () => {
    host.replaceChildren();
    const all = rows.flatMap((r) => series.map((s) => r.values[s.key] || 0));
    const maxY = niceMax(Math.max(0, ...all));
    const { root, pad, iw, ih } = frame(host, height, maxY, fmtY, rows.map((r) => r.label));
    if (title) root.setAttribute("aria-label", title);
    const tip = tooltip(host);
    const n = rows.length || 1;
    const px = (i) => pad.l + (iw * (i + 0.5)) / n;
    const py = (v) => pad.t + ih - (ih * v) / maxY;
    for (const s of series) {
      const pts = rows.map((r, i) => [px(i), py(r.values[s.key] || 0)]);
      if (pts.length > 1) {
        root.appendChild(svg("path", { class: `line ${s.cls}`, d: pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("") }));
      }
      rows.forEach((r, i) => {
        if (!r.values[s.key] && rows.length > 1) return;
        const c = svg("circle", { class: s.ptCls, cx: pts[i][0], cy: pts[i][1], r: 3 });
        c.addEventListener("mouseenter", () => tip.show(pts[i][0], pts[i][1], r.tip));
        c.addEventListener("mouseleave", () => tip.hide());
        c.appendChild(svg("title", {}, r.tip));
        root.appendChild(c);
      });
    }
    host.appendChild(root);
  });
}

// Tiny trend line for KPI cards. `values` are numbers (nulls are skipped).
export function sparkline(values, { width = 120, height = 32, cls = "spark", label } = {}) {
  const root = svg("svg", { class: cls, width, height, viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", role: "img", "aria-label": label || "trend" });
  const pts = values.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : 0));
  if (pts.length < 2) return root;
  const max = Math.max(...pts);
  const min = Math.min(0, ...pts);
  const span = max - min || 1;
  const x = (i) => (i / (pts.length - 1)) * (width - 2) + 1;
  const y = (v) => height - 2 - ((v - min) / span) * (height - 4);
  const d = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  root.appendChild(svg("path", { class: "spark-area", d: `${d}L${x(pts.length - 1).toFixed(1)},${height}L${x(0).toFixed(1)},${height}Z` }));
  root.appendChild(svg("path", { class: "spark-line", d }));
  root.appendChild(svg("circle", { class: "spark-dot", cx: x(pts.length - 1), cy: y(pts[pts.length - 1]), r: 2 }));
  return root;
}

// Trace volume histogram with drag-to-select (brush). `onSelect(t0, t1)` gets epoch seconds;
// a plain click selects one bucket. Errors stack on top of successes.
export function histogram(host, { buckets, start, end, selection, onSelect, fmtTip, height = 72 }) {
  observe(host, () => {
    host.replaceChildren();
    const width = Math.max(240, host.clientWidth);
    const pad = { l: 4, r: 4, t: 6, b: 16 };
    const iw = width - pad.l - pad.r;
    const ih = height - pad.t - pad.b;
    const n = buckets.length || 1;
    const maxY = Math.max(1, ...buckets.map((b) => b.count));
    const root = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}`, class: "histo", role: "img", "aria-label": `Trace volume over time, ${buckets.reduce((a, b) => a + b.count, 0)} traces` });
    const tip = tooltip(host);
    const bw = iw / n;
    const tToX = (t) => pad.l + ((t - start) / (end - start)) * iw;
    const xToT = (x) => start + ((Math.min(Math.max(x, pad.l), pad.l + iw) - pad.l) / iw) * (end - start);
    root.appendChild(svg("line", { class: "histo-base", x1: pad.l, x2: pad.l + iw, y1: pad.t + ih + 0.5, y2: pad.t + ih + 0.5 }));
    buckets.forEach((b, i) => {
      if (!b.count) return;
      const x = pad.l + i * bw + Math.min(1, bw * 0.15);
      const w = Math.max(1, bw - Math.min(2, bw * 0.3));
      const hOk = (ih * (b.count - b.errors)) / maxY;
      const hErr = (ih * b.errors) / maxY;
      if (hOk > 0) root.appendChild(svg("rect", { class: "histo-bar", x, y: pad.t + ih - hOk, width: w, height: Math.max(1, hOk), rx: 1 }));
      if (hErr > 0) root.appendChild(svg("rect", { class: "histo-err", x, y: pad.t + ih - hOk - hErr, width: w, height: Math.max(1, hErr), rx: 1 }));
    });
    // axis labels: start, middle, end
    const fmt = (t) => {
      const d = new Date(t * 1000);
      return end - start > 2 * 86400 ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    };
    const axis = svg("g", { class: "axis" });
    axis.appendChild(svg("text", { x: pad.l, y: height - 3, "text-anchor": "start" }, fmt(start)));
    axis.appendChild(svg("text", { x: pad.l + iw / 2, y: height - 3, "text-anchor": "middle" }, fmt((start + end) / 2)));
    axis.appendChild(svg("text", { x: pad.l + iw, y: height - 3, "text-anchor": "end" }, fmt(end)));
    root.appendChild(axis);
    const sel = svg("rect", { class: "histo-sel", y: pad.t, height: ih, x: 0, width: 0, visibility: "hidden" });
    root.appendChild(sel);
    const showSel = (a, b) => {
      const x0 = Math.min(a, b);
      sel.setAttribute("x", x0);
      sel.setAttribute("width", Math.max(2, Math.abs(b - a)));
      sel.setAttribute("visibility", "visible");
    };
    if (selection && (selection[0] || selection[1])) {
      showSel(tToX(selection[0] ?? start), tToX(selection[1] ?? end));
    }
    // brush
    let dragFrom = null;
    const local = (ev) => {
      const r = root.getBoundingClientRect();
      return ((ev.clientX - r.left) / r.width) * width;
    };
    root.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      dragFrom = local(ev);
      root.setPointerCapture(ev.pointerId);
      tip.hide();
    });
    root.addEventListener("pointermove", (ev) => {
      const x = local(ev);
      if (dragFrom !== null) {
        showSel(dragFrom, x);
        return;
      }
      const i = Math.floor((x - pad.l) / bw);
      const b = buckets[i];
      if (b && fmtTip) tip.show(pad.l + (i + 0.5) * bw, pad.t, fmtTip(b, bw));
      else tip.hide();
    });
    root.addEventListener("pointerleave", () => tip.hide());
    root.addEventListener("pointerup", (ev) => {
      if (dragFrom === null) return;
      const x = local(ev);
      let a = Math.min(dragFrom, x);
      let b = Math.max(dragFrom, x);
      dragFrom = null;
      if (b - a < 4) {
        const i = Math.max(0, Math.min(n - 1, Math.floor((a - pad.l) / bw)));
        a = pad.l + i * bw;
        b = a + bw;
      }
      if (onSelect) onSelect(xToT(a), xToT(b));
    });
    host.appendChild(root);
  });
}
