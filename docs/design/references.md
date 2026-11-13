# Design references

The AgentCore web app borrows interaction patterns from a few tools that agent and LLM developers
already use every day. We took patterns, not looks: AgentCore keeps its own colours, type and
icons. Since 0.3.0 it is built on a component kit (below) and ships as a pre-built bundle inside
the Python package, still with no CDN scripts or remote fonts.

## UI kit (0.3.0)

| Layer | Choice |
|---|---|
| Build | Vite, React 19, TypeScript (strict), sources in `web/`, output in `src/agentcore/server/static/` |
| Styling | Tailwind CSS v4 with CSS-variable design tokens (one indigo accent, status and span-kind colours) |
| Components | shadcn/ui (Radix primitives, "nova" preset): sidebar, command, dialog, sheet, popover, tabs, table, toggle group, resizable, sonner toasts, skeleton, empty, item, field, input group |
| Agent patterns | shadcn AI Elements, built on its Trace, Message, Bubble, Message Scroller and Code Block components |
| Data | TanStack Table (traces), shadcn charts on Recharts (overview, histogram, sparklines) |
| Code | Shiki with a small language set, loaded on demand; react-markdown (no raw HTML) for answers |
| Fonts | Geist and Geist Mono via `@fontsource`, bundled |

**Why this kit.** The vanilla app had grown to ~5,000 lines of hand-rolled DOM code, its own
dialog, popover, tab and focus logic, and its own charts. Every new view re-implemented the same
primitives and their accessibility details. shadcn/ui gives copy-in components (the code lives in
our repository, so nothing is hidden behind a package API) on top of Radix, which handles focus
management, roving tabindex, dismissal, portals and ARIA for menus, dialogs, sheets and tabs. AI
Elements adds a consistent vocabulary for agent activity: every step (a tool call, a reasoning
block, a test result, a subagent run) is a *Trace* line that can expand, so the Playground's run
summary, the trace preview and the eval views look and behave the same. Tailwind tokens keep both
themes consistent and meet WCAG AA contrast. The cost is a build step for contributors; users are
unaffected because the build is committed into the package, and CI fails when it is stale.

**What we did not adopt.** The AI SDK's UI hooks (`useChat`) expect the AI SDK stream protocol;
AgentCore streams its own agent events over SSE, so the app uses a small typed client
(`web/src/lib/sse.ts`, `web/src/lib/chat.ts`) that folds those events into the same turn shape the
server persists. Motion and Streamdown (used by some AI Elements demos) were left out to keep the
bundle small; shimmer and streaming effects are CSS.

### Where each AI Elements pattern is used

| Pattern | Where |
|---|---|
| Chat, Message, Message Scroller | Playground thread (keeps your place while a reply streams) |
| Prompt Input, Model Selector, Suggestion | Playground composer, model picker (models from `/v1/models` plus free-text specs), example prompts |
| Chain of Thought, Task, Reasoning, Tool | The run summary ("Worked for 1.2 s · 2 tool calls") and its step timeline; tool calls in the trace preview |
| Context | The Playground's context meter (memory window, tokens, cost) |
| Stack Trace | Failed runs, spans, eval runs and cases |
| Queue, Test Results | Running eval cases (left / done) and a run's per-case results |
| Subagent | Nested agent runs (multi-agent teams) in the trace preview |
| Confirmation | Tools page: approve or deny before invoking a tool that runs code, writes files or uses the network |
| Code Block, Shimmer | JSON, schemas and code with copy buttons; running steps |

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
- **Deep links.** `/traces/<id>?query=...` reopens the same list, filters and peek (old
  `#/traces/...` links are redirected).

### Playground (from Linear's agent panel)

- **Collapsible run summary** ("Worked for 1.2 s · 2 tool calls · 183 tokens") above every reply.
  The old inline tool cards were useful but noisy; most of the time you want the answer. The
  summary keeps the facts one click away and expands into a step timeline: model call, tool call
  with arguments and result, final answer, each with timings.
- **"Added to context" chips** in the expanded summary list what the model saw besides the new
  message: the system prompt (default or custom), earlier messages from the chat and the tools.
- **Run settings in a right-hand panel** with explicit controls (model, tool switches, a max-steps
  slider with an exact input, system prompt), toggled with `.` so the conversation can use the
  full width. A sheet on narrower screens.

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
- Radix primitives for dialogs, menus, popovers, sheets and tabs; visible focus rings; roving
  focus in the span tree and results matrix; `aria-live` for streamed replies and query errors;
  motion switches off with `prefers-reduced-motion`.
- At 375 px the sidebar, chat list, run settings and facet sidebar become sheets and every side
  peek becomes a full-screen sheet; tables drop secondary columns.
