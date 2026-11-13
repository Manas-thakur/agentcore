# Design references

The AgentCore web app borrows interaction patterns from a few tools that agent and LLM developers
already use every day. We took patterns, not looks: AgentCore keeps its own colours, type and
icons, and still ships as plain HTML/CSS/ES modules with no build step and no CDN scripts.

## References

| Reference | What we looked at |
|---|---|
| Langfuse trace explorer | Query bar, faceted filter sidebar with counts, volume histogram, dense trace table, side peek with a nested span tree and detail tabs |
| Linear agent panel and app shell | "Worked for N sec" run summary above an agent reply, "added to context" chips, low-contrast activity timeline, sectioned sidebar, command palette, keyboard-first navigation |
| LangSmith-style experiment comparison (dataset runs side by side) | Cases x runs results matrix with pass/fail/score cells and regressions called out, click-through to one case's trajectory |

## What AgentCore adopted, and why

### Traces explorer (from Langfuse)

- **Structured query bar** (`status:error -model:mock tool:calculator latency:>1s "free text"`).
  Typing beats clicking for people who live in logs, and a query string is easy to share and
  deep-link. The grammar is deliberately small (fields, `-` negation, `,` any-of, `*` wildcard,
  numeric comparisons with units) and the server parser is the source of truth; the browser only
  mirrors the tokenizer for autocomplete and to avoid sending half-typed clauses.
- **Facet sidebar with per-value counts** (status, source, model, tool, root name). Counts tell
  you where the volume and the failures are before you filter. Counts for a field ignore that
  field's own clauses (disjunctive faceting), so after picking `status:error` you can still see
  how many `ok` traces there are. Checkboxes and the exclude button just edit the query string,
  so the bar always shows the whole filter.
- **Volume histogram with drag-to-zoom.** A time distribution with failures stacked on top makes
  spikes obvious, and dragging over it is the fastest way to narrow a time range. Preset ranges
  (1h / 24h / 7d / All) remain for keyboard users.
- **Quick filter chips** (Errors, Slow > p95, Expensive). The thresholds come from the current
  window's percentiles and are inserted into the query as plain clauses, so nothing is hidden.
- **Dense sortable table + side peek.** Opening a trace beside the list (instead of navigating
  away) keeps your place; `j`/`k` walk the list while the peek follows. The peek shows metadata
  pills, a nested span tree whose latency bars are proportional to the root span, and Preview /
  Attributes / JSON tabs. Preview renders inputs, outputs, chat messages and tool arguments and
  results for humans; JSON (formatted or raw) is there when you need the exact payload.
- **Deep links.** `#/traces/<id>?query=...` reopens the same list, filters and peek.

### Playground (from Linear's agent panel)

- **Collapsible run summary** ("Worked for 1.2 s · 2 tool calls · 183 tokens") above every reply.
  The old inline tool cards were useful but noisy; most of the time you want the answer. The
  summary keeps the facts one click away and expands into a step timeline: model call, tool call
  with arguments and result, final answer, each with timings.
- **"Added to context" chips** in the expanded summary list what the model saw besides the new
  message: the system prompt (default or custom), earlier messages from the chat and the tools.
- **Run settings in a right-hand panel** with explicit controls (model, tool switches, a max-steps
  slider with an exact input, system prompt), toggled with `.` so the conversation can use the
  full width.

### App shell (from Linear)

- **Sectioned sidebar** (Build / Observe / Evaluate) so the six views read as three jobs.
- **Command palette** (`Ctrl/Cmd+K`): go to any view, start a new chat, open a recent trace by id
  or text, reopen a chat, run an eval suite, toggle the theme. One entry point that works from
  anywhere is faster than learning where every button lives.
- **Keyboard-first**: `?` lists every shortcut, `g` + letter jumps between views, `n` starts a chat,
  `/` focuses the main input of the current view, `Esc` closes whatever is on top.
- **Calmer visual system**: one accent colour, hairline borders, elevation only on floating layers
  (peeks, palette, toasts), a 4/8 px spacing scale and motion of 200 ms or less that switches off
  with `prefers-reduced-motion`. Status colours are reserved for status.

### Evals (from experiment comparison views)

- **Results matrix**: cases as rows and the most recent completed runs as columns (oldest on the
  left), each cell showing pass, or the score when it failed. A regression (worse than the previous
  run, or failing where the baseline passed) gets a red outline so it stands out in a sea of green.
  Column headers select a run for the detailed view below; arrow keys move between cells.
- **Case peek**: clicking a cell opens that case's input, output, per-metric results, the recorded
  trajectory and a strip of the same case across runs, plus a link to the agent trace. Baselines,
  history and the "Run suite" flow are unchanged.

### Overview

- **KPI cards with sparklines and a delta vs the previous period** of the same length, coloured by
  whether the change is good (lower latency, higher success rate) rather than by direction.
- Latency p50/p95, runs, tokens and cost over time, and **top tools with error rates** that link
  straight into the traces explorer filtered by that tool.

## Accessibility and responsiveness

- Light and dark themes; text tokens meet WCAG AA (4.5:1) against the backgrounds they sit on.
- Visible focus rings, real buttons and form controls, roving focus in the span tree, tabs and
  results matrix, and `aria-live` for streamed replies and query errors.
- At 375 px the facet sidebar becomes a bottom sheet behind a Filters button and every side peek
  becomes a full-screen sheet.
