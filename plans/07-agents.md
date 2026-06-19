# Part 7: `agentcore-agents` — Specialized Agents & A2A Protocol

## Purpose

A single general-purpose agent is powerful, but specialized agents — each optimized for a specific type of task — are far more effective when working together. This package provides specialized agent implementations (Researcher, Coder, Reviewer, Planner) and a communication protocol (A2A — Agent-to-Agent) for multi-agent collaboration.

## Architecture

```
Agent Base Class
├── ResearcherAgent    — Searches, reads, extracts, synthesizes information
├── CoderAgent         — Writes, debugs, refactors code; generates tests
├── ReviewerAgent      — Evaluates outputs against rubrics; provides feedback
└── PlannerAgent       — Decomposes goals → executable plans with task ordering

A2A Protocol
├── Message: {from, to, type, payload, correlation_id, timestamp}
├── Types: request, response, error, status_update, delegate
├── Routing: direct, broadcast, topic
└── Correlation: link responses to requests across hops
```

## Component Breakdown

### 1. Base Agent Architecture

**File:** `agentcore/agents/base.py`

The specialized agents share a common architecture built on top of the runtime:

```python
class SpecializedAgent(ABC):
    name: str
    description: str
    model_client: ModelClient
    tools: ToolRegistry
    config: AgentConfig
    
    @abstractmethod
    async def run(self, task: str, context: AgentContext | None = None) -> AgentOutput: ...
    
    @abstractmethod
    def system_prompt(self, task: str) -> str: ...
    
    def get_tools(self) -> ToolRegistry:
        """Return tools available to this agent type."""
        ...
    
    async def communicate(self, message: A2AMessage) -> A2AResponse:
        """Handle incoming A2A messages from other agents."""
        ...
```

---

### 2. ResearcherAgent

**File:** `agentcore/agents/researcher.py`

**Purpose:** Answer complex technical questions through thorough, multi-source research. This agent plans a research strategy, executes searches across multiple sources, extracts key information, and synthesizes a structured report with citations.

**System Prompt Strategy:**
```
You are a thorough research agent. Your goal is to answer the user's question 
comprehensively and accurately. Follow this process:

1. ANALYZE: Break the question into sub-questions and identify key concepts.
2. SEARCH: Use web search and document retrieval to find relevant information.
   Search multiple queries to ensure coverage.
3. EXTRACT: For each source, extract the key facts, claims, and data.
4. SYNTHESIZE: Combine information from multiple sources into a coherent answer.
   Note agreements, disagreements, and uncertainties between sources.
5. CITE: Every factual claim must be supported by a source citation.
6. VERIFY: Check for contradictions, outdated info, or unsupported claims.

When you find conflicting information:
- Present both perspectives fairly
- Note the source reliability for each
- Indicate which is more likely correct based on evidence

Always prefer:
- Primary sources over secondary
- Recent information over old (unless historical context is needed)
- Peer-reviewed or official documentation over informal sources
```

**Tools Available:**
- `web_search` — search the web
- `web_scrape` — fetch and extract content from URLs
- `file_read` — read stored documents
- `rag_retrieve` — search the ingested knowledge base
- `calculator` — for numerical analysis

**Research Pipeline (as a Graph):**

```
Parse Query → Plan Research → Execute Searches (parallel) 
→ Read & Extract (parallel per source) → Store in working memory
→ Synthesize → Draft Report → Review → Revise → Output
```

**Output Format:**
```markdown
# Research Report: {topic}

## Summary
{2-3 paragraph executive summary}

## Key Findings
1. {finding} — [Source 1][Source 2]
2. {finding} — [Source 3]

## Detailed Analysis
### Subtopic 1
{analysis with inline citations [1][2]}

### Subtopic 2
{analysis with inline citations [3][4]}

## Sources
[1] {title}, {url}, accessed {date}
[2] {title}, {url}, accessed {date}
...
```

**Handling Uncertainty:**
- Confidence scoring per claim (1-5)
- Explicit uncertainty markers: "This is likely true based on [source] but {alternative} contradicts"
- Source quality assessment: official docs > tech blogs > forums

---

### 3. CoderAgent

**File:** `agentcore/agents/coder.py`

**Purpose:** Write, debug, review, and refactor code. The coder agent plans its approach, generates code, tests it, and iterates until the solution passes all tests.

**System Prompt Strategy:**
```
You are a coding agent specialized in software development. Follow this process:

1. UNDERSTAND: Analyze the requirements. Identify inputs, outputs, edge cases.
2. PLAN: Design the solution architecture. Choose appropriate patterns.
3. IMPLEMENT: Write clean, well-structured code with proper error handling.
4. TEST: Write and run tests to verify correctness.
5. DEBUG: If tests fail, analyze the error, fix the code, re-run.
6. REVIEW: Check for edge cases, performance issues, and code quality.
7. REFINE: Improve based on self-review.

Code quality standards:
- Type hints for all functions
- Docstrings for public APIs
- Error handling with specific exception types
- No hardcoded values (use constants or config)
- Follow PEP 8 (Python) or language-specific best practices
```

**Tools Available:**
- `python_repl` — execute Python code in sandbox
- `shell` — run shell commands in Docker sandbox
- `file_read` — read existing code files
- `file_write` — write code to files
- `web_search` — search for docs, Stack Overflow, etc.
- `rag_retrieve` — search code documentation

**Code Writing Pipeline:**

```
Parse Requirements → Plan Implementation
    → Write Code → Write Tests → Run Tests
    → [If tests fail] Debug → Fix → Run Tests
    → [If tests pass] Review → Refactor → Output
```

**Self-Debugging Loop:**
1. Run the code with test input
2. Capture stdout, stderr, return code
3. If error: analyze traceback, identify the bug, fix, re-run
4. If wrong output: compare actual vs expected, identify logic error, fix, re-run
5. Loop until tests pass or max iterations reached

---

### 4. ReviewerAgent

**File:** `agentcore/agents/reviewer.py`

**Purpose:** Review outputs of other agents (or the same agent's self-review). Evaluates against rubrics for factual accuracy, completeness, code quality, clarity, and adherence to instructions.

**System Prompt Strategy:**
```
You are a meticulous reviewer. Your job is to evaluate the quality of outputs 
produced by other AI agents. Be thorough, constructive, and specific.

Evaluation dimensions:
1. FACTUAL ACCURACY: Are all claims supported by the cited sources? 
   Are there any contradictions or unsupported statements?
2. COMPLETENESS: Does the output address all parts of the original request?
   Are there any gaps or missing information?
3. CLARITY: Is the output well-structured and easy to understand?
4. CORRECTNESS (for code): Does the code work? Are there bugs?
5. SAFETY: Are there any harmful, biased, or unsafe outputs?

For each issue found:
- Specify the exact location (paragraph/section/line)
- Explain why it's an issue
- Suggest a concrete improvement
- Rate severity: critical / major / minor / suggestion

Final verdict: pass / pass_with_changes / fail
```

**Review Output:**
```python
@dataclass
class ReviewResult:
    verdict: Literal["pass", "pass_with_changes", "fail"]
    scores: dict[str, float]           # Dimension → score (0.0-1.0)
    issues: list[ReviewIssue]          # List of issues found
    summary: str                       # Overall assessment
    suggestions: list[str]             # Improvement suggestions

@dataclass
class ReviewIssue:
    location: str                      # Where the issue is
    description: str                   # What's wrong
    suggestion: str                    # How to fix
    severity: Literal["critical", "major", "minor", "suggestion"]
```

---

### 5. PlannerAgent

**File:** `agentcore/agents/planner.py`

**Purpose:** Decompose high-level goals into structured, executable plans. The planner analyzes the goal, identifies sub-tasks, determines dependencies, assigns appropriate agents/tools, and produces a step-by-step execution plan.

**System Prompt Strategy:**
```
You are a planning agent specialized in task decomposition. Given a high-level goal,
you produce a detailed execution plan.

Planning process:
1. ANALYZE GOAL: What exactly needs to be achieved? What are the constraints?
2. IDENTIFY SUB-TASKS: Break the goal into smaller, manageable tasks.
3. DETERMINE DEPENDENCIES: Which tasks depend on others? What can be parallelized?
4. SELECT TOOLS/AGENTS: For each task, what's the best tool or agent to use?
5. ESTIMATE: For each task, estimate complexity (simple/medium/complex).
6. PRODUCE PLAN: Ordered list of tasks with dependencies, tools, and success criteria.
```

**Plan Output:**
```python
@dataclass
class Plan:
    goal: str
    tasks: list[Task]
    estimated_cost: Cost | None
    risks: list[Risk]

@dataclass
class Task:
    id: str
    description: str
    depends_on: list[str]          # Task IDs that must complete first
    assigned_to: str               # Agent name or tool name
    success_criteria: list[str]    # How to verify this task is done
    complexity: Literal["simple", "medium", "complex"]
    estimated_steps: int | None
```

---

### 6. A2A Protocol (Agent-to-Agent)

**File:** `agentcore/agents/a2a.py`

**Purpose:** Define how agents communicate with each other — sending requests, sharing results, delegating tasks, and reporting status.

**Message Format:**
```python
@dataclass
class A2AMessage:
    sender: str                     # Agent name
    recipient: str                  # Agent name or "broadcast"
    message_type: A2AMessageType    # request, response, error, status, delegate
    payload: dict                   # Message content
    correlation_id: str             # For linking responses to requests
    parent_id: str | None = None    # For nested/chain messages
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: float = 300.0      # Message expiry

class A2AMessageType(Enum):
    REQUEST = "request"              # Ask another agent to do something
    RESPONSE = "response"            # Return result from a request
    ERROR = "error"                  # Report error processing a request
    STATUS_UPDATE = "status_update"  # Report progress on long-running task
    DELEGATE = "delegate"            # Pass a subtask to another agent
    QUERY = "query"                  # Ask for information (no side effects)
```

**Routing:**
- `Direct`: `recipient = "coder_agent"` → delivered to that agent
- `Broadcast`: `recipient = "broadcast"` → delivered to all agents
- `Topic`: `recipient = "topic:code_review"` → delivered to agents subscribed to that topic

**Communication Patterns:**

| Pattern | Description | Example |
|---------|-------------|---------|
| Request-Response | Agent A asks Agent B to do work, B responds | Planner → Researcher: "Research topic X" |
| Delegate | Agent A passes sub-task to Agent B with context | Researcher → Coder: "Write a script to scrape Y" |
| Pipeline | A → B → C, each consuming the previous output | Planner → Researcher → Reviewer |
| Broadcast | Agent A informs all agents of something | Any → Broadcast: "User changed requirements" |
| Query | Agent A asks Agent B for information | Coder → Researcher: "What's the latest API for Z?" |
| Escalate | Agent A asks for human intervention | Any → Human: "I'm stuck on task X" |

**Implementation:**
```python
class A2AOrchestrator:
    def __init__(self, agents: dict[str, SpecializedAgent]):
        self.agents = agents
        self.message_queue: asyncio.Queue[A2AMessage]
        self.callbacks: dict[str, list[Callable]]  # correlation_id → callbacks
    
    async def send(self, message: A2AMessage) -> None:
        """Send message to recipient (or broadcast)."""
    
    async def request(
        self, recipient: str, payload: dict, timeout: float = 30.0
    ) -> A2AResponse:
        """Send request and wait for response."""
    
    async def process_message(self, message: A2AMessage) -> A2AResponse:
        """Deliver message to appropriate agent and return response."""
```

---

## Multi-Agent Collaboration Patterns

### Pattern 1: Manager-Worker

```
User → PlannerAgent (manager)
    ├─→ ResearcherAgent (worker 1)
    ├─→ CoderAgent (worker 2)
    └─→ ReviewerAgent (worker 3)

Planner decomposes task, assigns sub-tasks to workers, 
collects results, and synthesizes final output.
```

### Pattern 2: Pipeline

```
ResearcherAgent → CoderAgent → ReviewerAgent
```

### Pattern 3: Peer Review

```
CoderAgent writes code → ReviewerAgent reviews
    → [if fail] CoderAgent fixes → ReviewerAgent re-reviews
    → [if pass] Output
```

### Pattern 4: Consensus

```
Multiple ResearcherAgents (with different tools/perspectives)
    → Each researches independently
    → ReviewerAgent compares and synthesizes
```

---

## File Structure

```
packages/python/agents/
├── __init__.py
├── base.py                    # SpecializedAgent ABC
├── researcher.py              # ResearcherAgent
├── coder.py                   # CoderAgent
├── reviewer.py                # ReviewerAgent
├── planner.py                 # PlannerAgent
├── a2a.py                     # A2A protocol: Message, Orchestrator
├── patterns.py                # Multi-agent collaboration patterns
├── registry.py                # AgentRegistry
└── tests/
    ├── test_researcher.py
    ├── test_coder.py
    ├── test_reviewer.py
    ├── test_planner.py
    └── test_a2a.py
```
