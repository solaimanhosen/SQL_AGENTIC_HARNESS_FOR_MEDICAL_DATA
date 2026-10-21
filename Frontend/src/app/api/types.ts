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

/** What an analytics tool computed. Every figure in it was computed by the service. */
export interface AnalysisInfo {
  tool: 'summarize' | 'trend' | 'compare_groups';
  /** A short description, such as "trend by month over 5,571 rows". */
  label: string;
  parameters: Record<string, unknown>;
  /** Rows the SQL returned. The query's own rows are the table computed from them. */
  source_rows: number;
  summary: string[];
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
  /** Set when an analytics tool produced this result. Older stored answers lack it. */
  analysis?: AnalysisInfo | null;
}

export interface ChartSeries {
  name: string;
  /** One value per category, in the order of the chart's x. Null is a gap. */
  values: (number | null)[];
}

/** A chart drawn from one query's rows. Only the title was written by the model. */
export interface Chart {
  kind: 'bar' | 'line';
  title: string;
  query_number: number;
  x_label: string;
  y_label: string;
  x: string[];
  series: ChartSeries[];
}

export interface AnswerIssues {
  any: boolean;
  unknown_definitions: string[];
  missing_query_numbers: number[];
  unsupported_findings: string[];
  window_not_in_sql: string | null;
  /** Charts that could not be drawn from the run. Older stored answers lack it. */
  chart_problems?: string[];
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
  /** Older stored answers lack it. */
  charts?: Chart[];
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

export type StepKind =
  'sql' | 'sql_result' | 'sql_error' | 'analysis' | 'describe_table' | 'lookup_definition';

export interface Step {
  kind: StepKind;
  detail: string;
}

/** A stored conversation as the sidebar lists it. */
export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  /** Questions answered in it so far. */
  turns: number;
  /** When it was pinned, or null. Missing from services before pinning existed. */
  pinned_at?: string | null;
}

/** What a PATCH may change. Fields left out stay as they are. */
export interface ConversationChanges {
  title?: string;
  pinned?: boolean;
}

/** One answered question of a stored conversation, as it was sent when it was asked. */
export interface StoredTurn {
  turn: number;
  question: string;
  created_at: string;
  answer: Answer;
  steps: Step[];
}

export interface ConversationDetail extends ConversationSummary {
  /** True while a question is being answered, so its turn is not in `history` yet. */
  busy: boolean;
  history: StoredTurn[];
}

/**
 * The answer while the model is still writing it. It is unchecked text, with no citations,
 * definitions or dates: those arrive only with the complete answer.
 */
export interface Draft {
  headline: string;
  findings: string[];
}

/** One event from /api/ask/stream, in the order the service sends them. */
export type StreamEvent =
  | { type: 'conversation'; conversationId: string; turn: number }
  | { type: 'step'; step: Step }
  | { type: 'draft'; draft: Draft }
  | { type: 'answer'; answer: Answer };
