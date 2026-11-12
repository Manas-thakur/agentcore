# Part 9: `agentcore-deploy` — Deployment Infrastructure

## Purpose

Building an agent system is only half the work. Deploying it reliably, scaling it, monitoring it, and updating it without downtime is the other half. This package provides deployment templates, CI/CD pipelines, and infrastructure-as-code for running AgentCore in production — from a single Docker container on a laptop to a Kubernetes cluster on GCP.

## Philosophy

**Local-first, cloud-ready.** Every component works locally with zero cloud dependencies. When you're ready to deploy to the cloud, you add infrastructure — you don't modify application code.

## Component Breakdown

### 1. Docker

**File:** `infra/docker/`

**`Dockerfile` (Python API):**
```dockerfile
# Multi-stage build for production
FROM python:3.11-slim AS builder
RUN pip install uv
COPY packages/python/ /packages/
WORKDIR /packages
RUN uv sync --no-dev

FROM nvidia/cuda:12.4-runtime-ubuntu22.04 AS runtime
# Only if GPU needed
COPY --from=builder /packages /app
WORKDIR /app
EXPOSE 8000
CMD ["uvicorn", "agentcore.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`docker-compose.yml` (Full Stack):**
```yaml
version: "3.8"
services:
  agent-api:
    build: .
    ports: ["8000:8000"]
    environment:
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
      - VECTOR_STORE=lancedb
      - OBSERVABILITY_BACKEND=sqlite
    volumes:
      - ./data:/data
    depends_on: [ollama]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ./ollama_data:/root/.ollama
    ports: ["11434:11434"]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  dashboard:
    build: ./packages/typescript/dashboard
    ports: ["3000:3000"]
    environment:
      - API_URL=http://agent-api:8000

  vector-db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: vectors
      POSTGRES_USER: agentcore
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - ./pgvector_data:/var/lib/postgresql/data
```

---

### 2. CI/CD (GitHub Actions)

**File:** `.github/workflows/`

**`ci.yml` — Main CI Pipeline:**
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install uv && uv sync && uv run ruff check .
      - run: uv run mypy packages/

  test:
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install uv && uv sync && uv run pytest packages/ --cov

  eval:
    runs-on: [self-hosted, gpu]  # Or ubuntu-latest for CPU-only eval
    steps:
      - uses: actions/checkout@v4
      - run: pip install uv && uv sync
      - run: uv run agentcore eval --suite regression
      - uses: actions/github-script@v7
        with:
          script: |
            const report = require('fs').readFileSync('eval-report.md', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: report
            });

  build:
    runs-on: ubuntu-latest
    needs: [lint, test, eval]
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t agentcore-api .
      - run: docker tag agentcore-api ghcr.io/${{ github.repository }}/agentcore-api:${{ github.sha }}
      - run: echo "${{ secrets.GITHUB_TOKEN }}" | docker login ghcr.io -u ${{ github.actor }} --password-stdin
      - run: docker push ghcr.io/${{ github.repository }}/agentcore-api:${{ github.sha }}
```

**`release.yml` — Release Pipeline:**
```yaml
name: Release
on:
  push:
    tags: ["v*"]
jobs:
  pypi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install build && python -m build packages/python/runtime
      - run: twine upload dist/* --username __token__ --password ${{ secrets.PYPI_TOKEN }}

  npm:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: npm publish packages/typescript/cli/
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

---

### 3. Helm Charts (Kubernetes)

**File:** `infra/helm/agentcore/`

```
helm/agentcore/
├── Chart.yaml
├── values.yaml
├── templates/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── hpa.yaml
│   └── pvc.yaml
```

**Key Values:**
```yaml
# values.yaml
replicaCount: 2

image:
  repository: ghcr.io/manas-thakur/agentcore-api
  tag: latest
  pullPolicy: Always

resources:
  requests:
    cpu: "1"
    memory: "2Gi"
  limits:
    cpu: "4"
    memory: "8Gi"
    nvidia.com/gpu: 1  # For GPU nodes

ollama:
  enabled: true
  model: llama3.1:8b

vectorStore:
  type: pgvector
  host: postgresql-headless
  port: 5432
  database: vectors

observability:
  traces:
    exporter: otlp
    endpoint: tempo.monitoring:4317
  metrics:
    exporter: prometheus
    port: 8000
  logs:
    exporter: loki
    url: http://loki.monitoring:3100

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

ingress:
  enabled: true
  host: agentcore.example.com
  tls: true
```

---

### 4. Terraform (GCP)

**File:** `infra/terraform/`

```
terraform/
├── main.tf
├── variables.tf
├── outputs.tf
├── modules/
│   ├── cloud-run/
│   ├── cloud-sql/
│   ├── artifact-registry/
│   ├── load-balancer/
│   └── monitoring/
└── environments/
    ├── dev.tfvars
    └── prod.tfvars
```

**`main.tf` Structure:**
```hcl
module "cloud_run" {
  source   = "./modules/cloud-run"
  name     = "agentcore-api"
  image    = "ghcr.io/manas-thakur/agentcore-api:latest"
  cpu      = 4
  memory   = "8Gi"
  
  env_vars = {
    LLM_PROVIDER        = "ollama"
    VECTOR_STORE        = "pgvector"
    DATABASE_URL        = module.cloud_sql.connection_string
    OBSERVABILITY_TRACE = "otlp"
  }
  
  # For GPU: use Cloud Run with GPU enabled (or GKE)
  # Or use Ollama on GKE/GCE + Cloud Run for stateless API
}

module "cloud_sql" {
  source      = "./modules/cloud-sql"
  name        = "agentcore-db"
  database    = "vectors"
  extensions  = ["pgvector"]
  tier        = "db-f1-micro"  # Free tier
}

module "artifact_registry" {
  source = "./modules/artifact-registry"
  name   = "agentcore-images"
}
```

---

### 5. Environment Configuration

**File:** `agentcore/deploy/config.py`

**Purpose:** Provide a unified configuration system that reads from environment variables, `.env` files, or configuration management systems.

```python
@dataclass
class AgentCoreConfig:
    # LLM
    llm_provider: str = "ollama"                # "ollama" | "openai" | "vllm"
    llm_model: str = "llama3.1:8b"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    
    # Vector Store
    vector_store: str = "lancedb"               # "lancedb" | "chroma" | "pgvector" | "pinecone"
    lancedb_uri: str = "./.lancedb"
    pgvector_connection_string: str = ""
    pinecone_api_key: str = ""
    
    # Observability
    observability_backend: str = "sqlite"       # "sqlite" | "otlp" | "prometheus" | "none"
    otlp_endpoint: str = "http://localhost:4317"
    prometheus_port: int = 8000
    
    # Storage
    data_dir: str = "./data"
    
    @classmethod
    def from_env(cls) -> "AgentCoreConfig":
        """Load config from environment variables (with .env file support)."""
        ...
```

---

## File Structure

```
packages/python/deploy/
├── __init__.py
├── config.py              # AgentCoreConfig

infra/
├── docker/
│   ├── Dockerfile.api
│   ├── Dockerfile.dashboard
│   ├── docker-compose.yml
│   └── .dockerignore
├── helm/
│   └── agentcore/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── modules/
│   └── environments/

.github/workflows/
├── ci.yml
├── release.yml
├── eval.yml
└── deploy.yml
```
