// The shapes the backend service returns. They mirror the Pydantic models in
// Backend/sql_agent/service.py, and the live OpenAPI document at /docs is the reference.

export type DefinitionStatus = 'confirmed' | 'assumed' | 'unknown';

export interface Finding {
  statement: string;
  query_numbers: number[];
}

export interface DefinitionUsed {
  name: string;
  label: string;
  status: DefinitionStatus;
  summary: string;
}

export interface TimeWindow {
  months: number | null;
  start: string | null;
  end: string | null;
  description: string;
}

export interface QueryRecord {
  number: number | null;
  sql: string;
  ok: boolean;
  row_count: number | null;
  elapsed_ms: number | null;
  truncated: boolean;
  error: string | null;
  columns: string[];
  rows: unknown[][];
}

export interface AnswerIssues {
  any: boolean;
  unknown_definitions: string[];
  missing_query_numbers: number[];
  unsupported_findings: string[];
  window_not_in_sql: string | null;
}

export interface Answer {
  conversation_id: string;
  turn: number;
  question: string;
  answer: string;
  structured: boolean;
  headline: string | null;
  findings: Finding[];
  definitions_used: DefinitionUsed[];
  time_window: TimeWindow | null;
  assumptions: string[];
  caveats: string[];
  queries: QueryRecord[];
  issues: AnswerIssues;
  as_of: string;
  model: string;
  elapsed_s: number;
  input_tokens: number;
  output_tokens: number;
}

export interface Health {
  status: 'ok' | 'degraded';
  database: boolean;
  tables: number;
  model: string;
  as_of: string;
}

export type StepKind = 'sql' | 'sql_result' | 'sql_error' | 'describe_table' | 'lookup_definition';

export interface Step {
  kind: StepKind;
  detail: string;
}

/** One event from /api/ask/stream, in the order the service sends them. */
export type StreamEvent =
  | { type: 'conversation'; conversationId: string; turn: number }
  | { type: 'step'; step: Step }
  | { type: 'answer'; answer: Answer };
