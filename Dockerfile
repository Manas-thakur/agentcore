# AgentCore web app + agent API (OpenAI-compatible /v1/chat/completions included).
#   docker build -t agentcore .
#   docker run -p 8000:8000 -v agentcore-data:/data -e AGENTCORE_MODEL=mock agentcore
#   (set -e AGENTCORE_API_KEY=... before exposing it beyond localhost)
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable --extra server

FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/Manas-thakur/agentcore"       org.opencontainers.image.description="AgentCore web app, agent API and OpenAI-compatible endpoint"       org.opencontainers.image.licenses="MIT"
RUN useradd --create-home --uid 1000 agent
COPY --from=build /app /app
# The server runs as uid 1000 from /data, which it owns: traces, sessions, eval history and
# suites created from the web app ("evals/") all land there, so mount a volume at /data.
# No AGENTCORE_MODEL default here: it would override `model` in a mounted agentcore.toml.
# Without one the CLI default applies ("auto": Ollama if reachable, else the mock model).
COPY --chown=agent:agent examples /data/examples
RUN mkdir -p /data/evals /data/traces && chown -R agent:agent /data
WORKDIR /data
ENV PATH="/app/.venv/bin:$PATH"     PYTHONUNBUFFERED=1     AGENTCORE_TRACE_DIR=/data/traces
USER agent
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["agentcore", "serve", "--host", "0.0.0.0", "--port", "8000"]
