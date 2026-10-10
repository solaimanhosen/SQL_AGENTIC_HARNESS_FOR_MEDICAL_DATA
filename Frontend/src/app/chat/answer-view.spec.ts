import { TestBed } from '@angular/core/testing';

import { Answer, QueryRecord, Step } from '../api/types';
import { answerFixture } from '../testing/fixtures';
import { AnswerView } from './answer-view';
import { Exporter, toCsv } from './export';

const FAILED: QueryRecord = {
  number: null,
  sql: 'SELECT ssn FROM patients',
  ok: false,
  row_count: null,
  elapsed_ms: null,
  truncated: false,
  error: 'BlockedColumnError: access to patients.ssn is prohibited',
  columns: [],
  rows: [],
};

function fakeExporter(copies = true) {
  return { save: vi.fn(), saveCsv: vi.fn(), copy: vi.fn(async () => copies) };
}

async function render(
  overrides: Partial<Answer> = {},
  steps: Step[] = [],
  exporter = fakeExporter(),
) {
  TestBed.configureTestingModule({ providers: [{ provide: Exporter, useValue: exporter }] });
  const fixture = TestBed.createComponent(AnswerView);
  fixture.componentRef.setInput('answer', answerFixture(overrides));
  fixture.componentRef.setInput('steps', steps);
  await fixture.whenStable();
  return { fixture, element: fixture.nativeElement as HTMLElement };
}

function text(element: Element | null): string {
  return (element?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

describe('AnswerView', () => {
  it('shows the time window and the as-of date the service computed', async () => {
    const { element } = await render({
      time_window: {
        months: 12,
        start: '2025-08-17',
        end: '2026-08-16',
        description: 'last 12 months (2025-08-17 to 2026-08-16)',
      },
    });
    const facts = [...element.querySelectorAll('.facts div')].map((row) => [
      text(row.querySelector('dt')),
      text(row.querySelector('dd')),
    ]);
    expect(facts).toEqual([
      ['Time window', 'last 12 months (2025-08-17 to 2026-08-16)'],
      ['As-of date', '2026-08-16'],
    ]);
  });

  it('shows each definition with the status from the service records', async () => {
    const { element } = await render({
      definitions_used: [
        { name: 'diabetes', label: 'Diabetic patient', status: 'assumed', summary: 'Diabetes.' },
        { name: 'deceased', label: 'Deceased patient', status: 'confirmed', summary: 'Has died.' },
        { name: 'frail', label: 'frail', status: 'unknown', summary: '' },
      ],
    });
    const items = [...element.querySelectorAll('.definitions li')].map((item) => [
      text(item.querySelector('.label')),
      text(item.querySelector('code')),
      text(item.querySelector('.badge')),
      text(item.querySelector('p')),
    ]);
    expect(items).toEqual([
      ['Diabetic patient', 'diabetes', 'Assumed, not yet confirmed', 'Diabetes.'],
      ['Deceased patient', 'deceased', 'Confirmed', 'Has died.'],
      ['frail', '', 'Not a shared definition', 'The agent chose its own meaning for this term.'],
    ]);
    expect(element.querySelector('.badge.confirmed')?.textContent).toBe('Confirmed');
  });

  it('lists assumptions and caveats, and leaves out an empty section', async () => {
    const { element } = await render({ assumptions: ['Sick means any active condition.'] });
    expect(text(element.querySelector('.assumptions'))).toContain(
      'Sick means any active condition.',
    );
    expect(text(element.querySelector('.caveats'))).toContain('Small cohort.');

    TestBed.resetTestingModule();
    const empty = await render({ caveats: [] });
    expect(empty.element.querySelector('.caveats')).toBeNull();
    expect(empty.element.querySelector('.assumptions')).toBeNull();
  });

  it('keeps the SQL closed until asked, then shows each query that ran', async () => {
    const { fixture, element } = await render();
    const panel = element.querySelector('app-query-list details') as HTMLDetailsElement;
    expect(panel.open).toBe(false);
    expect(text(panel.querySelector('summary'))).toBe('SQL that produced this answer (1)');

    panel.open = true;
    panel.dispatchEvent(new Event('toggle'));
    await fixture.whenStable();
    expect(text(panel.querySelector('.query .head'))).toBe('Query 1 · 1 row in 3 ms');
    expect(panel.querySelector('.query pre')?.textContent).toBe(
      'SELECT COUNT(*) AS n FROM conditions',
    );
  });

  it('opens the SQL at the cited query when a citation is clicked', async () => {
    const second = { ...answerFixture().queries[0], number: 2, sql: 'SELECT 2' };
    const { fixture, element } = await render({
      queries: [answerFixture().queries[0], second],
      findings: [{ statement: 'Two things.', query_numbers: [1, 2] }],
    });
    const citations = element.querySelectorAll<HTMLButtonElement>('button.cite');
    expect([...citations].map(text)).toEqual(['Query 1', 'Query 2']);

    citations[1].click();
    await fixture.whenStable();

    const panel = element.querySelector('app-query-list details') as HTMLDetailsElement;
    expect(panel.open).toBe(true);
    expect(panel.querySelector('.query.lit')?.getAttribute('data-query')).toBe('2');
  });

  it('marks a citation to a query that never ran instead of linking it', async () => {
    const { element } = await render({
      findings: [
        { statement: 'A claim.', query_numbers: [9] },
        { statement: 'Another.', query_numbers: [] },
      ],
    });
    expect(element.querySelector('button.cite')).toBeNull();
    expect([...element.querySelectorAll('.cite.uncited')].map(text)).toEqual([
      'Query 9 did not run',
      'No query cited',
    ]);
  });

  it('shows failed attempts apart from the queries the answer rests on', async () => {
    const { element } = await render({ queries: [answerFixture().queries[0], FAILED] });
    expect(text(element.querySelector('.attempts .head'))).toContain('1 failed attempt.');
    expect(element.querySelector('.attempts pre')?.textContent).toBe('SELECT ssn FROM patients');
    expect(text(element.querySelector('.attempts .error'))).toContain('prohibited');
    expect(text(element.querySelector('.meta'))).toContain('1 query, 1 failed ·');
  });

  it('spells out every traceability warning', async () => {
    const { element } = await render({
      issues: {
        any: true,
        unknown_definitions: ['made_up'],
        missing_query_numbers: [9],
        unsupported_findings: ['12 patients were readmitted.'],
        window_not_in_sql: 'last 12 months is claimed but no query filters on those dates',
      },
    });
    const warnings = [...element.querySelectorAll('.warning li')].map(text);
    expect(warnings).toEqual([
      'Named definitions that do not exist: made_up',
      'Cited query numbers that did not run: 9',
      'Time window not backed by SQL: last 12 months is claimed but no query filters on those dates',
      'No query cited for: 12 patients were readmitted.',
    ]);
  });

  it('shows no warning when the answer checks out', async () => {
    const { element } = await render();
    expect(element.querySelector('.warning')).toBeNull();
  });

  it('shows what the run cost, as the command line does', async () => {
    const { element } = await render({ input_tokens: 19183, output_tokens: 852 });
    expect(text(element.querySelector('.meta'))).toBe(
      '1 query · 12.3s · 19,183 in and 852 out tokens · claude-opus-5',
    );
  });

  it('still shows the SQL for an answer that came back as plain text', async () => {
    const { element } = await render({ structured: false, headline: null, answer: 'Just prose.' });
    expect(element.querySelector('.prose')?.textContent).toBe('Just prose.');
    expect(text(element.querySelector('.warning'))).toContain('plain text');
    expect(element.querySelector('app-query-list details')).not.toBeNull();
    expect(element.querySelector('.facts')).toBeNull();
  });

  it('keeps the steps the agent took, with the SQL of each query', async () => {
    const { element } = await render({}, [
      { kind: 'lookup_definition', detail: 'diabetes' },
      { kind: 'sql', detail: 'SELECT 1' },
      { kind: 'sql_error', detail: 'UnsafeQueryError: nope' },
      { kind: 'sql_result', detail: '1 rows in 3 ms' },
    ]);
    const steps = [...element.querySelectorAll('app-step-log li')].map((item) => [
      text(item.querySelector('span')),
      text(item.querySelector('pre, .detail')),
    ]);
    expect(steps).toEqual([
      ['Looking up the definition of diabetes', ''],
      ['Running a query', 'SELECT 1'],
      ['A query failed, so the agent is correcting it', 'UnsafeQueryError: nope'],
      ['Query finished: 1 rows in 3 ms', ''],
    ]);
    expect(text(element.querySelector('details.panel:not(app-query-list *) summary'))).toBe(
      'Steps the agent took (4)',
    );
  });

  it('renders markup in SQL, definitions, warnings and steps as text', async () => {
    const injected = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    const { element } = await render(
      {
        queries: [
          { ...answerFixture().queries[0], sql: injected },
          { ...FAILED, error: injected },
        ],
        definitions_used: [{ name: 'x', label: injected, status: 'assumed', summary: injected }],
        assumptions: [injected],
        caveats: [injected],
        time_window: { months: null, start: null, end: null, description: injected },
        issues: {
          any: true,
          unknown_definitions: [injected],
          missing_query_numbers: [],
          unsupported_findings: [injected],
          window_not_in_sql: injected,
        },
      },
      [{ kind: 'sql', detail: injected }],
    );
    expect(element.querySelector('img')).toBeNull();
    expect(element.querySelector('script')).toBeNull();
    expect(element.querySelector('.query pre')?.textContent).toBe(injected);
  });

  it('shows the rows each query returned', async () => {
    const { element } = await render({
      queries: [
        {
          ...answerFixture().queries[0],
          columns: ['gender', 'n'],
          rows: [
            ['F', 13],
            ['M', 21],
          ],
          row_count: 2,
        },
      ],
    });
    const rows = [...element.querySelectorAll('app-result-table tbody tr')].map(text);
    expect(rows.length).toBe(2);
    expect(element.querySelector('app-result-table th')?.textContent).toBe('gender');
  });

  it('copies the SQL of a query and says so', async () => {
    const exporter = fakeExporter();
    const { fixture, element } = await render({}, [], exporter);
    const button = element.querySelector('.query .tool') as HTMLButtonElement;
    expect(text(button)).toBe('Copy SQL');

    button.click();
    await fixture.whenStable();
    expect(exporter.copy).toHaveBeenCalledWith('SELECT COUNT(*) AS n FROM conditions');
    expect(text(button)).toBe('Copied');
  });

  it('says when the browser refused the copy', async () => {
    const { fixture, element } = await render({}, [], fakeExporter(false));
    const button = element.querySelector('.query .tool') as HTMLButtonElement;
    button.click();
    await fixture.whenStable();
    expect(text(button)).toBe('Copy failed');
  });

  it('downloads the rows of a query as CSV, named after the conversation and query', async () => {
    const exporter = fakeExporter();
    const { element } = await render({}, [], exporter);
    const button = [...element.querySelectorAll<HTMLButtonElement>('.query .tool')].find(
      (item) => text(item) === 'Download rows (CSV)',
    )!;
    button.click();
    expect(exporter.saveCsv).toHaveBeenCalledWith('cccccccc-turn1-query1.csv', toCsv(['n'], [[8]]));
  });

  it('downloads the whole answer as JSON', async () => {
    const exporter = fakeExporter();
    const { element } = await render({}, [], exporter);
    (element.querySelector('.foot .tool') as HTMLButtonElement).click();
    const [name, body, type] = exporter.save.mock.calls[0];
    expect(name).toBe('cccccccc-turn1-answer.json');
    expect(type).toBe('application/json');
    expect(JSON.parse(body)).toEqual(answerFixture());
  });

  it('offers no rows or CSV for a failed attempt', async () => {
    const { element } = await render({ queries: [FAILED] });
    expect(element.querySelector('app-result-table')).toBeNull();
    expect(element.querySelector('.attempts .tool')).toBeNull();
  });
});
