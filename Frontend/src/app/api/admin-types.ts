/** The shapes the admin console's routes return (Backend/sql_agent/admin_routes.py). */

export type RunStatus =
  'running' | 'passed' | 'failed' | 'timed_out' | 'cancelled' | 'error' | 'interrupted';

export interface RunSummary {
  verdict?: string;
  seconds?: number;
  /** From pytest's report, for the test job. */
  passed?: number;
  failures?: number;
  errors?: number;
  skipped?: number;
  failed?: string[];
}

export interface RunRecord {
  id: string;
  job: string;
  status: RunStatus;
  started_by: string;
  started_at: string;
  finished_at: string | null;
  exit_code: number | null;
  choices: Record<string, string>;
  summary: RunSummary;
  /** Only when a single run is fetched. */
  output?: string;
  truncated?: boolean;
}

export interface JobChoice {
  name: string;
  label: string;
  options: string[];
  default: string;
}

export interface JobInfo {
  id: string;
  label: string;
  description: string;
  cost: string;
  paid: boolean;
  enabled: boolean;
  disabled_reason: string | null;
  timeout_seconds: number;
  choices: JobChoice[];
  running: boolean;
  latest: RunRecord | null;
}

export interface AdminOverview {
  service: { started_at: string; uptime_seconds: number };
  database: { ok: boolean; tables: number; as_of: string };
  application_database: { schema_version: number };
  anthropic_key_set: boolean;
  default_model: string;
  default_effort: string;
  google_enabled: boolean;
  registration_open: boolean;
  people: { accounts: number; admins: number; disabled: number };
  conversations: { conversations: number; questions: number };
  budget: {
    day: string;
    running: number;
    max_concurrent_runs: number;
    spent_today: number;
    reserved_today: number;
    daily_token_budget: number;
  };
  latest_checks: Record<string, RunRecord>;
}

export interface RequestDay {
  day: string;
  requests: number;
  errors: number;
  refused: number;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface UsageBucket {
  questions: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
}

export interface AdminMetrics {
  days: number;
  requests: {
    days: RequestDay[];
    total: number;
    errors: number;
    refused: number;
    p50_ms: number | null;
    p95_ms: number | null;
    refusals: Record<string, number>;
  };
  runs: {
    days: (UsageBucket & { day: string })[];
    by_model: (UsageBucket & { model: string; label: string })[];
    by_user: (UsageBucket & { user_id: string; email?: string | null })[];
    questions: number;
    estimated_cost_usd: number;
  };
  logs: { requests: boolean; runs: boolean };
}

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: 'user' | 'admin';
  disabled: boolean;
  has_password: boolean;
  google_linked: boolean;
  created_at: string;
  last_seen_at: string | null;
  conversations: number;
  questions_this_month: number;
}
