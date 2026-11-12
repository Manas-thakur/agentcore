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
