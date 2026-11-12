# Part 1: `agentcore-runtime` — The Agent Loop

## Purpose

The runtime is the heart of AgentCore. It defines the fundamental execution model: how an agent perceives input, plans a course of action, executes tools, observes results, and reflects to improve. This is the ReAct (Reasoning and Acting) loop, built from scratch without any framework.

## Architecture Overview

```
User Input
    │
    ▼
┌─────────────────────────────────────┐
│         ModelClient                 │
│  (Ollama / OpenAI / vLLM / etc.)    │
└────────────┬────────────────────────┘
             │ generate()
             ▼
┌─────────────────────────────────────┐
│         Agent Loop (ReAct)          │
│                                     │
│  ┌─────────┐  ┌──────────┐         │
│  │  Plan   │→ │   Act    │         │
│  └─────────┘  └────┬─────┘         │
│                    │ tool_call()    │
│                    ▼                │
│  ┌─────────┐  ┌──────────┐         │
│  │ Reflect │← │ Observe  │         │
│  └─────────┘  └──────────┘         │
│                                     │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│         Memory Systems              │
│  ShortTerm / SlidingWindow /        │
│  Summarizing / LongTerm (Vector)    │
└─────────────────────────────────────┘
```

## Component Breakdown

### 1. `ModelClient` — The LLM Abstraction Layer

**File:** `agentcore/runtime/model_client.py` (and per-provider files)

**Purpose:** Abstract away the differences between LLM providers (Ollama, OpenAI, vLLM, etc.) behind a common interface. Every provider exposes a REST API (or Python binding), but they differ in request/response formats, streaming behavior, rate limits, and pricing.

**Interface:**

```python
class ModelClient(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> ChatResponse:
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[StreamEvent, None]:
        ...

    @abstractmethod
    async def count_tokens(self, messages: list[Message]) -> int:
        ...
```

**`ChatResponse`** contains:
- `message`: The assistant's response (`Message` with role, content, tool_calls)
- `usage`: `{prompt_tokens, completion_tokens, total_tokens}`
- `model`: The model identifier used
- `latency_ms`: Time to first token (or full response time)

**`StreamEvent`** — a tagged union:
- `TokenEvent(content: str)` — a single token
- `ToolCallEvent(tool_call: ToolCall)` — a tool call decision (may arrive before tokens finish)
- `DoneEvent(usage: Usage)` — stream complete

**Implementations:**

| Provider | Class | Backend | Key Details |
|----------|-------|---------|-------------|
| Ollama | `OllamaClient` | Ollama REST API | `http://localhost:11434/api/chat`, streaming via SSE |
| OpenAI | `OpenAIClient` | OpenAI Python SDK | Compatible with any OpenAI-proxy (Groq, Together, etc.) |
| vLLM | `VLLMClient` | vLLM `--api` endpoint | OpenAI-compatible, optimized for local GPU |

**Key Design Decisions:**

- **Streaming-first design.** Even non-streaming calls go through the streaming path internally, just buffered. This ensures consistency and makes it easy to add streaming later.
- **Automatic retry with exponential backoff.** Transient failures (rate limits, 5xx) are retried up to `max_retries` times with jitter.
- **Token counting.** Each client handles token counting differently. Ollama doesn't expose token counts in the streaming API, so we implement a local fallback using the `tiktoken` library or a custom BPE tokenizer when the provider doesn't return counts.
- **Tool calling normalization.** OpenAI and Ollama have similar tool-calling formats. vLLM may differ. The client normalizes tool calls into a standard `ToolCall(name, parameters, id)` structure regardless of provider.

**Blog Content Angles:**
- "Abstracting LLM Providers: Why and How"
- "The Streaming Architecture: Transformers, Async Generators, and SSE"
- "Token Counting: Accuracy, Performance, and Provider Differences"

---

### 2. `Agent` — The ReAct Loop

**File:** `agentcore/runtime/agent.py`

**Purpose:** Implement the fundamental agent execution cycle: given a task, the agent repeatedly decides what to do (plan), executes tools (act), processes results (observe), and decides if more work is needed (reflect).

**The ReAct Loop Pseudocode:**

```
async def run(task: str) -> AgentResult:
    context = AgentContext(task=task)

    while context.should_continue():
        # Plan: decide next action(s)
        response = await model.generate(
            messages=context.messages,
            tools=context.available_tools
        )

        if response.has_tool_calls:
            # Act: execute tools in parallel
            results = await asyncio.gather(*[
                execute_tool(tc) for tc in response.tool_calls
            ])

            # Observe: add results to context
            for tc, result in zip(response.tool_calls, results):
                context.add_tool_result(tc, result)

            # Reflect: agent may reflect on results
            if context.should_reflect():
                reflection = await model.generate(
                    messages=context.reflection_prompt()
                )
                context.add_reflection(reflection)
        else:
            # Final answer
            context.final_answer = response.content
            break

    return context.final_result()
```

**`AgentContext`** — carries all state through execution:
- `task`: The original user task
- `messages`: Full message history (system prompt, user, assistant, tool results)
- `available_tools`: ToolRegistry with tools available to this agent
- `iteration`: Current loop iteration count
- `max_iterations`: Hard limit (default 15) to prevent infinite loops
- `token_budget`: Total token budget for this session
- `tokens_used`: Accumulated token usage
- `tool_results`: Log of all tool executions
- `metadata`: Custom metadata (session_id, user_id, tags)

**Agent Configuration:**

```python
@dataclass
class AgentConfig:
    system_prompt: str  # System prompt that defines agent behavior
    model_client: ModelClient  # The LLM client
    tools: ToolRegistry  # Available tools
    memory: MemorySystem  # Memory backend
    max_iterations: int = 15
    max_tokens_per_response: int = 2048
    temperature: float = 0.0
    should_reflect: bool = True
    reflection_frequency: int = 3  # Reflect every N iterations
    streaming: bool = False
    timeout_seconds: int = 300
```

**Key Design Decisions:**

- **Parallel tool execution.** If the model calls multiple tools, they execute concurrently (via `asyncio.gather`). This requires careful handling of dependencies (tools that depend on other tools' outputs must be called sequentially).
- **Self-reflection.** Periodically (or when context.detects_stuck()), the agent generates a reflection: "What have I done so far? What's still missing? Should I change my approach?" This is added as a special reflection message.
- **Stuck detection.** If the agent repeats the same tool call with the same parameters, or the last N iterations produced no tangible progress, the agent is considered stuck and a reflection+re-plan is forced.
- **Streaming through the loop.** When streaming is enabled, the `run()` method yields `StreamEvent` objects so callers can stream tokens to the user in real-time while the agent continues processing.

**Blog Content Angles:**
- "Building a ReAct Loop from Scratch: Plan → Act → Observe → Reflect"
- "Parallel Tool Execution in Agent Systems: Promise All vs Sequential"
- "Detecting and Handling Stuck Agents: Self-Reflection and Recovery"
- "The Infinite Loop Problem: Safeguards for Autonomous Agents"

---

### 3. Memory Systems

**File:** `agentcore/runtime/memory.py`

**Purpose:** Provide agents with multiple tiers of memory, from simple conversation buffers to sophisticated vector-backed long-term storage. Memory is what separates a stateless LLM call from a stateful agent.

**Architecture:**

```
MemorySystem
├── ShortTermMemory      # Last N messages, within token budget
├── SlidingWindowMemory  # Keep last K turns, drop oldest
├── SummarizingMemory    # Periodically summarize older context
└── LongTermMemory       # Vector-backed, retrieve relevant history
```

**`ShortTermMemory`:**
- Stores messages in a `deque` with a maximum token budget
- When budget is exceeded, removes oldest messages first
- Implements `add_message()`, `get_messages()`, `clear()`, `token_count()`
- Configurable: `max_tokens`, `max_messages`

**`SlidingWindowMemory`:**
- Keeps the last N conversational turns (a turn = user message + assistant response)
- When a new turn is added and the window is full, the oldest turn is evicted
- More intuitive than raw token counting: you know exactly how many exchanges are remembered

**`SummarizingMemory`:**
- When the token budget is about to be exceeded, generates a summary of the conversation so far
- Stores: `{summary: str, messages_summarized: int, timestamp: datetime}`
- The summary replaces the summarized messages in context
- Configurable: `summary_frequency` (every N turns), `summary_model` (can be a faster/cheaper model)
- Challenge: summary must preserve task-critical details. We use a structured prompt that asks the model to extract: (a) user's core objective, (b) constraints discovered, (c) partial results obtained, (d) pending sub-tasks.

**`LongTermMemory`:**
- Stores memories as vector embeddings in a vector database
- On each step, the agent may choose to: (a) store an important fact, (b) retrieve relevant past memories
- Memory format: `{id, content, embedding, timestamp, importance_score, metadata}`
- Importance scoring: the agent self-evaluates how important each fact is (1-10 scale). High-importance memories are never summarised away.
- Retrieval: nearest neighbor search on the query embedding, filtered by relevance threshold

**Memory Combinator:**
- `HybridMemory`: combines short-term + long-term
  - Short-term: last N messages (within token budget)
  - Long-term: top-K relevant memories retrieved at each step
  - Memories are injected as a special `system` message: "Relevant past information:\n{memories}"

**Memory Serialization:**
- `save(path) / load(path)`: serialize memory state to JSON/Parquet
- Enables: session persistence, replay, debugging
- Format preserves: all messages, summaries, long-term memories, metadata

**Blog Content Angles:**
- "Memory Systems for Agents: Beyond ConversationBufferWindowMemory"
- "Summarizing Memory: When to Summarize and What to Keep"
- "Long-Term Memory with Vector Search: A Practical Implementation"
- "The Importance Score: Teaching Agents What Matters"

---

### 4. Context Management

**File:** `agentcore/runtime/context.py`

**Purpose:** Manage the model's context window — the finite token budget that constrains what the agent can "see" at each step. This is one of the most complex and underappreciated challenges in agent systems.

**Components:**

**`TokenCounter`:**
- Counts tokens in messages using the appropriate tokenizer for the active model
- Maintains a mapping of model → tokenizer for automatic selection
- Falls back to character-count approximation when no tokenizer is available

**`ContextManager`:**
- Maintains a running total of tokens used in the current context
- Allocates token budget across: `[system_prompt, memories, conversation_history, tool_definitions, pending_output]`
- Provides `fit_messages(messages: list[Message], budget: int) → list[Message]` that applies truncation strategy to fit within budget

**Truncation Strategies:**
1. `DropOldest`: remove messages from the beginning of history (oldest first, except system prompt)
2. `SummarizeWindow`: summarize oldest N messages into a single short summary
3. `DropLowestRelevance`: use embedding similarity to drop messages least relevant to current query
4. `StructuredCompression`: compress verbose tool outputs by extracting only key information

**`TokenBudget` allocation:**
```python
@dataclass
class TokenBudget:
    system_prompt: int = 1024
    conversation_history: int = 4096
    tool_definitions: int = 2048
    memories: int = 1024
    pending_output: int = 2048
    total: int = 8192  # Sum of above
```

**Dynamic Budget Allocation:**
- If the model response consistently includes many tool calls, increase `tool_definitions` budget
- If the conversation is long, shift budget from `pending_output` to `conversation_history`
- Budget reallocation triggers are: token overflow, user preference, detected truncation quality loss

**Context Streaming:**
- When streaming, the token budget allocation is continuously monitored
- If the agent tries to generate a very long response that would exceed the budget, the `ContextManager` can inject a "Please wrap up" signal

**Blog Content Angles:**
- "Context Management: The Hidden Complexity of Agent Systems"
- "Dynamic Token Budget Allocation: Balancing System Prompts, History, and Tools"
- "Truncation Strategies Compared: When to Drop, Summarize, or Compress"
- "Why 128K Context Windows Don't Solve Your Problems"

---

## Testing Strategy

| Test Type | What It Covers |
|-----------|----------------|
| Unit tests | Each memory strategy independently |
| Mock LLM tests | Agent loop with mocked `ModelClient` — verify tool call ordering, loop termination, error handling |
| Integration tests | Agent loop with Ollama (Llama 3.1 8B) — simple tasks (calculator, search) |
| Context tests | Token budget enforcement, truncation correctness, memory isolation between sessions |
| Stress tests | Long conversations (100+ turns), large tool definitions, continuous streaming |

## File Structure

```
packages/python/runtime/
├── __init__.py              # Public API exports
├── agent.py                 # Agent class, ReAct loop, AgentConfig
├── agent_context.py         # AgentContext: state container
├── model_client.py          # ModelClient ABC
├── clients/
│   ├── __init__.py
│   ├── ollama.py            # OllamaClient
│   ├── openai.py            # OpenAIClient
│   └── vllm.py              # VLLMClient
├── memory.py                # MemorySystem ABC + implementations
├── context.py               # ContextManager, TokenCounter, TokenBudget
├── truncation.py            # Truncation strategies
├── streaming.py             # StreamEvent types, AsyncGenerator helpers
├── errors.py                # Runtime-specific errors (TokenBudgetExceeded, LoopTimeout, etc.)
└── serialization.py         # Memory serialization helpers
```
