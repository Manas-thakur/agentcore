# Part 8: `agentcore-obs` — Observability Suite

## Purpose

Agentic AI systems are fundamentally complex and unpredictable. When an agent produces a wrong answer, you need to know: What was the input? What steps did it take? Which tool returned bad data? How many tokens did it use? What was the total cost? How long did each step take?

Observability answers these questions. It's not optional — it's a necessity for building reliable agent systems. This package provides distributed tracing (OpenTelemetry), metrics collection, structured logging, cost tracking, and a React dashboard for visualization.

## Architecture

```
Agent Execution
    │
    ├── OpenTelemetry Instrumentation
    │   └── Spans: session → run → step → tool_call
    │
    ├── Metrics Collection
    │   ├── Token counters (input/output per model)
    │   ├── Latency histograms (p50/p95/p99)
    │   ├── Tool usage counters
    │   └── Error rates
    │
    ├── Structured Logging
    │   └── JSON logs with correlation IDs
    │
    └── Cost Tracking
        └── Token → cost mapping per model
             |
             ▼
    ┌─────────────────────────────────────┐
    │         Export / Store              │
    │  OTLP → Grafana Tempo (traces)      │
    │  Prometheus → Grafana (metrics)     │
    │  Loki / ELK (logs)                  │
    │  SQLite / PostgreSQL (cost ledger)  │
    └─────────────────────────────────────┘
             │
             ▼
    ┌─────────────────────────────────────┐
    │   React Dashboard                  │
    │   Trace Viewer, Metrics Charts,     │
    │   Log Explorer, Cost Breakdown      │
    └─────────────────────────────────────┘
```

## Component Breakdown

### 1. OpenTelemetry Tracing

**File:** `agentcore/obs/tracing.py`

**Purpose:** Automatically instrument the agent loop to create distributed traces. Every significant event in the agent's execution becomes a span in a trace hierarchy.

**Trace Hierarchy:**

```
Trace: agent-session-xxx
├── Span: run_agent [agent.run()]
│   ├── Span: step_0 [agent.step()]
│   │   ├── Span: model_generate [model.generate()]
│   │   │   └── Event: tool_calls_detected
│   │   ├── Span: execute_tool [tool.execute()] × N (parallel)
│   │   │   ├── Span: web_search [tool: web_search]
│   │   │   └── Span: web_scrape [tool: web_scrape]
│   │   └── Span: process_results [agent.observe()]
│   ├── Span: step_1 [agent.step()]
│   │   ├── Span: model_generate
│   │   └── Span: reflect [agent.reflect()]
│   └── Span: step_2 [agent.step()]
│       └── Span: model_generate [final answer]
```

**Implementation:**

```python
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

class TracingMiddleware:
    """Injected into the agent loop to create spans."""
    
    tracer = trace.get_tracer("agentcore", "0.1.0")
    
    @contextmanager
    def agent_run_span(self, agent_name: str, task: str) -> Span:
        with self.tracer.start_as_current_span(
            f"agent.{agent_name}.run",
            attributes={"task": task, "agent": agent_name},
        ) as span:
            yield span
    
    @contextmanager
    def step_span(self, step_number: int) -> Span:
        with self.tracer.start_as_current_span(
            f"agent.step.{step_number}",
            attributes={"step": step_number},
        ) as span:
            yield span
    
    def add_tool_call_event(self, span: Span, tool_name: str, params: dict):
        span.add_event(
            "tool_call",
            attributes={"tool": tool_name, "params": json.dumps(params)},
        )
```

**Span Attributes:**
```python
SPAN_ATTRIBUTES = {
    "agent.name": str,
    "agent.run_id": str,
    "agent.iteration": int,
    "agent.max_iterations": int,
    
    "model.provider": str,       # "ollama", "openai", "vllm"
    "model.name": str,           # "llama3.1-8b", "gpt-4o"
    "model.temperature": float,
    "model.max_tokens": int,
    
    "tool.name": str,
    "tool.category": str,
    "tool.timeout": float,
    
    "tokens.prompt": int,
    "tokens.completion": int,
    "tokens.total": int,
    
    "latency.ms": float,
    
    "error": str,                # If step/tool failed
    "error.type": str,           # Exception class name
}
```

**Exporters:**
- **Console Exporter** (for development): print spans to stdout
- **OTLP Exporter** (for production): send to OpenTelemetry Collector → Grafana Tempo
- **SQLite Exporter**: store traces locally for debugging (no infrastructure needed)

---

### 2. Metrics Collection

**File:** `agentcore/obs/metrics.py`

**Purpose:** Collect quantitative measurements about agent performance, tool usage, and system health. Metrics are aggregated over time windows and exposed for Prometheus scraping or stored locally.

**Metric Types:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `agent.runs.total` | Counter | agent_name, status | Total agent runs |
| `agent.runs.duration` | Histogram | agent_name | Run duration in ms |
| `agent.steps.total` | Counter | agent_name | Total steps across runs |
| `tool.calls.total` | Counter | tool_name, status | Total tool invocations |
| `tool.calls.duration` | Histogram | tool_name | Tool execution time |
| `tokens.prompt.total` | Counter | model_name | Total prompt tokens |
| `tokens.completion.total` | Counter | model_name | Total completion tokens |
| `tokens.cost.total` | Counter | model_name | Total cost in USD |
| `errors.total` | Counter | error_type, component | Total errors |
| `memory.usage` | Gauge | type | Memory usage in MB |

**Implementation:**
```python
class MetricsCollector:
    def __init__(self, storage: MetricsStorage = "prometheus"):
        self.metrics: dict[str, Metric] = {}
    
    def counter(self, name: str, labels: dict | None = None) -> None:
        """Increment a counter metric."""
    
    def histogram(self, name: str, value: float, labels: dict | None = None) -> None:
        """Record a histogram observation."""
    
    def gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        """Set a gauge value."""
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format for scraping."""
    
    def export_json(self) -> dict:
        """Export metrics as JSON for local storage."""

class MetricsStorage:
    """Abstract storage for metrics data."""
    
    @abstractmethod
    def store_observation(self, name: str, value: float, labels: dict, timestamp: datetime): ...
    
    @abstractmethod
    def query_range(self, name: str, start: datetime, end: datetime, labels: dict | None = None) -> list[Observation]: ...
```

---

### 3. Structured Logging

**File:** `agentcore/obs/logging.py`

**Purpose:** Log every significant event with structured JSON format, correlation IDs, and sufficient context for debugging.

**Log Format:**
```json
{
    "timestamp": "2026-06-19T10:30:00.123Z",
    "level": "INFO",
    "logger": "agentcore.runtime",
    "correlation_id": "run_abc123_step_2",
    "session_id": "session_xyz",
    "agent": "researcher",
    "event": "tool_call",
    "tool": "web_search",
    "params": {"query": "latest LLM quantization techniques"},
    "duration_ms": 1500,
    "tokens_used": 250,
    "result_summary": "Found 5 relevant results",
    "metadata": {
        "source": "duckduckgo",
        "result_count": 5
    }
}
```

**Log Levels:**
| Level | When to Use |
|-------|-------------|
| DEBUG | Every step, every tool call, every model request |
| INFO | Agent start/end, tool call start/end, significant state changes |
| WARNING | Retry attempts, rate limiting, unexpected but handled errors |
| ERROR | Failed tool calls, model errors, unhandled exceptions |
| CRITICAL | System failures, data corruption, security issues |

**Log Exporters:**
- Console (colorized for development)
- File (rotating file handler for production)
- JSON stream (for log aggregators like Loki, ELK)

---

### 4. Cost Tracking

**File:** `agentcore/obs/cost.py`

**Purpose:** Track the cost of every agent run. For API-based models, this is straightforward (tokens × price). For local models, estimate cost based on GPU power consumption.

**Cost Model Configuration:**

```python
COST_TABLE = {
    "gpt-4o": {
        "input_per_1k": 0.0025,    # $0.0025 per 1K input tokens
        "output_per_1k": 0.010,    # $0.01 per 1K output tokens
    },
    "local": {
        "input_per_1k": 0.0,       # No API cost
        "output_per_1k": 0.0,
        "power_watts": 115,        # RTX 4060 power draw
        "electricity_cost_per_kwh": 0.12,  # Average US rate
    },
}
```

**Cost Calculator:**
```python
class CostTracker:
    def __init__(self, cost_table: dict | None = None):
        self.cost_table = cost_table or DEFAULT_COST_TABLE
        self.session_costs: list[CostEntry] = []
    
    def record_usage(self, model: str, prompt_tokens: int, completion_tokens: int) -> CostEntry:
        """Record token usage and calculate cost."""
        pricing = self.cost_table.get(model, self.cost_table["local"])
        cost = (
            prompt_tokens / 1000 * pricing.get("input_per_1k", 0)
            + completion_tokens / 1000 * pricing.get("output_per_1k", 0)
        )
        entry = CostEntry(model, prompt_tokens, completion_tokens, cost)
        self.session_costs.append(entry)
        return entry
    
    def session_total(self) -> float:
        """Total cost for this session."""
        return sum(e.cost for e in self.session_costs)
    
    def breakdown_by_model(self) -> dict[str, float]:
        """Cost grouped by model."""
        ...
    
    def breakdown_by_agent(self) -> dict[str, float]:
        """Cost grouped by agent (if tracking per-agent)."""
        ...
```

---

### 5. Dashboard (TypeScript/React)

**File:** `agentcore/typescript/dashboard/`

**Purpose:** A web-based dashboard for visualizing traces, metrics, logs, and costs. Built with React + TypeScript, communicates with the observability backend via REST API.

**Pages:**

| Page | Description |
|------|-------------|
| **Sessions** | List of agent sessions with filters (status, duration, cost, date range) |
| **Session Detail** | Trace waterfall view: step-by-step agent execution timeline |
| **Metrics** | Time-series charts: token usage, latency, cost, success rate |
| **Tool Analysis** | Tool usage frequency, success rate, average latency |
| **Cost Center** | Cost by model, by agent, by date range |
| **Log Explorer** | Full-text search across logs, filter by level/correlation_id |
| **Configuration** | Cost table, model selection, alert thresholds |

**Key Components:**
- `TraceWaterfall`: Horizontal bar chart showing span hierarchy and duration
- `MetricChart`: Time-series chart with zoom/pan (uses lightweight-charts or recharts)
- `SessionTable`: Sortable, filterable table of recent sessions
- `CostBreakdownChart`: Pie/bar chart of costs by dimension

**API Endpoints (backend):**
```
GET  /api/v1/sessions           # List sessions (paginated, filterable)
GET  /api/v1/sessions/:id       # Session detail + traces
GET  /api/v1/sessions/:id/traces  # Raw trace data
GET  /api/v1/sessions/:id/logs  # Logs for session
GET  /api/v1/metrics            # Aggregated metrics
GET  /api/v1/metrics/history    # Time-series metrics
GET  /api/v1/costs              # Cost breakdown
GET  /api/v1/tools              # Tool usage statistics
```

---

### 6. Local-First Storage

**File:** `agentcore/obs/storage.py`

**Purpose:** Provide local storage for observability data when running without external services (Grafana, Prometheus, etc.). Uses SQLite for structured data, file-based for logs.

**Storage Schema (SQLite):**

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    agent_name TEXT,
    task TEXT,
    status TEXT,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    duration_ms INTEGER,
    total_tokens INTEGER,
    total_cost REAL,
    error TEXT
);

CREATE TABLE spans (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    parent_span_id TEXT,
    name TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_ms INTEGER,
    attributes TEXT,  -- JSON
    status TEXT
);

CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    span_id TEXT,
    tool_name TEXT,
    params TEXT,     -- JSON
    result TEXT,     -- JSON
    duration_ms INTEGER,
    success BOOLEAN,
    error TEXT
);

CREATE TABLE metrics_history (
    name TEXT,
    value REAL,
    labels TEXT,     -- JSON
    timestamp TIMESTAMP
);

CREATE TABLE cost_ledger (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    model_name TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost REAL,
    timestamp TIMESTAMP
);
```

---

## File Structure

```
packages/python/obs/
├── __init__.py
├── tracing.py                # TracingMiddleware, span management
├── metrics.py                # MetricsCollector, Metric types
├── logging.py                # StructuredLogging, LogExporter
├── cost.py                   # CostTracker, CostTable
├── storage.py                # SQLiteStorage, FileStorage
├── exporters/
│   ├── __init__.py
│   ├── console.py            # ConsoleExporter (traces + logs)
│   ├── otlp.py               # OTLPExporter (to Grafana Tempo)
│   ├── prometheus.py         # PrometheusExporter
│   └── sqlite.py             # SQLiteExporter
├── middleware.py             # Agent instrumentation middleware
└── api.py                    # FastAPI server for dashboard backend

packages/typescript/dashboard/
├── package.json
├── src/
│   ├── App.tsx
│   ├── pages/
│   │   ├── Sessions.tsx
│   │   ├── SessionDetail.tsx
│   │   ├── Metrics.tsx
│   │   ├── Tools.tsx
│   │   ├── Costs.tsx
│   │   └── Logs.tsx
│   ├── components/
│   │   ├── TraceWaterfall.tsx
│   │   ├── MetricChart.tsx
│   │   ├── SessionTable.tsx
│   │   └── CostBreakdown.tsx
│   └── api/
│       └── client.ts
└── ...
```
