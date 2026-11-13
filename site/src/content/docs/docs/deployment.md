---
title: Deployment
description: Run agentcore serve with Docker or docker compose, protect it with an API key, configure CORS and request limits, and put it behind a reverse proxy.
---

`agentcore serve` is a single FastAPI process (uvicorn) that serves the web app and the HTTP API.
State is files: traces (JSONL), chat sessions and eval history (JSON). Run one process per state
directory.

## Docker

The release image `ghcr.io/manas-thakur/agentcore` (linux/amd64 and linux/arm64) runs
`agentcore serve --host 0.0.0.0 --port 8000` as a non-root user, keeps state in `/data` and has a
health check on `/health`.

```bash
docker run -d --name agentcore -p 8000:8000 \
  -e AGENTCORE_MODEL=mock \
  -e AGENTCORE_API_KEY=change-me \
  -v agentcore-data:/data \
  ghcr.io/manas-thakur/agentcore:0.3.0
```

Build it yourself with `docker build -t agentcore .` from the repository. The web app is already
built into the Python package, so the image build needs no Node.js.

To serve your own tools and eval suites, mount your project and point the configuration at it:

```bash
docker run -d -p 8000:8000 -v "$PWD":/project -w /project \
  -e AGENTCORE_TRACE_DIR=/project/.agentcore/traces \
  ghcr.io/manas-thakur/agentcore:0.3.0 agentcore serve --host 0.0.0.0 --port 8000
```

## docker compose with Ollama

The repository's `docker-compose.yml` runs AgentCore next to Ollama:

```bash
docker compose up --build
docker compose exec ollama ollama pull qwen2.5:7b   # first run only
# open http://localhost:8000
```

`AGENTCORE_MODEL=auto` uses Ollama once the model is pulled and falls back to the mock model until
then. Uncomment the `deploy` block in the compose file for NVIDIA GPU inference.

## API key

Set `AGENTCORE_API_KEY` to require `Authorization: Bearer <key>` (or `X-API-Key: <key>`) on every
API route:

```bash
AGENTCORE_API_KEY=change-me agentcore serve --host 0.0.0.0
curl -H "Authorization: Bearer change-me" http://127.0.0.1:8000/api/traces
```

`/health`, the web app shell (`/`, `/static/*` and the app's own pages such as `/traces`) stay
public so the browser can load the app; it then asks for the key once and keeps it in local
storage. Requests without a valid key get `401` with
`{"error": {"type": "invalid_api_key", ...}}`. The key is compared in constant time and is never
returned by `/api/config`.

**Always set an API key when binding to anything other than `127.0.0.1`.** The agent can call
tools on the server; only `calculator` and `current_time` are enabled by default. Think twice
before enabling `python_exec`, the file tools or the web tools on a network.

## CORS

CORS is off unless you list origins, for browsers calling the API from another origin:

```bash
agentcore serve --cors-origins http://localhost:5173,https://app.example.com
# or AGENTCORE_CORS_ORIGINS, or [server] cors_origins in agentcore.toml
```

Allowed methods are GET, POST, DELETE and OPTIONS; allowed headers are `Authorization`,
`Content-Type` and `X-API-Key`; `X-Total-Count` is exposed. Credentials are not allowed.

## Request limits

Request bodies over `max_body_kb` (default 1024 KB) are rejected with `413`, whether the size is
declared in `Content-Length` or only discovered while streaming. Set it with `[server] max_body_kb`
or `AGENTCORE_MAX_BODY_KB`.

## Reverse proxy

The chat endpoints stream Server-Sent Events; disable response buffering for them. AgentCore
already sends `X-Accel-Buffering: no` for nginx. A minimal nginx location:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

Serve the app at the root of a host name: the web app uses absolute paths (`/api`, `/static`).

## Health and metrics

- `GET /health` returns `{"status": "ok", "version", "model", "tools", "auth"}` and is always
  public.
- `GET /metrics` returns Prometheus text (behind the API key when one is set).

## Data and retention

Traces are one `<trace_id>.jsonl` file each in the trace directory; sessions are
`sessions/<id>.json` and eval runs `evals/<suite>/runs/<run>.json` in the state directory. There is
no built-in retention policy: delete old files (for example with a cron job) to reclaim space.
