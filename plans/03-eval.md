# Part 3: `agentcore-eval` — The Evaluation Harness

## Purpose

Evaluation is the most critical and most overlooked component of agentic AI systems. How do you know if your agent is working correctly? How do you catch regressions when you change the prompt or add a new tool? How do you compare different agent configurations?

The evaluation harness provides a systematic framework for testing agent behavior. It supports deterministic replay (same input → same trajectory), trajectory comparison (did the agent take the right path?), LLM-as-judge (is the output high quality?), and regression testing in CI.

## Why Build Your Own Eval Harness

Existing evaluation tools (LangSmith, Weights & Biases Prompts) are great for tracking experiments, but they don't solve the fundamental challenge: **agent evaluations are non-deterministic**. The same input can produce different outputs due to LLM randomness, timing, or external state. The eval harness addresses this with:

1. **Deterministic replay** — capture the seed, temperature, and external state so you can replay the exact same trajectory
2. **Trajectory-aware metrics** — not just "did the output match?" but "did the agent take the right sequence of actions?"
3. **LLM-as-judge** — use a separate LLM to evaluate output quality against a rubric
4. **Regression detection** — compare eval runs to catch regressions automatically

## Architecture

```
EvalSuite
├── EvalCase {input, expected_output, expected_trajectory, tags}
├── EvalRun {case, actual_trajectory, actual_output, metrics}
│
├── TrajectoryRecorder
│   └── Records every step: thought, tool_call, tool_result, reflection
│
├── Metrics
│   ├── ExactMatch / SubsetMatch / SemanticSimilarity
│   ├── ToolCallMatch (correct tool + correct parameters)
│   ├── LLMAsJudge (rubric-based evaluation)
│   └── CustomMetric (user-defined)
│
├── RegressionDetection
│   ├── EvalDiff: compare two runs
│   └── Regression: pass/fail against baseline
│
└── CI Integration
    └── GitHub Actions: run eval on PR, comment results
```

## Component Breakdown

### 1. `EvalSuite` and `EvalCase`

**File:** `agentcore/eval/suite.py`

**Purpose:** Organize evaluation cases into suites. A suite represents a logical grouping of tests (e.g., "calculator agent tests", "web search agent tests", "regression suite"). Each suite can be run independently.

```python
@dataclass
class EvalCase:
    name: str                               # Unique identifier
    input: str | Message | list[Message]    # The test input
    expected_output: str | None = None      # Expected final answer
    expected_trajectory: list[Step] | None = None  # Expected sequence of steps
    expected_tool_calls: list[ToolCallTemplate] | None = None  # Expected tool calls
    rubric: dict[str, float] | None = None  # LLM-as-judge rubric {criterion: weight}
    tags: list[str] = field(default_factory=list)  # Grouping/filtering tags
    metadata: dict = field(default_factory=dict)

@dataclass
class EvalSuite:
    name: str
    description: str
    cases: list[EvalCase]
    config: SuiteConfig  # Agent config to use for all cases (can be overridden per-case)
```

**Expected Trajectory Template:**
```python
@dataclass
class Step:
    step_type: Literal["thought", "tool_call", "tool_result", "reflection", "output"]
    content: str | None = None       # For thought/reflection
    tool_name: str | None = None     # For tool_call
    tool_params: dict | None = None  # For tool_call
    tool_result: Any | None = None   # For tool_result
```

**`ToolCallTemplate` — flexible matching:**
```python
@dataclass
class ToolCallTemplate:
    tool_name: str
    params: dict                       # Exact match or {field: Any} for partial
    params_matcher: Literal["exact", "subset", "type_match"] = "exact"
    min_count: int = 1                 # Must appear at least this many times
    max_count: int | None = None       # Must appear at most this many times
```

---

### 2. `TrajectoryRecorder` — Capturing Every Step

**File:** `agentcore/eval/trajectory.py`

**Purpose:** Instrument the agent loop to record every single step of execution. The recorder is injected as middleware into the agent loop, capturing messages, tool calls, tool results, reflections, and state changes.

```python
class TrajectoryRecorder:
    def record_step(self, step: Step) -> None: ...
    def get_trajectory(self) -> list[Step]: ...
    def replay(self) -> AsyncGenerator[Step, None]: ...
    def serialize(self) -> dict: ...
    
    @classmethod
    def deserialize(cls, data: dict) -> TrajectoryRecorder: ...
```

**Trajectory Data Structure:**
```python
@dataclass
class Trajectory:
    case_name: str
    agent_config: AgentConfig
    steps: list[Step]
    final_output: str | None
    usage: UsageSummary
    duration_ms: float
    error: str | None
    metadata: dict
```

**Deterministic Replay:**
- Record: `random_seed`, `temperature`, `top_p`, and any external state (time if relevant, API results if cached)
- Replay: re-run with same seed, same temperature, same cached API responses
- Used for: debugging, regression testing, demo generation

---

### 3. Evaluation Metrics

**File:** `agentcore/eval/metrics.py`

**Purpose:** Compute scores comparing actual agent output/trajectory against expected behavior. Multiple metric classes that can be composed.

**Metric Types:**

```python
class EvalMetric(ABC):
    @abstractmethod
    async def evaluate(
        self, case: EvalCase, run: EvalRun
    ) -> MetricResult:
        ...

@dataclass
class MetricResult:
    name: str
    score: float           # 0.0 to 1.0
    passed: bool           # score >= threshold
    threshold: float
    details: str           # Human-readable explanation
    breakdown: dict | None = None  # Per-criterion breakdown
```

**Built-in Metrics:**

| Metric | Description | Use Case |
|--------|-------------|----------|
| `ExactMatch` | Output string exactly matches expected | Deterministic tasks |
| `SubsetMatch` | All required info present in output (configurable required phrases) | Information extraction |
| `ToolCallMatch` | Correct tool called with correct parameters | Function-calling agents |
| `SemanticSimilarity` | Embedding cosine similarity between outputs | Open-ended tasks |
| `TrajectoryAlignment` | Sequence of steps matches expected trajectory | Multi-step workflows |
| `TokenEfficiency` | Tokens used vs optimal tokens | Cost optimization |
| `ToolEfficiency` | Tool calls vs optimal number | Architecture optimization |
| `TimeEfficiency` | End-to-end duration | Latency optimization |
| `StuckDetection` | Agent got stuck in a loop | Robustness testing |

**`LLMAsJudge`:**
```python
class LLMAsJudge(EvalMetric):
    def __init__(
        self,
        judge_model: ModelClient,
        rubric: dict[str, float],  # {"factual_accuracy": 0.4, "completeness": 0.3, "clarity": 0.3}
        prompt_template: str = None,
    ):
        ...

    async def evaluate(self, case: EvalCase, run: EvalRun) -> MetricResult:
        prompt = self.build_prompt(
            task=case.input,
            actual_output=run.actual_output,
            rubric=self.rubric,
        )
        response = await self.judge_model.generate(prompt)
        # Parse structured judgment from response
        # Returns: {criterion: score, reasoning: str}
```

---

### 4. `EvalRun` and Results

**File:** `agentcore/eval/runner.py`

**Purpose:** Execute a suite of eval cases against an agent configuration, collect results, and produce a report.

```python
class EvalRunner:
    def __init__(
        self,
        agent_factory: Callable[[], BaseAgent],
        recorder_class: type = TrajectoryRecorder,
        metrics: list[EvalMetric],
    ):
        ...

    async def run_suite(self, suite: EvalSuite) -> EvalReport:
        results = []
        for case in suite.cases:
            agent = self.agent_factory()
            recorder = self.recorder_class()
            agent.instrument(recorder)
            
            try:
                output = await agent.run(case.input)
            except Exception as e:
                results.append(EvalRun(
                    case=case,
                    error=str(e),
                    trajectory=recorder.get_trajectory(),
                ))
                continue
            
            metrics = await asyncio.gather(*[
                metric.evaluate(case, EvalRun(
                    case=case,
                    actual_output=output,
                    trajectory=recorder.get_trajectory(),
                )) for metric in self.metrics
            ])
            
            results.append(EvalRun(
                case=case,
                actual_output=output,
                trajectory=recorder.get_trajectory(),
                metrics=metrics,
            ))
        
        return EvalReport(suite=suite, runs=results)
```

**`EvalReport`:**
```python
@dataclass
class EvalReport:
    suite: EvalSuite
    runs: list[EvalRun]
    
    def summary(self) -> dict:
        """Aggregate: pass_rate, avg_scores per metric, total_duration, etc."""
    
    def by_tag(self, tag: str) -> "EvalReport":
        """Filter runs by tag"""
    
    def regression(self, baseline: "EvalReport") -> "EvalDiff":
        """Compare against baseline"""
    
    def to_markdown(self) -> str:
        """GitHub-flavored markdown report for CI comments"""
```

---

### 5. Regression Detection

**File:** `agentcore/eval/regression.py`

**Purpose:** Compare two eval runs to detect regressions. Used in CI to automatically block PRs that degrade agent performance.

```python
@dataclass
class EvalDiff:
    baseline: EvalReport
    current: EvalReport
    
    def regressions(self, threshold: float = 0.05) -> list[Regression]:
        """Return metrics that regressed beyond threshold"""
    
    def improvements(self) -> list[Improvement]:
        """Return metrics that improved"""
    
    def summary_markdown(self) -> str:
        """Human-readable regression report"""

@dataclass
class Regression:
    case_name: str
    metric_name: str
    baseline_score: float
    current_score: float
    delta: float
```

---

### 6. CI Integration

**File:** `.github/workflows/eval.yml`

**Purpose:** Run the evaluation suite on every PR and push to main. Comment results on the PR. Block merges on regression.

**CI Flow:**
1. On PR: run eval suite against PR changes
2. Compare against baseline (stored from main branch)
3. If regressions found: comment on PR with diff, add failure annotation
4. If passed: comment with summary, add "eval-passed" label

**Baseline Storage:**
- Baseline results stored as artifacts in GitHub Actions
- Keyed by: `{suite_name}_{agent_config_hash}`
- Updated on merge to main

---

## Testing Your Eval Harness

The eval harness itself needs testing. Key tests:

| Test | Description |
|------|-------------|
| `test_exact_match` | Known output → ExactMatch returns 1.0 |
| `test_subset_match` | Output with required info → 1.0; missing info → lower |
| `test_tool_call_match` | Correct tool sequence → 1.0; wrong tool → 0.0 |
| `test_llm_judge_reliability` | Same input evaluated twice → same/similar scores |
| `test_regression_detection` | Deliberately degrade prompt → regression detected |
| `test_deterministic_replay` | Same seed + same inputs → identical trajectory |
| `test_ci_format` | Markdown report correctly formatted |

## Blog Content Angles

- "Testing Non-Deterministic Systems: An Evaluation Harness for LLM Agents"
- "LLM-as-Judge: When, Why, and How to Use It Reliably"
- "Trajectory Matching: Evaluating Agent Behavior Beyond Final Output"
- "Catching Regressions in Agent Prompts: A CI-Capable Eval System"
- "The Eval Pipeline: From Unit Tests to Production Monitoring"

## File Structure

```
packages/python/eval/
├── __init__.py
├── suite.py                  # EvalSuite, EvalCase
├── trajectory.py             # TrajectoryRecorder, Trajectory, Step
├── metrics.py                # EvalMetric ABC + all built-in metrics
├── runner.py                 # EvalRunner, EvalRun, EvalReport
├── regression.py             # EvalDiff, Regression
├── replay.py                 # Deterministic replay utilities
├── llm_judge.py              # LLMAsJudge implementation
├── ci_integration.py         # GitHub Actions helpers
├── visualization.py          # Trajectory visualization (mermaid, text)
└── storage.py                # Baseline storage and retrieval
```
