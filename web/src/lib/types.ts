// Shapes returned by the AgentCore HTTP API (see src/agentcore/server/app.py).

export interface Health {
  status: string;
  version: string;
  model: string;
  tools: string[];
  auth: boolean;
}

export interface ModelInfo {
  id: string;
  object: "model";
  created: number;
  owned_by: string;
  default: boolean;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface ChatContext {
  tools: string[];
  system_prompt: "custom" | "default";
  memory_messages: number;
}

export interface TextPart {
  type: "text";
  step?: number;
  content: string;
}

export interface ModelPart {
  type: "model";
  step: number;
  latency_ms: number;
  tokens: number;
  tool_calls: number;
}

export interface ToolPart {
  type: "tool";
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  step: number;
  status: "running" | "ok" | "error";
  output?: string;
  error?: string | null;
  latency_ms?: number;
}

export interface NotePart {
  type: "note";
  step?: number;
  content: string;
}

export type TurnPart = TextPart | ModelPart | ToolPart | NotePart;

export interface UserTurn {
  role: "user";
  content: string;
  ts: number;
}

export interface AssistantTurn {
  role: "assistant";
  content: string;
  parts: TurnPart[];
  model?: string;
  /** running | ok | error | stopped | max_steps | timeout | stuck ... */
  status: string;
  context?: ChatContext;
  trace_id?: string | null;
  usage?: Usage;
  cost_usd?: number;
  steps?: number;
  duration_ms?: number;
  error?: string;
  ts: number;
}

export type Turn = UserTurn | AssistantTurn;

export interface SessionSummary {
  id: string;
  title: string;
  created: number;
  updated: number;
  turns: number;
  busy: boolean;
}

export interface Session extends SessionSummary {
  settings: Record<string, unknown>;
  messages: Turn[];
  memory: unknown;
}

export interface JsonSchema {
  type?: string | string[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: unknown[];
  default?: unknown;
  description?: string;
  anyOf?: JsonSchema[];
  items?: JsonSchema;
  [key: string]: unknown;
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: JsonSchema;
  category?: string;
  timeout?: number | null;
  source: "builtin" | "custom";
  [key: string]: unknown;
}

export interface ToolInvokeResult {
  tool_name: string;
  arguments: Record<string, unknown>;
  success: boolean;
  output: unknown;
  error: string | null;
  error_type?: string | null;
  latency_ms: number;
  attempts: number;
  text: string;
  trace_id: string;
}

export interface ToolStats {
  calls: number;
  errors: number;
  total_ms: number;
}

export interface TraceSummary {
  trace_id: string;
  name: string;
  start_time: number;
  duration_ms: number;
  span_count: number;
  status: "ok" | "error";
  total_tokens: number;
  cost_usd: number;
  attributes: Record<string, unknown>;
  model: string;
  input: string;
  output: string;
  tool_calls: number;
  tool_errors: number;
  error: string | null;
  tools: Record<string, ToolStats>;
  kind?: string;
}

export interface FacetValue {
  value: string | null;
  count: number;
}

export interface HistogramBucket {
  t: number;
  count: number;
  errors: number;
}

export interface TraceStats {
  count: number;
  errors: number;
  p50_ms: number;
  p95_ms: number;
  p90_cost_usd: number;
  p90_tokens: number;
}

export interface ExploreResponse {
  query: { source: string; clauses: unknown[] };
  total: number;
  items: TraceSummary[];
  facets: Record<string, FacetValue[]>;
  histogram: { start: number; end: number; bucket_seconds: number; buckets: HistogramBucket[] };
  window: { since: number | null; until: number | null };
  stats: TraceStats;
}

export interface Span {
  name: string;
  trace_id: string;
  span_id: string;
  parent_id: string | null;
  start_time: number;
  end_time: number | null;
  duration_ms: number;
  status: string;
  error: string | null;
  attributes: Record<string, unknown>;
  events?: unknown[];
}

export interface TraceDetail {
  trace_id: string;
  summary: TraceSummary | null;
  spans: Span[];
}

export interface Kpis {
  runs: number;
  errors: number;
  success_rate: number | null;
  p50_ms: number;
  p95_ms: number;
  tokens: number;
  cost_usd: number;
  tool_calls: number;
}

export interface SeriesPoint {
  t: number;
  runs: number;
  errors: number;
  tokens: number;
  cost_usd: number;
  p50_ms: number;
  p95_ms: number;
}

export interface OverviewResponse {
  range: { days: number; since: number; until: number; bucket_seconds: number };
  kpis: Kpis;
  previous: Kpis | null;
  series: SeriesPoint[];
  top_tools: { name: string; calls: number; errors: number; avg_ms: number; error_rate: number }[];
  models: { model: string; runs: number; tokens: number; cost_usd: number }[];
  recent_errors: { trace_id: string; name: string; error: string | null; start_time: number }[];
}

export interface EvalSummary {
  suite?: string;
  model?: string;
  cases: number;
  passed: number;
  pass_rate: number;
  mean_score: number;
  total_tokens: number;
  duration_ms: number;
  metrics?: Record<string, number>;
}

export interface EvalRunInfo {
  id: string;
  suite: string;
  suite_path: string;
  model: string;
  status: "queued" | "running" | "completed" | "failed";
  total: number;
  done: number;
  passed: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  summary: EvalSummary | null;
  is_baseline?: boolean;
}

export interface EvalSuite {
  path: string;
  dir: string;
  name: string;
  description?: string;
  cases: number;
  tools?: string[];
  model?: string | null;
  tags?: string[];
  case_names?: string[];
  last_run?: EvalRunInfo | null;
  baseline?: string | null;
  error?: string;
}

export interface MetricResult {
  name: string;
  score: number;
  passed: boolean;
  details?: string;
}

export interface TrajectoryStep {
  step: number;
  type: string;
  content?: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  success?: boolean;
}

export interface CaseResult {
  case: string;
  input: string;
  output: string | null;
  passed: boolean;
  score: number;
  metrics: MetricResult[];
  steps: number;
  stop_reason?: string;
  duration_ms: number;
  error?: string | null;
  tags?: string[];
  usage?: Usage;
  trace_id?: string | null;
  trajectory?: { steps: TrajectoryStep[]; output?: string | null };
}

export interface EvalDiff {
  baseline_pass_rate: number;
  current_pass_rate: number;
  new_failures: string[];
  fixed: string[];
  regressions: { case: string; metric: string; baseline: number; current: number; delta: number }[];
  improvements: unknown[];
  new_cases: string[];
  has_regressions: boolean;
}

export interface EvalRunDetail extends EvalRunInfo {
  results: CaseResult[];
  diff: EvalDiff | null;
  baseline: {
    id: string;
    started_at: string;
    model: string;
    summary: EvalSummary;
    cases: Record<string, { passed: boolean; score: number; metrics: Record<string, number> }>;
  } | null;
  elapsed_s: number | null;
}

export interface MatrixCell {
  run_id: string;
  passed: boolean;
  score: number;
  duration_ms?: number;
  steps?: number;
  error?: string | null;
  failing: string[];
  regressed: boolean;
  baseline_regressed: boolean;
}

export interface MatrixRun {
  id: string;
  started_at: string;
  model: string;
  summary: EvalSummary | null;
  is_baseline: boolean;
}

export interface EvalMatrix {
  suite: string;
  baseline: string | null;
  runs: MatrixRun[];
  cases: { case: string; tags: string[]; cells: (MatrixCell | null)[] }[];
  regressions: number;
}

export interface ServerConfig {
  version: string;
  python: string;
  config_file?: string | null;
  model?: string | null;
  default_model: string;
  models: string[];
  tools?: string[] | null;
  tool_modules?: string[];
  enabled_tools: string[];
  custom_tools: string[];
  trace_dir: string;
  state_dir: string;
  workspace?: string;
  eval_dirs: string[];
  server: {
    host?: string;
    port?: number;
    auth_enabled: boolean;
    cors_origins: string[];
    max_body_bytes: number;
  };
}
