import {
  Answer,
  AuthUser,
  ConversationDetail,
  ConversationSummary,
  ModelCatalog,
} from '../api/types';

/** A complete answer as the service returns it, with any field overridden. */
export function answerFixture(overrides: Partial<Answer> = {}): Answer {
  return {
    conversation_id: 'c'.repeat(32),
    turn: 1,
    question: 'How many patients have diabetes?',
    answer: 'Eight patients have diabetes. [query 1]',
    structured: true,
    headline: 'Eight patients have diabetes.',
    findings: [{ statement: '8 patients match the diabetes codes.', query_numbers: [1] }],
    definitions_used: [
      {
        name: 'diabetes',
        label: 'Diabetic patient',
        status: 'assumed',
        summary: 'Recorded diabetes diagnosis.',
      },
    ],
    time_window: { months: null, start: null, end: null, description: 'all dates in the data' },
    assumptions: [],
    caveats: ['Small cohort.'],
    queries: [
      {
        number: 1,
        sql: 'SELECT COUNT(*) AS n FROM conditions',
        ok: true,
        row_count: 1,
        elapsed_ms: 3,
        truncated: false,
        error: null,
        columns: ['n'],
        rows: [[8]],
      },
    ],
    issues: {
      any: false,
      unknown_definitions: [],
      missing_query_numbers: [],
      unsupported_findings: [],
      window_not_in_sql: null,
    },
    as_of: '2026-08-16',
    model: 'claude-opus-5',
    elapsed_s: 12.3,
    input_tokens: 1200,
    output_tokens: 150,
    ...overrides,
  };
}

export function summaryFixture(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    id: 'c'.repeat(32),
    title: 'How many patients have diabetes?',
    created_at: '2026-10-13T15:00:00Z',
    updated_at: '2026-10-13T15:01:00Z',
    turns: 1,
    ...overrides,
  };
}

/** A stored conversation with one answered question, with any field overridden. */
export function conversationFixture(
  overrides: Partial<ConversationDetail> = {},
): ConversationDetail {
  return {
    ...summaryFixture(),
    busy: false,
    history: [
      {
        turn: 1,
        question: 'How many patients have diabetes?',
        created_at: '2026-10-13T15:01:00Z',
        answer: answerFixture(),
        steps: [{ kind: 'sql', detail: 'SELECT 1' }],
      },
    ],
    ...overrides,
  };
}

/** The models on offer, as /api/models returns them: the default and a cheap one. */
export function catalogFixture(): ModelCatalog {
  const efforts = ['low', 'medium', 'high', 'xhigh', 'max'] as const;
  return {
    default_model: 'claude-opus-5',
    default_effort: 'high',
    models: [
      {
        id: 'claude-opus-5',
        label: 'Opus 5',
        description: 'The default.',
        input_price: 5,
        output_price: 25,
        efforts: [...efforts],
        default_effort: 'high',
        evaluated: '23 of 23 at high effort',
      },
      {
        id: 'claude-haiku-5-5',
        label: 'Haiku 5.5',
        description: 'The fastest and cheapest.',
        input_price: 0.1,
        output_price: 0.5,
        efforts: ['low', 'medium', 'high'],
        default_effort: 'medium',
        evaluated: null,
      },
    ],
  };
}

/** A signed-in person, with any field overridden. */
export function userFixture(overrides: Partial<AuthUser> = {}): AuthUser {
  return {
    id: 'u'.repeat(32),
    email: 'ann@example.org',
    name: 'Ann Lee',
    role: 'user',
    has_password: true,
    google_linked: false,
    email_verified: true,
    default_model: null,
    default_effort: null,
    ...overrides,
  };
}
