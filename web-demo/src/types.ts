// Shapes of the orchestrator artefacts (orchestrator/out/*.json). Only the
// fields the UI reads are typed.

export interface Hazard {
  severity: "error" | "warning" | "info";
  code: string;
  line: number;
  message: string;
  unit?: string;
}

export interface SymbolInfo {
  name: string;
  type: string;
  typing: "explicit" | "implicit";
  role: string;
  dims: string[] | null;
  intent: string | null;
  value: string | null;
  rust_type: string | null;
}

export interface Goto {
  line: number;
  label: number;
  kind: string;
  target_line: number | null;
  direction: string;
}

export interface SpecUnit {
  name: string;
  kind: string;
  line_start: number;
  line_end: number;
  signature: string;
  args: SymbolInfo[];
  includes: string[];
  implicit_rules: string[];
  symbols: SymbolInfo[];
  common_blocks: { name: string; line: number; members: string[] }[];
  calls: { name: string; line: number; args: string[]; valid: boolean }[];
  labels: Record<string, number>;
  gotos: Goto[];
  do_loops: { line: number; var: string; label: number | null }[];
  hazards: Hazard[];
  statement_count: number;
  acceptance: string[];
}

export interface Spec {
  schema: string;
  source: {
    path: string;
    sha256: string;
    bytes: number;
    lines: number;
    line_endings: string;
    code_lines: number;
    comment_lines: number;
  };
  units: SpecUnit[];
  call_graph: Record<string, string[]>;
  schedule: string[];
  file_hazards: Hazard[];
  summary: {
    units: number;
    gotos: number;
    backward_gotos: number;
    common_blocks: number;
    hazards: Record<string, number>;
  };
}

export interface Step {
  seq: number;
  state: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  status: "ok" | "failed" | "skipped";
  summary: string;
  details: Record<string, unknown>;
}

export interface GateCheck {
  check: string;
  cmd: string;
  ok: boolean;
  duration_ms: number;
  metrics: Record<string, unknown>;
  output_tail: string;
}

export interface Counterexample {
  attempt: number;
  routine: string;
  entry: string;
  rust: number;
  oracle: number;
  tol: number;
  inputs: Record<string, number[]>;
  property: string | null;
  evaluations: number | null;
  minimal_input: string | null;
}

export interface Heal {
  attempt: number;
  max_attempts: number;
  applied: boolean;
  strategy: string;
  rationale: string;
  file: string | null;
  line: number | null;
  before: string | null;
  after: string | null;
  diff?: string;
  matches_reference_translation?: boolean | null;
  evidence: Record<string, unknown>;
}

export interface PrInfo {
  mode: string;
  state?: string;
  number?: number;
  html_url?: string;
  draft?: boolean;
  title?: string;
  head?: string;
  head_sha?: string;
  base?: string;
  updated_at?: string;
  payload: { title: string; body: string; base: string; head: string | null };
}

export interface RunLog {
  schema: string;
  run_id: string;
  mode: string;
  started_at: string;
  finished_at: string | null;
  outcome: "success" | "blocked" | null;
  graph: { states: string[]; edges: [string, string][] };
  toolchain: Record<string, string | null>;
  target: Spec["source"];
  scope: Record<string, { status: string; rust?: string; reason?: string }>;
  transitions: { seq: number; from: string | null; to: string; at: string; reason: string }[];
  steps: Step[];
  planted_bug: {
    routine: string;
    file: string;
    line: number;
    before: string;
    after: string;
    description: string;
  } | null;
  counterexamples: Counterexample[];
  heals: Heal[];
  gate_runs: { attempt: number; ok: boolean; checks: GateCheck[] }[];
  parity: {
    total_cases: number;
    properties: Record<string, number>;
    cases_per_routine: Record<string, number>;
    bit_identical: { test: string; identical: number; total: number }[];
    tests_passed: number;
    routines: string[];
  } | null;
  pr: PrInfo | null;
  blocker: { state: string; message: string } | null;
}
