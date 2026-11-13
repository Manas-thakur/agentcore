// Number, time and text formatting shared by every view.

const nf = new Intl.NumberFormat();

export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return nf.format(n);
}

export function fmtCompact(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  if (Math.abs(n) < 1000) return nf.format(Math.round(n * 100) / 100);
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "-";
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

export function fmtCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined || Number.isNaN(usd)) return "-";
  if (usd === 0) return "$0";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `${(v * 100).toFixed(digits)}%`;
}

export function plural(n: number, word: string, pluralWord?: string): string {
  return `${fmtNum(n)} ${n === 1 ? word : pluralWord || `${word}s`}`;
}

/** Epoch seconds -> local date + time. */
export function fmtTime(t: number | null | undefined): string {
  if (!t) return "-";
  return new Date(t * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Epoch seconds -> "5s ago", "3m ago", "2h ago", "4d ago" or a date. */
export function fmtAgo(t: number | null | undefined, now = Date.now() / 1000): string {
  if (!t) return "-";
  const d = Math.max(0, now - t);
  if (d < 45) return `${Math.max(1, Math.round(d))}s ago`;
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  if (d < 86400) return `${Math.round(d / 3600)}h ago`;
  if (d < 86400 * 14) return `${Math.round(d / 86400)}d ago`;
  return new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function isoToEpoch(iso: string | null | undefined): number | null {
  const t = Date.parse(iso || "");
  return Number.isNaN(t) ? null : t / 1000;
}

export function isoAgo(iso: string | null | undefined): string {
  return fmtAgo(isoToEpoch(iso));
}

/** Short label for an ISO timestamp: time today, otherwise "Nov 3". */
export function shortWhen(iso: string | null | undefined): string {
  const t = isoToEpoch(iso);
  if (t === null) return "-";
  const d = new Date(t * 1000);
  return d.toDateString() === new Date().toDateString()
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function pctChange(cur: number | null | undefined, before: number | null | undefined): number | null {
  if (cur === null || cur === undefined || before === null || before === undefined) return null;
  if (before === 0) return cur === 0 ? 0 : null;
  return (cur - before) / Math.abs(before);
}

export function oneLine(s: unknown, n = 120): string {
  const t = String(s ?? "")
    .replace(/\s+/g, " ")
    .trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

export function compactArgs(args: Record<string, unknown> | undefined | null): string {
  const entries = Object.entries(args || {});
  if (!entries.length) return "()";
  return entries.map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ");
}

/** Parse a string that looks like JSON; return the input otherwise. */
export function parseMaybeJson(v: unknown): unknown {
  if (typeof v !== "string") return v;
  const t = v.trim();
  if (!t || !/^[[{]/.test(t)) return v;
  try {
    return JSON.parse(t);
  } catch {
    return v;
  }
}

export function pretty(v: unknown): string {
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const modKey = isMac ? "⌘" : "Ctrl";
