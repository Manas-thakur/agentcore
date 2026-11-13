import { describe, expect, it } from "vitest";

import {
  applySuggestion,
  describe as describeToken,
  fmtLatencyExpr,
  removeToken,
  selected,
  setNumeric,
  setValues,
  suggest,
  tokenAt,
  tokenize,
  toggleValue,
  validate,
} from "./query";

describe("query tokenizer", () => {
  it("splits fields, negation, quotes and free text", () => {
    const t = tokenize('status:error -model:mock latency:>1.5s "division by zero" refund');
    expect(t.map((x) => [x.neg, x.key, x.value])).toEqual([
      [false, "status", "error"],
      [true, "model", "mock"],
      [false, "latency", ">1.5s"],
      [false, null, '"division by zero"'],
      [false, null, "refund"],
    ]);
    expect(t[1]).toMatchObject({ start: 13, end: 24 });
  });

  it("keeps colons inside values (name:agent.run:eval:*)", () => {
    const [t] = tokenize("name:agent.run:eval:*");
    expect(t.key).toBe("name");
    expect(t.value).toBe("agent.run:eval:*");
  });

  it("reads any-of values and the token under the caret", () => {
    expect(selected("model:mock,ollama:* -model:x", "model")).toEqual(["mock", "ollama:*"]);
    expect(selected("model:mock -model:x", "model", true)).toEqual(["x"]);
    expect(tokenAt("status:error tool:", 18)).toMatchObject({ key: "tool", value: "" });
  });
});

describe("query editing", () => {
  it("toggles facet values and exclusions", () => {
    let q = toggleValue("", "status", "error");
    expect(q).toBe("status:error");
    q = toggleValue(q, "model", "mock");
    q = toggleValue(q, "model", "ollama:qwen");
    expect(q).toBe("status:error model:mock,ollama:qwen");
    q = toggleValue(q, "model", "mock", true);
    expect(q).toBe("status:error -model:mock model:ollama:qwen");
    expect(setValues(q, "model", [])).toBe("status:error -model:mock");
  });

  it("quotes values with spaces", () => {
    expect(setValues("", "name", ["my agent"])).toBe('name:"my agent"');
  });

  it("replaces numeric clauses of the same direction", () => {
    expect(setNumeric("latency:>1s tokens:>5", "latency", ">2s")).toBe("tokens:>5 latency:>2s");
    expect(removeToken("a status:error b", "status:error")).toBe("a b");
    expect(fmtLatencyExpr(1234)).toBe(">1.23s");
    expect(fmtLatencyExpr(80.4)).toBe(">80ms");
  });

  it("describes tokens for pills", () => {
    const [a, b, c] = tokenize('-status:ok latency:>=2s "free text"');
    expect(describeToken(a)).toEqual({ field: "status", op: "is not", value: "ok" });
    expect(describeToken(b)).toEqual({ field: "latency", op: ">=", value: "2s" });
    expect(describeToken(c)).toEqual({ field: "text", op: "contains", value: "free text" });
  });
});

describe("validation mirrors the server parser", () => {
  it.each([
    ["status:error tool:calculator", null],
    ["model:", "model: missing a value"],
    ["latency:>", "latency: missing a number after '>'"],
    ["latency:>2h", "latency: unknown unit 'h' (use ms, s or m)"],
    ["status:maybe", "status: use ok or error"],
    ['"unterminated', "unterminated quote"],
  ])("%s", (q, expected) => {
    expect(validate(q)).toBe(expected);
  });

  it("rejects unknown fields", () => {
    expect(validate("colour:red")).toMatch(/^unknown field 'colour'/);
  });
});

describe("autocomplete", () => {
  const facets = { model: [{ value: "mock", count: 3 }, { value: "ollama:qwen", count: 1 }] };

  it("suggests fields on an empty query and values with counts", () => {
    expect(suggest("", 0, facets, true).map((s) => s.label)).toContain("latency:");
    const s = suggest("model:o", 7, facets, false);
    expect(s.map((x) => x.label)).toEqual(["ollama:qwen"]);
    expect(applySuggestion("model:o", s[0])).toEqual({ value: "model:ollama:qwen ", caret: 18 });
  });

  it("completes a partial field name", () => {
    const s = suggest("-mo", 3, facets, false);
    expect(s[0]).toMatchObject({ insert: "-model:", keepOpen: true });
  });
});
