---
title: Contributing
description: Set up the Python, web app and docs toolchains, run the checks, and open a pull request.
---

Thanks for your interest in improving AgentCore. Bug reports, documentation fixes, tests and
features are all welcome. This file explains how the repository is laid out, how to set up each
toolchain, and what a pull request needs to pass.

## Repository layout

| Path | What it is | Toolchain |
|---|---|---|
| `src/agentcore/` | The Python package (runtime, tools, eval, rag, index, graph, agents, obs, server, CLI) | Python 3.10+, [uv](https://docs.astral.sh/uv/) |
| `tests/` | pytest suite, fully offline | uv |
| `web/` | The web app (Vite, React 19, TypeScript, Tailwind CSS v4, shadcn/ui) | Node 20+, pnpm 10 |
| `src/agentcore/server/static/` | **Build output** of `web/`, committed so `pip install` needs no Node.js | generated |
| `site/` | Landing page and documentation (Astro + Starlight) | Node 20+, pnpm 10 |
| `examples/` | Runnable demos, sample corpus, eval suite | uv |
| `docs/` | README screenshots and design notes | - |
| `plans/` | The original design documents for each component | - |

## Python

```bash
git clone https://github.com/Manas-thakur/agentcore.git
cd agentcore
uv sync --all-extras          # or: make install

uv run pytest -q              # tests (offline, a few seconds)
uv run ruff check .           # lint
uv run ruff format --check .  # formatting (run `uv run ruff format .` to fix)
uv run agentcore eval --suite examples/evals/calculator_suite.yaml --model mock
```

Everything runs on the deterministic `mock` model, so no model server or API key is needed. New
behaviour needs a test; if it talks to a model, use `ScriptedModel`, `MockModel` or a recorded
cassette instead of a live server.

## Web app (`web/`)

```bash
cd web
pnpm install
pnpm dev          # Vite on http://127.0.0.1:8762, proxies the API to http://127.0.0.1:8761

# in another terminal, from a directory with some data:
uv run agentcore serve --model mock --port 8761
```

Set `AGENTCORE_URL` to proxy to another server. Before opening a pull request:

```bash
pnpm typecheck    # tsc
pnpm lint         # ESLint, zero warnings
pnpm test         # Vitest (SSE parser, query tokenizer, chat event folding)
pnpm build        # writes ../src/agentcore/server/static
```

**Commit the build output** together with the source change: CI rebuilds the app and fails if
`src/agentcore/server/static/` differs from what is committed.

Conventions:

- UI primitives come from shadcn/ui (`src/components/ui/`, added with
  `pnpm dlx shadcn@latest add <name>`). Keep them close to upstream; compose them in
  `src/components/` and the pages in `src/pages/`.
- Agent-specific views follow the shadcn AI Elements patterns (`src/components/ai/`).
- No CDN scripts, remote fonts or analytics: fonts come from `@fontsource`.
- Every view needs loading, empty and error states, keyboard access and a 375 px layout. Check both
  themes.
- The trace query tokenizer in `src/lib/query.ts` mirrors `src/agentcore/server/query.py`; change
  them together and extend the tests on both sides.

## Docs site (`site/`)

```bash
cd site
pnpm install
pnpm dev          # http://127.0.0.1:8763/agentcore/
pnpm build        # static site in site/dist, fails on broken internal links
```

Docs pages are Markdown in `site/src/content/docs/docs/`; the landing page is
`site/src/pages/index.astro`. Every code example must run as written against the current code:
run it before you commit. Screenshots come from `docs/screenshots/` (shared with the README); when
they are made with the mock model and generated traces, say so in the caption.

The site is deployed to GitHub Pages by `.github/workflows/pages.yml` on pushes to `main` that touch
`site/` or `docs/`.

## Pull requests

- Keep each pull request focused on one change, and describe what changed and why.
- Make sure `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .` and, for web
  changes, `pnpm typecheck && pnpm lint && pnpm test && pnpm build` pass.
- Update the docs (`site/`), the README and `CHANGELOG.md` (under *Unreleased*) when behaviour
  changes.
- Content must be accurate: no invented numbers, testimonials or claims the code does not support.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml`, `__version__` in `src/agentcore/__init__.py`, `version` in
   `web/package.json` and `site/package.json`, run `uv lock`, and move the *Unreleased* changelog
   entries under the new version.
2. Tag and push: `git tag v0.3.0 && git push origin v0.3.0`.
3. `.github/workflows/release.yml` builds the web app, tests and builds the sdist and wheel, creates
   the GitHub Release and pushes the Docker image to `ghcr.io/manas-thakur/agentcore`.

## License

By contributing you agree that your contributions are licensed under the [MIT License](https://github.com/Manas-thakur/agentcore/blob/main/LICENSE).
