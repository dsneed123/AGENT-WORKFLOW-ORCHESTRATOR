/** The wire format, mirrored from src/engine/events.py and src/engine/runner.py. */

export type EventKind =
  | "run_started" | "node_started" | "node_output" | "tool_call" | "node_completed"
  | "node_failed" | "run_paused" | "run_resumed" | "run_stopped" | "run_completed" | "heartbeat";

export type NodeStatus = "pending" | "running" | "success" | "failed" | "skipped" | "cancelled";
export type RunStatus = "idle" | "running" | "paused" | "failed" | "completed" | "stopped";
export type RunMode = "run" | "test";

export interface Tokens { prompt?: number; completion?: number; total?: number }
export interface Validation { ok: boolean; problems: string[] }
export interface ToolCall { tool: string; args: Record<string, unknown>; result: string; ms?: number | null }

export interface RunEvent {
  type: EventKind;
  run_id: string;
  workflow: string;
  seq: number;
  at: number;
  node: string;
  node_type: string;
  index: number | null;
  mode: string;
  from_node: string;
  nodes: { name: string; type: string; mode: string; disabled?: boolean }[];
  status: string;
  ms: number | null;
  tokens: Tokens;
  metrics: Record<string, number | null>;
  at_node: string;
  text: string;
  bytes: number | null;
  records: number | null;
  model: string;
  validation: Validation | null;
  tool: string;
  args: Record<string, unknown>;
  result: string;
  error: string;
  attempt: number | null;
  retries_left: number | null;
}

export interface NodeState {
  name: string;
  type: string;
  mode: string;
  status: NodeStatus;
  ms: number | null;
  tokens: Tokens;
  model: string;
  input: string;
  output: string;
  error: string;
  tool_calls: ToolCall[];
  validation: Validation | null;
  disabled: boolean;
}

export interface RunState {
  run_id: string;
  workflow: string;
  name: string;
  mode: RunMode;
  status: RunStatus;
  from_node: string;
  started: number;
  finished: number | null;
  ms: number | null;
  tokens: Tokens;
  metrics: Record<string, number | null>;
  error: string;
  seq: number;
  nodes: NodeState[];
}

export interface FlowNode {
  name: string;
  type?: string;
  mode?: string;
  model?: string;
  tools?: string[];
  require_tools?: string[];
  schema?: Record<string, unknown>;
  sink?: string;
  source?: string;
  value?: string;
  path?: string;
  url?: string;
  prompt?: string;
  ref?: string;
  when?: string;
  retry?: number;
  on_error?: string;
  map?: boolean;
  parallel?: number;
  interval?: number;
  wait?: number;
  dedupe?: string;
  verify?: string;
  disabled?: boolean;
  layout?: { x: number; y: number };
  [key: string]: unknown;
}

export interface MetricDecl { key: string; label?: string; agg?: string; format?: string }

export interface Flow {
  folder: string;
  name: string;
  purpose: string;
  alwaysOn: boolean;
  interval: number;
  schedule: string | null;
  metrics: MetricDecl[];
  nodes: FlowNode[];
  problems: string[];
  running: string | null;
  files: string[];
}

export interface RunRecordNode {
  name: string; type: string; mode: string; ms?: number; input?: string; output?: string;
  failed?: boolean; model?: string; tool_calls?: ToolCall[]; skipped?: string; note?: string;
  status?: string; tokens?: Tokens; validation?: Validation | null; error?: string;
}

export interface RunRecord {
  workflow: string; started: string; nodes: RunRecordNode[]; ms?: number; stopped_at?: string;
  run_id?: string; mode?: string; status?: string; tokens?: Tokens;
  metrics?: Record<string, number | null>;
}

export interface MetricLine {
  run_id: string; at: number; workflow: string; name: string; status: string; ms: number;
  tokens: Tokens; values: Record<string, number | null>; records: number; failed_nodes: string[];
}

export interface Summary {
  runs: number; success_rate: number | null; avg_ms: number | null; tokens: number;
}

export interface SystemMetrics {
  runs: number;
  previous?: Summary;
  per_day: { label: string; value: number }[];
  success_rate: number | null;
  avg_ms: number | null;
  tokens: number;
  failures_by_node: { label: string; value: number }[];
  recent: MetricLine[];
  range?: string;
}

export interface DiffNode {
  name: string; status: "added" | "removed" | "modified"; type: string;
  changes?: Record<string, [unknown, unknown]>;
}

export interface Diff {
  nodes: DiffNode[];
  edges: { from: string; to: string; status: "added" | "removed" }[];
  top: Record<string, [unknown, unknown]>;
  counts: { added: number; removed: number; modified: number; edges: number; settings: number };
  same: boolean;
  error?: string;
}

export interface Proposal {
  success: boolean;
  yaml?: string;
  current?: string;
  diff?: Diff;
  warnings?: string[];
  error?: string;
  folder?: string;
  name?: string;
}
