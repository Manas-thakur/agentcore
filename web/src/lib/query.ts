// Client mirror of the trace query tokenizer (server/query.py is the source of truth). Used to
// toggle facet values and quick filters in the query string, render pills and drive autocomplete.

export interface FieldDef {
  name: string;
  kind: "text" | "num";
  hint: string;
  values?: string[];
}

export const FIELDS: FieldDef[] = [
  { name: "status", kind: "text", hint: "ok or error", values: ["ok", "error"] },
  { name: "model", kind: "text", hint: "model id, * wildcard" },
  { name: "tool", kind: "text", hint: "a tool the run called" },
  { name: "name", kind: "text", hint: "root span name" },
  {
    name: "kind",
    kind: "text",
    hint: "chat, api, openai, eval, tool",
    values: ["chat", "api", "openai", "eval", "tool", "other"],
  },
  { name: "session", kind: "text", hint: "chat session id" },
  { name: "id", kind: "text", hint: "trace id prefix" },
  { name: "latency", kind: "num", hint: ">2s, <=500ms", values: [">1s", ">500ms", "<100ms"] },
  { name: "tokens", kind: "num", hint: ">500", values: [">500", ">1000"] },
  { name: "cost", kind: "num", hint: ">0.01 (USD)", values: [">0.01", ">0"] },
  { name: "steps", kind: "num", hint: "model steps" },
  { name: "tools", kind: "num", hint: "number of tool calls" },
];

export const ALIASES: Record<string, string> = {
  duration: "latency",
  lat: "latency",
  level: "status",
  trace: "id",
  trace_id: "id",
  session_id: "session",
  token: "tokens",
  usd: "cost",
  type: "kind",
};

export interface Token {
  raw: string;
  neg: boolean;
  key: string | null;
  value: string;
  start: number;
  end: number;
}

const TOKEN_RE = /(-?)(?:([A-Za-z_][\w.]*):)?("(?:[^"\\]|\\.)*"?|\S+)/g;
const NUM_RE = /^(-?\d+(?:\.\d+)?|-?\.\d+)\s*([a-z]*)$/i;

export function tokenize(q: string): Token[] {
  const out: Token[] = [];
  const re = new RegExp(TOKEN_RE.source, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(q))) {
    if (!m[0]) {
      re.lastIndex++;
      continue;
    }
    out.push({
      raw: m[0],
      neg: m[1] === "-",
      key: m[2] ? m[2].toLowerCase() : null,
      value: m[3],
      start: m.index,
      end: m.index + m[0].length,
    });
  }
  return out;
}

export function quote(v: string): string {
  return /[\s",]/.test(v) ? `"${v.replace(/(["\\])/g, "\\$1")}"` : v;
}

export function unquote(v: string): string {
  return v.startsWith('"') && v.endsWith('"') && v.length > 1 ? v.slice(1, -1).replace(/\\(.)/g, "$1") : v;
}

export function valuesOf(token: Pick<Token, "value">): string[] {
  if (token.value.startsWith('"')) return [unquote(token.value)];
  return token.value.split(",").filter(Boolean);
}

/** Values currently included (or excluded with neg=true) for a text field. */
export function selected(q: string, field: string, neg = false): string[] {
  const vals: string[] = [];
  for (const t of tokenize(q)) if (t.key === field && t.neg === neg) vals.push(...valuesOf(t));
  return vals;
}

function rebuild(tokens: { raw: string }[]): string {
  return tokens
    .map((t) => t.raw)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Replace every clause on `field` with the given sign by one `field:v1,v2` clause. */
export function setValues(q: string, field: string, values: string[], neg = false): string {
  const tokens: { raw: string }[] = tokenize(q).filter((t) => !(t.key === field && t.neg === neg));
  if (values.length) {
    const sign = neg ? "-" : "";
    const simple = values.every((v) => !/[\s",]/.test(v));
    if (values.length === 1) tokens.push({ raw: `${sign}${field}:${quote(values[0])}` });
    else if (simple) tokens.push({ raw: `${sign}${field}:${values.join(",")}` });
    else for (const v of values) tokens.push({ raw: `${sign}${field}:${quote(v)}` });
  }
  return rebuild(tokens);
}

/** Toggle one value; including a value removes an exclusion of it and vice versa. */
export function toggleValue(q: string, field: string, value: string, neg = false): string {
  const cur = selected(q, field, neg);
  const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
  let out = setValues(q, field, next, neg);
  const other = selected(out, field, !neg).filter((v) => v !== value);
  out = setValues(out, field, other, !neg);
  return out;
}

/** Add or replace a numeric clause such as latency:>1.2s (one per field + direction). */
export function setNumeric(q: string, field: string, expr: string): string {
  const dir = (s: string) => /^[<>]/.test(s);
  const tokens: { raw: string }[] = tokenize(q).filter(
    (t) => !(t.key === field && !t.neg && dir(t.value) === dir(expr)),
  );
  if (expr) tokens.push({ raw: `${field}:${expr}` });
  return rebuild(tokens);
}

export function hasClause(q: string, raw: string): boolean {
  return tokenize(q).some((t) => t.raw === raw);
}

export function removeToken(q: string, raw: string): string {
  return rebuild(tokenize(q).filter((t) => t.raw !== raw));
}

export function addToken(q: string, raw: string): string {
  return hasClause(q, raw) ? q : rebuild([...tokenize(q), { raw }]);
}

/** The token under the caret, for autocomplete. A dangling "field:" counts as that field. */
export function tokenAt(q: string, caret: number): Token | null {
  for (const t of tokenize(q)) {
    if (caret >= t.start && caret <= t.end) {
      const m = !t.key ? /^-?([A-Za-z_][\w.]*):$/.exec(t.raw) : null;
      if (m) return { ...t, key: m[1].toLowerCase(), value: "" };
      return t;
    }
  }
  return null;
}

const STATUS_NORM: Record<string, string> = { err: "error", errors: "error", failed: "error", success: "ok" };

/**
 * Client-side check that mirrors the server's parser closely enough to avoid sending half-typed
 * queries ("latency:>", "model:"). Returns an error message or null.
 */
export function validate(q: string): string | null {
  for (const t of tokenize(q)) {
    if (!t.key) {
      const m = /^-?([A-Za-z_][\w.]*):$/.exec(t.raw);
      if (m) {
        const name = ALIASES[m[1].toLowerCase()] || m[1].toLowerCase();
        if (FIELDS.some((f) => f.name === name)) return `${name}: missing a value`;
      }
      if (t.value.startsWith('"') && (t.value.length < 2 || !t.value.endsWith('"'))) return "unterminated quote";
      continue;
    }
    const name = ALIASES[t.key] || t.key;
    const f = FIELDS.find((x) => x.name === name);
    if (!f)
      return `unknown field '${t.key}'; use one of: ${FIELDS.map((x) => x.name).join(", ")} (quote text that contains ':')`;
    if (f.kind === "num") {
      const op = /^(>=|<=|!=|>|<|=)/.exec(t.value);
      const rest = op ? t.value.slice(op[1].length) : t.value;
      if (!rest) return `${name}: missing a number after '${op ? op[1] : ""}'`;
      const m = NUM_RE.exec(rest);
      if (!m) return `${name}: expected a number, got '${rest}'`;
      const unit = m[2].toLowerCase();
      if (name === "latency" && !["", "ms", "s", "sec", "m", "min"].includes(unit))
        return `latency: unknown unit '${unit}' (use ms, s or m)`;
    } else {
      if (t.value.startsWith('"') && (t.value.length < 2 || !t.value.endsWith('"'))) return "unterminated quote";
      if (f.values && (name === "status" || name === "kind")) {
        const norm = (v: string) => STATUS_NORM[v.toLowerCase()] || v.toLowerCase();
        const bad = valuesOf(t)
          .map(norm)
          .find((v) => !f.values!.includes(v));
        if (bad) return name === "status" ? "status: use ok or error" : `kind: use one of ${f.values.join(", ")}`;
      }
    }
  }
  return null;
}

/** Whether a validation message is just "keep typing" rather than a real mistake. */
export function isSoftError(message: string): boolean {
  return /missing a (value|number)/.test(message);
}

/** Human description of a token, for the parsed-filter pills. */
export function describe(token: Token): { field: string; op: string; value: string } {
  if (!token.key) return { field: "text", op: token.neg ? "excludes" : "contains", value: unquote(token.value) };
  const name = ALIASES[token.key] || token.key;
  const f = FIELDS.find((x) => x.name === name);
  if (f && f.kind === "num") {
    const m = /^(>=|<=|!=|>|<|=)?(.*)$/.exec(token.value)!;
    return { field: name, op: (token.neg ? "not " : "") + (m[1] || "="), value: m[2] };
  }
  const vals = valuesOf(token);
  return {
    field: name,
    op: token.neg ? (vals.length > 1 ? "not in" : "is not") : vals.length > 1 ? "in" : "is",
    value: vals.join(", "),
  };
}

export function fmtLatencyExpr(ms: number): string {
  if (ms >= 1000) return `>${(ms / 1000).toFixed(ms >= 10000 ? 0 : 2).replace(/\.?0+$/, "")}s`;
  return `>${Math.max(1, Math.round(ms))}ms`;
}

export interface Suggestion {
  insert: string;
  label: string;
  desc: string;
  replace: Token | null;
  keepOpen?: boolean;
}

/** Autocomplete suggestions for the caret position, using facet values when known. */
export function suggest(
  q: string,
  caret: number,
  facets: Record<string, { value: string | null; count: number }[]>,
  focusedEmpty: boolean,
): Suggestion[] {
  const tok = tokenAt(q, caret);
  if (!tok) {
    return focusedEmpty
      ? FIELDS.map((f) => ({ insert: `${f.name}:`, label: `${f.name}:`, desc: f.hint, replace: null, keepOpen: true }))
      : [];
  }
  if (!tok.key) {
    const word = tok.value.toLowerCase();
    if (!word || word.startsWith('"')) return [];
    const sign = tok.neg ? "-" : "";
    return FIELDS.filter((f) => f.name.startsWith(word) && f.name !== word).map((f) => ({
      insert: `${sign}${f.name}:`,
      label: `${sign}${f.name}:`,
      desc: f.hint,
      replace: tok,
      keepOpen: true,
    }));
  }
  const f = FIELDS.find((x) => x.name === (ALIASES[tok.key!] || tok.key));
  if (!f) return [];
  const parts = tok.value.split(",");
  const last = parts[parts.length - 1].toLowerCase().replace(/^"/, "");
  const head = parts.slice(0, -1);
  const pool: { v: string; n: number | null }[] =
    f.kind === "text"
      ? (facets[f.name] || []).filter((v) => v.value !== null).map((v) => ({ v: v.value as string, n: v.count }))
      : [];
  for (const v of f.values || []) if (!pool.some((p) => p.v === v)) pool.push({ v, n: null });
  const sign = tok.neg ? "-" : "";
  return pool
    .filter((p) => !head.includes(p.v) && p.v.toLowerCase().startsWith(last) && p.v.toLowerCase() !== last)
    .slice(0, 10)
    .map((p) => ({
      insert: `${sign}${f.name}:${head.length ? [...head, p.v].join(",") : quote(p.v)} `,
      label: p.v,
      desc: p.n !== null ? `${p.n} trace${p.n === 1 ? "" : "s"}` : f.hint,
      replace: tok,
    }));
}

/** Apply a suggestion to the input value; returns the new value and caret. */
export function applySuggestion(value: string, s: Suggestion): { value: string; caret: number } {
  if (s.replace) {
    const next = value.slice(0, s.replace.start) + s.insert + value.slice(s.replace.end).replace(/^\s+/, "");
    return { value: next, caret: s.replace.start + s.insert.length };
  }
  const sep = value && !/\s$/.test(value) ? " " : "";
  const next = value + sep + s.insert;
  return { value: next, caret: next.length };
}
