// Client mirror of the trace query tokenizer (server/query.py is the source of truth). Used to
// toggle facet values and quick filters in the query string and to drive autocomplete.

export const FIELDS = [
  { name: "status", kind: "text", hint: "ok or error", values: ["ok", "error"] },
  { name: "model", kind: "text", hint: "model id, * wildcard" },
  { name: "tool", kind: "text", hint: "a tool the run called" },
  { name: "name", kind: "text", hint: "root span name" },
  { name: "kind", kind: "text", hint: "chat, api, openai, eval, tool", values: ["chat", "api", "openai", "eval", "tool", "other"] },
  { name: "session", kind: "text", hint: "chat session id" },
  { name: "id", kind: "text", hint: "trace id prefix" },
  { name: "latency", kind: "num", hint: ">2s, <=500ms", values: [">1s", ">500ms", "<100ms"] },
  { name: "tokens", kind: "num", hint: ">500", values: [">500", ">1000"] },
  { name: "cost", kind: "num", hint: ">0.01 (USD)", values: [">0.01", ">0"] },
  { name: "steps", kind: "num", hint: "model steps" },
  { name: "tools", kind: "num", hint: "number of tool calls" },
];

const TOKEN_RE = /(-?)(?:([A-Za-z_][\w.]*):)?("(?:[^"\\]|\\.)*"?|\S+)/g;

export function tokenize(q) {
  const out = [];
  TOKEN_RE.lastIndex = 0;
  let m;
  while ((m = TOKEN_RE.exec(q))) {
    if (!m[0]) {
      TOKEN_RE.lastIndex++;
      continue;
    }
    out.push({ raw: m[0], neg: m[1] === "-", key: m[2] ? m[2].toLowerCase() : null, value: m[3], start: m.index, end: m.index + m[0].length });
  }
  return out;
}

export function quote(v) {
  return /[\s",]/.test(v) ? `"${v.replace(/(["\\])/g, "\\$1")}"` : v;
}

function unquote(v) {
  return v.startsWith('"') && v.endsWith('"') && v.length > 1 ? v.slice(1, -1).replace(/\\(.)/g, "$1") : v;
}

export function valuesOf(token) {
  if (token.value.startsWith('"')) return [unquote(token.value)];
  return token.value.split(",").filter(Boolean);
}

// Values currently included (or excluded with neg=true) for a text field.
export function selected(q, field, neg = false) {
  const vals = [];
  for (const t of tokenize(q)) if (t.key === field && t.neg === neg) vals.push(...valuesOf(t));
  return vals;
}

function rebuild(tokens) {
  return tokens.map((t) => t.raw).join(" ").replace(/\s+/g, " ").trim();
}

// Replace every clause on `field` with the given sign by one `field:v1,v2` clause.
export function setValues(q, field, values, neg = false) {
  const tokens = tokenize(q).filter((t) => !(t.key === field && t.neg === neg));
  if (values.length) {
    const quoted = values.length === 1 ? quote(values[0]) : values.map((v) => (/[\s",]/.test(v) ? null : v)).every(Boolean) ? values.join(",") : null;
    if (quoted) tokens.push({ raw: `${neg ? "-" : ""}${field}:${quoted}` });
    else for (const v of values) tokens.push({ raw: `${neg ? "-" : ""}${field}:${quote(v)}` });
  }
  return rebuild(tokens);
}

export function toggleValue(q, field, value, neg = false) {
  const cur = selected(q, field, neg);
  const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
  // including a value removes an exclusion of the same value and vice versa
  let out = setValues(q, field, next, neg);
  const other = selected(out, field, !neg).filter((v) => v !== value);
  out = setValues(out, field, other, !neg);
  return out;
}

// Add or replace a numeric clause such as latency:>1.2s (one per field + operator family).
export function setNumeric(q, field, expr) {
  const tokens = tokenize(q).filter((t) => !(t.key === field && !t.neg && /^[<>]/.test(t.value) === /^[<>]/.test(expr)));
  if (expr) tokens.push({ raw: `${field}:${expr}` });
  return rebuild(tokens);
}

export function hasClause(q, raw) {
  return tokenize(q).some((t) => t.raw === raw);
}

export function removeToken(q, raw) {
  return rebuild(tokenize(q).filter((t) => t.raw !== raw));
}

export function addToken(q, raw) {
  return hasClause(q, raw) ? q : rebuild([...tokenize(q), { raw }]);
}

// The token under the caret, for autocomplete. A dangling "field:" counts as that field.
export function tokenAt(q, caret) {
  for (const t of tokenize(q)) {
    if (caret >= t.start && caret <= t.end) {
      const m = !t.key && /^-?([A-Za-z_][\w.]*):$/.exec(t.raw);
      if (m) return { ...t, key: m[1].toLowerCase(), value: "" };
      return t;
    }
  }
  return null;
}

const ALIASES = { duration: "latency", lat: "latency", level: "status", trace: "id", trace_id: "id", session_id: "session", token: "tokens", usd: "cost", type: "kind" };
const NUM_RE = /^(-?\d+(?:\.\d+)?|-?\.\d+)\s*([a-z]*)$/i;

// Client-side check that mirrors the server's parser closely enough to avoid sending
// half-typed queries ("latency:>", "model:"). Returns an error message or null.
export function validate(q) {
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
    if (!f) return `unknown field '${t.key}'; use one of: ${FIELDS.map((x) => x.name).join(", ")} (quote text that contains ':')`;
    if (f.kind === "num") {
      const op = /^(>=|<=|!=|>|<|=)/.exec(t.value);
      const rest = op ? t.value.slice(op[1].length) : t.value;
      if (!rest) return `${name}: missing a number after '${op ? op[1] : ""}'`;
      const m = NUM_RE.exec(rest);
      if (!m) return `${name}: expected a number, got '${rest}'`;
      const unit = m[2].toLowerCase();
      if (name === "latency" && !["", "ms", "s", "sec", "m", "min"].includes(unit)) return `latency: unknown unit '${unit}' (use ms, s or m)`;
    } else {
      if (t.value.startsWith('"') && (t.value.length < 2 || !t.value.endsWith('"'))) return "unterminated quote";
      if (f.values && (name === "status" || name === "kind")) {
        const norm = (v) => ({ err: "error", errors: "error", failed: "error", success: "ok" })[v.toLowerCase()] || v.toLowerCase();
        const bad = valuesOf(t).map(norm).find((v) => !f.values.includes(v));
        if (bad) return name === "status" ? "status: use ok or error" : `kind: use one of ${f.values.join(", ")}`;
      }
    }
  }
  return null;
}

// Human description of a token, for the parsed-filter pills.
export function describe(token) {
  if (!token.key) return { field: "text", op: token.neg ? "excludes" : "contains", value: unquote(token.value) };
  const f = FIELDS.find((x) => x.name === token.key);
  if (f && f.kind === "num") {
    const m = /^(>=|<=|!=|>|<|=)?(.*)$/.exec(token.value);
    return { field: token.key, op: (token.neg ? "not " : "") + (m[1] || "="), value: m[2] };
  }
  const vals = valuesOf(token);
  return { field: token.key, op: token.neg ? (vals.length > 1 ? "not in" : "is not") : vals.length > 1 ? "in" : "is", value: vals.join(", ") };
}
