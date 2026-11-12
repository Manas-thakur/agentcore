# Part 2: `agentcore-tools` — The Tool Calling Framework

## Purpose

Tools are how agents interact with the world. They enable agents to run code, query databases, search the web, read files, and call APIs. The tools package provides a complete framework for defining, registering, validating, executing, and sandboxing tools — all from scratch.

The core insight: a tool is simply **a Python function with a well-defined schema**. The framework converts that function into a JSON Schema that the LLM can understand, executes the call when the LLM requests it, and returns the result in a structured format.

## Architecture

```
ToolDefinition (JSON Schema)
    ▲
    │ @tool decorator generates
    │
Python Function ──► ToolRegistry ──► ExecutionEngine
    ▲                                  │
    │                                  ├─ LocalExecutor (direct)
    │                                  ├─ SubprocessExecutor (sandboxed)
    │                                  ├─ DockerExecutor (container sandbox)
    │                                  └─ WasmExecutor (lightweight sandbox)
    │                                  │
    │                                  ▼
    │                           ToolResult {success, output, latency, cost}
    │
    └── After execution, result returned to agent context
```

## Component Breakdown

### 1. `@tool` Decorator — Function to Schema

**File:** `agentcore/tools/decorator.py`

**Purpose:** Convert a Python function into a `ToolDefinition` with an automatically generated JSON Schema. The decorator inspects the function's type annotations, docstring, and default values to build the schema.

**Usage:**

```python
@tool(
    name="calculator",
    description="Evaluate a math expression",
    category="utilities",
    timeout_seconds=10,
)
def calculate(expression: str) -> float:
    """Evaluate a mathematical expression.
    
    Args:
        expression: A mathematical expression string (e.g., "2 + 3 * 4")
    
    Returns:
        The evaluated result as a float
    """
    import ast, operator
    # Safe evaluation using AST (no eval())
    ...
```

**Generated `ToolDefinition`:**
```python
@dataclass
class ToolDefinition:
    name: str                              # Unique tool name
    description: str                       # Human-readable description
    category: str                          # Grouping category
    parameters: JSONSchema                 # OpenAI-compatible JSON Schema
    required_params: list[str]             # Which parameters are required
    returns: JSONSchema | None             # Return value schema (for structured output)
    fn: Callable                           # The actual Python function
    timeout: int = 30                      # Max execution time
    is_async: bool = False                 # Whether the function is async
    metadata: dict = field(default_factory=dict)
```

**Schema Generation Logic:**
- Type annotations → JSON Schema types: `str → string`, `int → integer`, `float → number`, `bool → boolean`, `list → array`, `dict → object`
- Optional typing: `Optional[str]` or `str | None` → not in `required_params`
- Lists with type args: `list[int]` → `array items: integer`
- Pydantic models: recursively generate nested schema
- Union types: `generate oneOf` schema
- Docstring parsing: extract parameter descriptions from Google/Numpy/ReST-style docstrings
- Default values: set as schema `default`, exclude from `required_params`

**Advanced Features:**
- `ToolSchemaOverrides`: manually override parts of the generated schema
- `ToolValidator`: provide custom validation functions that run before execution
- `ToolMiddleware`: pre/post hooks for logging, metrics, auth

**Blog Content Angles:**
- "From Python Function to JSON Schema: Building a Type-Safe Tool Decorator"
- "Docstring Parsing for LLM Tools: Google vs Numpy vs ReST"
- "Handling Complex Types: Pydantic Models, Unions, and Recursive Schemas"

---

### 2. `ToolRegistry` — Tool Discovery and Management

**File:** `agentcore/tools/registry.py`

**Purpose:** A central registry that stores all available tools, provides lookup by name, filtering by category, and returns tool definitions in the format expected by LLM providers.

**Interface:**

```python
class ToolRegistry:
    def register(self, tool: ToolDefinition) -> None: ...
    def register_multiple(self, tools: list[ToolDefinition]) -> None: ...
    
    def get(self, name: str) -> ToolDefinition: ...
    def list(self, category: str | None = None) -> list[ToolDefinition]: ...
    
    def openai_format(self) -> list[dict]: ...
    def ollama_format(self) -> list[dict]: ...
    
    def execute(self, name: str, params: dict) -> ToolResult: ...
    async def execute_async(self, name: str, params: dict) -> ToolResult: ...
    
    def create_subset(self, names: list[str]) -> ToolRegistry: ...
```

**Key Design Decisions:**
- **Format conversion methods.** Different LLM providers expect different JSON Schema formats for tools. The registry provides `openai_format()` and `ollama_format()` that convert internal `ToolDefinition` to the provider-specific format on demand.
- **Subset creation.** `create_subset(names)` returns a new registry with only the specified tools. Useful for per-agent tool restrictions (the Researcher agent gets search tools but not database tools).
- **Lazy registration.** Tools can be registered from entry points or discovered by scanning packages, enabling plugins.

**Provider Format Differences:**

| Provider | Tool Format | Key Difference |
|----------|-------------|----------------|
| OpenAI | `functions` array | `parameters` uses standard JSON Schema |
| Ollama | `tools` array | Similar to OpenAI but with minor differences |
| vLLM | OpenAI-compatible | Same as OpenAI |

---

### 3. `ExecutionEngine` — Running Tools Safely

**File:** `agentcore/tools/execution.py`

**Purpose:** Execute tool calls with proper error handling, timeouts, retries, and rate limiting. Supports multiple execution modes from direct function calls to fully sandboxed execution.

**Execution Flow:**

```
ToolCall(name, params)
    │
    ▼
ExecutionEngine.execute(call)
    │
    ├─ Validate: schema validation, type coercion
    ├─ Rate limit: token bucket check
    ├─ Execute:
    │   ├─ LocalExecutor: direct fn() call
    │   ├─ SubprocessExecutor: run in subprocess
    │   ├─ DockerExecutor: run in ephemeral container
    │   └─ WasmExecutor: run in WASM runtime
    ├─ Timeout: if execution exceeds limit
    ├─ Retry: if transient error and retries configured
    └─ Result: ToolResult {success, output, error, latency, usage}
```

**`ToolResult`:**
```python
@dataclass
class ToolResult:
    success: bool
    output: Any                    # Parsed return value
    error: str | None              # Error message if failed
    tool_name: str                 # Which tool was called
    params: dict                   # Parameters used
    latency_ms: float              # Execution time
    tokens_used: int               # Approximate tokens in output
    metadata: dict                 # Execution metadata (pid, container id, etc.)
```

**Executors:**

| Executor | Use Case | Security | Performance |
|----------|----------|----------|-------------|
| `LocalExecutor` | Trusted tools (calculator, data processing) | None (direct call) | Fastest |
| `SubprocessExecutor` | Python/Shell code execution | Process isolation, resource limits | Medium |
| `DockerExecutor` | High-risk code, multi-tenant | Full container isolation | Slower (container startup) |
| `WasmExecutor` | Sandboxed code, plugins | Capability-based, no syscalls | Fast |

**Sandbox Configuration:**

```python
@dataclass
class SandboxConfig:
    cpu_limit: float = 1.0       # CPU cores
    memory_limit_mb: int = 256   # Memory limit
    disk_limit_mb: int = 100     # Writeable disk limit
    network_access: bool = False # Allow network connections
    allowed_imports: list[str] | None = None  # Whitelist for Python sandbox
    timeout_seconds: int = 30
    tmp_directory: str = "/tmp/agentcore_sandbox/"
```

---

### 4. Error Handling and Retries

**File:** `agentcore/tools/errors.py`

**Error taxonomy:**
- `ToolNotFoundError`: tool name doesn't exist in registry
- `ToolValidationError`: parameters don't match schema
- `ToolExecutionError`: tool raised an exception during execution
- `ToolTimeoutError`: execution exceeded timeout
- `ToolRateLimitError`: rate limit exceeded
- `ToolSandboxViolation`: tool attempted disallowed operation
- `ToolResourceExceeded`: tool exceeded CPU/memory/disk limits

**Retry Policy:**
```python
@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay_ms: float = 1000
    max_delay_ms: float = 30000
    jitter: bool = True
    retryable_errors: list[type] = field(default_factory=lambda: [
        ToolTimeoutError, ToolRateLimitError
    ])
```

---

### 5. Built-in Tool Library

**File:** `agentcore/tools/library/`

**Purpose:** Provide a rich set of built-in tools that agents can use out of the box. Each tool is carefully designed to be safe, well-documented, and configurable.

| Tool | Description | Safety Considerations |
|------|-------------|---------------------|
| `calculator` | Safe expression evaluation using AST | No `eval()` or `exec()`. Only pure math operations. |
| `web_search` | Search the web (DuckDuckGo/Google) | Rate limited. No scraping without permission. |
| `web_scrape` | Fetch and extract content from a URL | Respects `robots.txt`. Limits on page size. |
| `file_read` | Read file content within allowed paths | Path traversal protection. Size limits. |
| `file_write` | Write content to file within workspace | Must be in allowed directories. Overwrite confirmation. |
| `python_repl` | Execute Python code in sandboxed REPL | Subprocess sandbox. No network. Resource limits. |
| `shell` | Execute shell commands | Docker sandbox only. Whitelisted commands. |
| `sql_query` | Read-only SQL query execution | Read-only connection. Query timeout. Row limits. |
| `embedding` | Generate embedding for given text | Uses local embedding model. |

**Blog Content Angles:**
- "Safe Code Execution for LLM Agents: Sandboxing Strategies Compared"
- "Building a Calculator Tool Without eval(): AST-Based Expression Evaluation"
- "Rate Limiting in Multi-Tool Systems: Token Buckets and Fair Scheduling"

---

## File Structure

```
packages/python/tools/
├── __init__.py
├── decorator.py              # @tool decorator
├── schema.py                 # JSON Schema generation from Python types
├── registry.py               # ToolRegistry
├── execution.py              # ExecutionEngine, ToolResult
├── errors.py                 # Error types, RetryPolicy
├── sandbox/
│   ├── __init__.py
│   ├── base.py               # Sandbox ABC
│   ├── subprocess.py         # SubprocessExecutor
│   ├── docker.py             # DockerExecutor
│   └── wasm.py               # WasmExecutor
├── rate_limit.py             # Token bucket, rate limiter
├── validation.py             # Schema validation, type coercion
└── library/
    ├── __init__.py
    ├── calculator.py
    ├── web.py                 # web_search, web_scrape
    ├── filesystem.py          # file_read, file_write
    ├── python_repl.py
    ├── shell.py
    ├── database.py            # sql_query
    └── embedding.py
```
