import { Answer } from '../api/types';

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
