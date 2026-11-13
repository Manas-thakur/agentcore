---
title: Installation
description: Install AgentCore with pip or uv, from a release wheel, or run the Docker image from GHCR.
---

AgentCore needs **Python 3.10 or newer**. The core library depends only on `httpx`, `numpy` and
`pyyaml` (plus `tomli` on Python 3.10). Optional extras add the web server, OpenTelemetry and
pydantic support.

:::caution[Not on PyPI]
AgentCore is **not published on PyPI**, and the `agentcore` name there belongs to a different,
unrelated project: `pip install agentcore` or `pip install "agentcore[server]"` installs that
package, not this one. Always install from GitHub (below) or from a release wheel.
:::

## pip

```bash
# Library + CLI
pip install "git+https://github.com/Manas-thakur/agentcore"

# With the web app and HTTP server (FastAPI + uvicorn)
pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"

# Everything: server, OpenTelemetry, pydantic
pip install "agentcore[all] @ git+https://github.com/Manas-thakur/agentcore"

# Pin a release tag
pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore@v0.3.0"
```

The web app is a pre-built React bundle that ships **inside the Python package**
(`agentcore/server/static/`), so installing it never needs Node.js.

## uv

```bash
uv add "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"

# or as a global tool, to get the `agentcore` command
uv tool install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"
```

## Release wheel

Every tagged release on the [GitHub Releases page](https://github.com/Manas-thakur/agentcore/releases)
has an sdist and a wheel attached:

```bash
pip install "agentcore-0.3.0-py3-none-any.whl[server]"
```

## Docker (GHCR)

Releases also publish a multi-arch image (`linux/amd64`, `linux/arm64`) to the GitHub Container
Registry:

```bash
docker run --rm -p 8000:8000 -e AGENTCORE_MODEL=mock ghcr.io/manas-thakur/agentcore:latest
# open http://localhost:8000
```

Tags: `latest`, the full version (`0.3.0`) and `major.minor` (`0.3`). The image runs
`agentcore serve --host 0.0.0.0 --port 8000` as a non-root user and stores traces, chat sessions
and eval history in `/data`. See [Deployment](/agentcore/docs/deployment/) for volumes, API keys and
docker compose with Ollama.

## Optional extras

| Extra | Adds |
|---|---|
| `server` | FastAPI + uvicorn for `agentcore serve` (web app + HTTP API) |
| `otel` | OpenTelemetry API/SDK, to mirror spans to any OpenTelemetry exporter |
| `pydantic` | pydantic v2 models as tool parameters (schema + validation) |
| `all` | all of the above |

`tiktoken` is used for token counting automatically when it is installed; otherwise a calibrated
heuristic is used.

## Check the installation

```bash
agentcore --version
agentcore doctor --model mock
```

`agentcore doctor` checks the Python version, installed extras, the configuration file, the trace
directory, tool modules, eval directories and whether Ollama or an OpenAI-compatible server is
reachable. It exits with status 1 when a check fails.

## From source

```bash
git clone https://github.com/Manas-thakur/agentcore.git
cd agentcore
uv sync --all-extras
uv run pytest -q
```

See [Contributing](/agentcore/docs/contributing/) for the web app and docs site toolchains.
