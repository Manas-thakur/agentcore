---
title: Trace query language
description: The small query language used by the trace explorer and GET /api/traces?query=.
---

The trace explorer's query bar, `GET /api/traces?query=` and `GET /api/traces/explore?query=` share
one parser (`src/agentcore/server/query.py`). A query is a list of terms separated by spaces; every
term must match (AND).

```text
status:error -model:mock latency:>1.5s
tool:calculator tokens:>=500 "division by zero"
name:agent.run:eval:* cost:>0.01 -refund
kind:chat -status:ok latency:>2s
```

## Terms

| Form | Meaning |
|---|---|
| `field:value` | Filter on a field |
| `-field:value` | Exclude: the trace must **not** match |
| `field:a,b` | Any of the values |
| `field:pre*` | Wildcard (`*` any characters, `?` one character), case-insensitive |
| `field:"a value"` | Quoted value (spaces, commas or colons); `\"` escapes a quote |
| `word` or `"some phrase"` | Free text, matched case-insensitively against the trace id, root name, model, input, output and error |
| `-word` | Free text that must not appear |

## Text fields

| Field | Matches | Values |
|---|---|---|
| `status` | Trace status | `ok`, `error` (also `err`, `errors`, `failed`, `success`) |
| `model` | Model of the root span | e.g. `mock`, `ollama:qwen2.5:7b`, `ollama:*` |
| `tool` | Any tool the run called | e.g. `calculator` |
| `name` | Root span name | e.g. `agent.run:chat`, `agent.run:eval:*` |
| `kind` | Where the trace came from | `chat` (web chat), `api` (`/v1/agent`), `openai` (`/v1/chat/completions`), `eval`, `tool` (Tools page), `other` |
| `session` | Chat session id (web chats) | e.g. `s_0677839052f4` |
| `id` | Trace id **prefix** | e.g. `id:38df0b` |

Text matching is exact and case-insensitive, except `id` (prefix) and values with wildcards.

## Numeric fields

| Field | Unit |
|---|---|
| `latency` | Milliseconds by default; `ms`, `s` (or `sec`) and `m` (or `min`) suffixes |
| `tokens` | Tokens (a `k` suffix multiplies by 1000) |
| `cost` | USD (optional `usd` suffix) |
| `steps` | Model steps of the run |
| `spans` | Number of spans |
| `tools` | Number of tool calls |

Numeric clauses take a comparison: `>`, `>=`, `<`, `<=`, `=` (or none) and `!=`.
`latency:>2s`, `tokens:<=800`, `cost:>0.01`, `tools:>=2`, `steps:3`.

## Aliases

`duration` and `lat` mean `latency`, `level` means `status`, `trace` and `trace_id` mean `id`,
`session_id` means `session`, `token` means `tokens`, `usd` means `cost`, `type` means `kind`.

## Errors

An unknown field, a missing value (`model:`), a bad number (`latency:>fast`), an unknown latency
unit or an unterminated quote is a parse error. The API answers `400` with the message and the
character position:

```json
{"detail": "unknown field 'colour'; use one of: cost, id, kind, latency, model, name, session, spans, status, steps, tokens, tool, tools (quote text that contains ':')", "position": 0, "type": "query_error"}
```

In the web app, half-typed clauses (`model:`, `latency:>`) show a neutral "keep typing" hint
instead of an error, and the query is applied as soon as it parses.

## Facet counts

`GET /api/traces/explore` and `GET /api/traces/facets` return per-value counts for `status`, `kind`,
`model`, `tool` and `name`. The counts for one field ignore the query's clauses on **that** field
(disjunctive faceting), so after `status:error` you still see how many `ok` traces there are.
