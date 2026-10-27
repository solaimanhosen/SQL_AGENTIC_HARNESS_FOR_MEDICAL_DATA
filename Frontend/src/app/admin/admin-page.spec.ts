import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { AgentApi } from '../api/agent-api';
import { AdminMetrics, AdminOverview, AdminUser, JobInfo, RunRecord } from '../api/admin-types';
import { AuthUser } from '../api/types';
import { provideAppRouter } from '../app.config';
import { catalogFixture, userFixture } from '../testing/fixtures';
import { AdminApi, RunEvent } from './admin-api';
import { duration, millis } from './format';
import { monitoringCharts } from './monitoring-section';

const ADMIN = userFixture({
  id: 'a'.repeat(32),
  email: 'admin@example.org',
  name: 'Ada Admin',
  role: 'admin',
});

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: '0123456789abcdef',
    job: 'tests',
    status: 'passed',
    started_by: ADMIN.id,
    started_at: '2026-10-22T01:00:00Z',
    finished_at: '2026-10-22T01:00:20Z',
    exit_code: 0,
    choices: {},
    summary: { verdict: '519 passed, 0 failed, 3 skipped', seconds: 19.8 },
    ...overrides,
  };
}

function job(id: string, overrides: Partial<JobInfo> = {}): JobInfo {
  return {
    id,
    label:
      id === 'tests'
        ? 'Unit tests'
        : id === 'connections'
          ? 'Setup and connections'
          : 'Evaluation, live',
    description: `The ${id} job.`,
    cost: id === 'tests' ? 'Free' : 'A fraction of a cent',
    paid: id !== 'tests',
    enabled: true,
    disabled_reason: null,
    timeout_seconds: 600,
    choices: [],
    running: false,
    latest: null,
    ...overrides,
  };
}

const OVERVIEW: AdminOverview = {
  service: { started_at: '2026-10-22T00:00:00Z', uptime_seconds: 3725 },
  database: { ok: true, tables: 18, as_of: '2026-08-16' },
  application_database: { schema_version: 5 },
  anthropic_key_set: true,
  default_model: 'claude-opus-5',
  default_effort: 'high',
  google_enabled: false,
  email_enabled: false,
  registration_open: true,
  people: { accounts: 3, admins: 1, disabled: 1 },
  conversations: { conversations: 12, questions: 4 },
  budget: {
    day: '2026-10-22',
    running: 1,
    max_concurrent_runs: 4,
    spent_today: 1_000_000,
    reserved_today: 60_000,
    daily_token_budget: 5_000_000,
  },
  latest_checks: {
    tests: run(),
    security: run({
      id: 'fedcba9876543210',
      job: 'security',
      status: 'failed',
      summary: { verdict: '77 of 78 behaved as expected.' },
    }),
  },
};

const METRICS: AdminMetrics = {
  days: 2,
  requests: {
    days: [
      { day: '2026-10-21', requests: 10, errors: 0, refused: 1, p50_ms: 20, p95_ms: 200 },
      { day: '2026-10-22', requests: 5, errors: 1, refused: 0, p50_ms: 30, p95_ms: 2400 },
    ],
    total: 15,
    errors: 1,
    refused: 1,
    p50_ms: 25,
    p95_ms: 2400,
    refusals: { unauthenticated: 1 },
  },
  runs: {
    days: [
      {
        day: '2026-10-21',
        questions: 2,
        input_tokens: 30_000,
        output_tokens: 600,
        estimated_cost_usd: 0.17,
      },
      { day: '2026-10-22', questions: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 },
    ],
    by_model: [
      {
        model: 'claude-opus-5',
        label: 'Opus 5',
        questions: 2,
        input_tokens: 30_000,
        output_tokens: 600,
        estimated_cost_usd: 0.17,
      },
    ],
    by_user: [
      {
        user_id: ADMIN.id,
        email: 'admin@example.org',
        questions: 2,
        input_tokens: 30_000,
        output_tokens: 600,
        estimated_cost_usd: 0.17,
      },
    ],
    questions: 2,
    estimated_cost_usd: 0.17,
  },
  logs: { requests: true, runs: true },
};

const PEOPLE: AdminUser[] = [
  {
    id: ADMIN.id,
    email: ADMIN.email,
    name: ADMIN.name,
    role: 'admin',
    disabled: false,
    has_password: true,
    google_linked: false,
    created_at: '2026-10-01T00:00:00Z',
    last_seen_at: '2026-10-22T01:00:00Z',
    conversations: 12,
    questions_this_month: 40,
  },
  {
    id: 'b'.repeat(32),
    email: 'bo@example.org',
    name: '',
    role: 'user',
    disabled: false,
    has_password: true,
    google_linked: true,
    created_at: '2026-10-05T00:00:00Z',
    last_seen_at: null,
    conversations: 0,
    questions_this_month: 0,
  },
];

function fakes(user: AuthUser = ADMIN) {
  const api = {
    signedOut: signal(0),
    me: vi.fn(async () => user),
    authConfig: vi.fn(async () => ({ registration_open: true, google_enabled: false })),
    logout: vi.fn(async () => undefined),
    models: vi.fn(async () => catalogFixture()),
    conversations: vi.fn(async () => []),
    health: vi.fn(async () => ({
      status: 'ok',
      database: true,
      tables: 18,
      model: 'm',
      as_of: '2026-08-16',
    })),
  };
  let jobs = [job('tests', { latest: run() }), job('connections')];
  const admin = {
    overview: vi.fn(async () => OVERVIEW),
    metrics: vi.fn(async (_days: number) => METRICS),
    jobs: vi.fn(async () => jobs),
    runs: vi.fn(async () => [run()]),
    run: vi.fn(async (_id: string) => run({ output: 'line one\n<b>not bold</b>' })),
    startRun: vi.fn(async (id: string, _choices: Record<string, string>) => {
      jobs = jobs.map((item) => (item.id === id ? { ...item, running: true } : item));
      return run({
        id: '1111111111111111',
        job: id,
        status: 'running',
        finished_at: null,
        summary: {},
      });
    }),
    cancelRun: vi.fn(async () => ({ cancelling: true })),
    follow: vi.fn(async function* (_id: string): AsyncGenerator<RunEvent> {
      yield { type: 'line', text: 'collected 519 items' };
      yield { type: 'line', text: '<img src=x onerror=alert(1)>' };
      jobs = jobs.map((item) => ({ ...item, running: false }));
      yield {
        type: 'done',
        run: run({
          id: '1111111111111111',
          status: 'failed',
          summary: {
            verdict: '518 passed, 1 failed, 0 skipped',
            failed: ['tests.test_x::test_y'],
            seconds: 21,
          },
        }),
      };
    }),
    users: vi.fn(async () => PEOPLE),
    changeUser: vi.fn(async (id: string, changes: object) => ({ id, ...changes })),
    resetPassword: vi.fn(async () => ({ temporary_password: 'Tmp-Pass-123456' })),
    settings: vi.fn(async () => ({ registration_open: true })),
    changeSettings: vi.fn(async (open: boolean) => ({ registration_open: open })),
  };
  return { api, admin };
}

async function open(url: string, user: AuthUser = ADMIN) {
  const { api, admin } = fakes(user);
  TestBed.configureTestingModule({
    providers: [
      { provide: AgentApi, useValue: api },
      { provide: AdminApi, useValue: admin },
      provideAppRouter(),
    ],
  });
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(url);
  await settle(harness);
  return { harness, page: harness.routeNativeElement as HTMLElement, admin };
}

async function settle(harness: RouterTestingHarness) {
  for (let i = 0; i < 4; i++) {
    await harness.fixture.whenStable();
  }
}

/** Press the confirm button of the dialog that is open. */
async function confirmDialog(harness: RouterTestingHarness) {
  await settle(harness);
  (document.querySelector('app-confirm-dialog .confirm') as HTMLButtonElement).click();
  await settle(harness);
}

const address = () => TestBed.inject(Router).url;
const texts = (root: ParentNode, selector: string) =>
  [...root.querySelectorAll(selector)].map((item) => item.textContent?.trim());

describe('reaching the admin console', () => {
  it('is for admins only', async () => {
    await open('/admin', userFixture());
    expect(address()).toBe('/');
  });

  it('shows the admin item in the avatar menu only to admins', async () => {
    const { harness, page } = await open('/admin');
    (page.querySelector('app-profile-menu button') as HTMLButtonElement).click();
    await settle(harness);
    expect(texts(document, '.profile .menu-item')).toEqual([
      'Account settings',
      'Admin console',
      'Sign out',
    ]);
  });

  it('opens on the overview, with its sections in the address', async () => {
    const { harness, page } = await open('/admin');
    expect(texts(page, '.tab')).toEqual(['Overview', 'Checks', 'Monitoring', 'People', 'Settings']);
    await harness.navigateByUrl('/admin?tab=people');
    await settle(harness);
    expect(page.querySelector('.tab[aria-current=page]')?.textContent?.trim()).toBe('People');
  });
});

describe('the overview', () => {
  it('shows the state of each part, the budget and the latest checks', async () => {
    const { page } = await open('/admin');
    const tiles = texts(page, '.tile .name');
    expect(tiles).toEqual([
      'Patient database',
      'Anthropic API key',
      'Sign-in',
      'Service',
      'People',
      'Conversations',
    ]);
    expect(page.querySelector('.tile .big')?.textContent?.trim()).toBe('1h 2m');
    expect(page.querySelector('[role=meter]')?.getAttribute('aria-valuenow')).toBe('1060000');
    expect(texts(page, '.checks .check-name')).toContain('Security catalogue');
    expect(page.querySelector('.checks .state.bad')?.textContent?.trim()).toBe('Failed');
  });
});

describe('checks', () => {
  it('runs a free check and shows its output as text, then its verdict and failures', async () => {
    const { harness, page, admin } = await open('/admin?tab=checks');
    const run = page.querySelector('.job .run') as HTMLButtonElement;
    run.click();
    await settle(harness);
    expect(admin.startRun).toHaveBeenCalledWith('tests', {});
    expect(page.querySelector('.log')?.textContent).toBe(
      'collected 519 items\n<img src=x onerror=alert(1)>',
    );
    expect(page.querySelector('.log img')).toBeNull();
    expect(page.querySelector('.verdict')?.textContent?.trim()).toBe(
      '518 passed, 1 failed, 0 skipped',
    );
    expect(texts(page, '.failed li')).toEqual(['tests.test_x::test_y']);
  });

  it('asks before a check that costs money, and starts nothing if cancelled', async () => {
    const { harness, page, admin } = await open('/admin?tab=checks');
    const paid = page.querySelectorAll<HTMLButtonElement>('.job .run')[1];
    paid.click();
    await settle(harness);
    expect(document.querySelector('app-confirm-dialog p')?.textContent).toContain(
      'costs money: A fraction of a cent',
    );
    (document.querySelector('app-confirm-dialog .secondary') as HTMLButtonElement).click();
    await settle(harness);
    expect(admin.startRun).not.toHaveBeenCalled();

    paid.click();
    await confirmDialog(harness);
    expect(admin.startRun).toHaveBeenCalledWith('connections', {});
  });

  it("shows a past run's kept output from the history", async () => {
    const { harness, page } = await open('/admin?tab=checks');
    expect(texts(page, 'tbody td:nth-child(5)')).toEqual(['You']);
    (page.querySelector('tbody .tool') as HTMLButtonElement).click();
    await settle(harness);
    expect(page.querySelector('.log')?.textContent).toBe('line one\n<b>not bold</b>');
    expect(page.querySelector('.log b')).toBeNull();
  });
});

describe('monitoring', () => {
  it('draws four daily charts from the logs, citing no query, and switches the period', async () => {
    const { harness, page, admin } = await open('/admin?tab=monitoring');
    expect(texts(page, 'app-chart-view .title')).toEqual([
      'Requests per day',
      'Response time per day (ms)',
      'Questions answered per day',
      'Estimated model cost per day (USD)',
    ]);
    expect(page.querySelector('app-chart-view .cite')).toBeNull();
    expect(texts(page, '.figure')).toEqual(['15', '1', '1', '2.4 s', '2', '$0.17']);
    const period = page.querySelector('#period') as HTMLSelectElement;
    period.value = '30';
    period.dispatchEvent(new Event('change'));
    await settle(harness);
    expect(admin.metrics).toHaveBeenLastCalledWith(30);
  });

  it('builds each chart from the right figures', () => {
    const [requests, times, questions] = monitoringCharts(METRICS);
    expect(requests.x).toEqual(['10-21', '10-22']);
    expect(requests.series.map((series) => series.values)).toEqual([
      [10, 5],
      [1, 0],
      [0, 1],
    ]);
    expect(times.series[1].values).toEqual([200, 2400]);
    expect(questions.series[0].values).toEqual([2, 0]);
  });
});

describe('people', () => {
  it('lists accounts, finds one, and keeps your own row out of reach', async () => {
    const { harness, page } = await open('/admin?tab=people');
    expect(texts(page, 'tbody .name')).toEqual(['Ada Admin', 'bo@example.org']);
    (page.querySelector('tbody tr:first-child button') as HTMLButtonElement).click();
    await settle(harness);
    expect(document.querySelector('.menu .menu-label')?.textContent).toContain('This is you');
    expect(texts(document, '.menu .menu-item')).toEqual(['Set a temporary password']);

    const search = page.querySelector('#people-search') as HTMLInputElement;
    search.value = 'BO@';
    search.dispatchEvent(new Event('input'));
    await settle(harness);
    expect(texts(page, 'tbody .name')).toEqual(['bo@example.org']);
  });

  it('makes someone an admin after asking', async () => {
    const { harness, page, admin } = await open('/admin?tab=people');
    (page.querySelector('tbody tr:nth-child(2) button') as HTMLButtonElement).click();
    await settle(harness);
    [...document.querySelectorAll<HTMLButtonElement>('.menu .menu-item')]
      .find((item) => item.textContent?.trim() === 'Make an admin')!
      .click();
    await confirmDialog(harness);
    expect(admin.changeUser).toHaveBeenCalledWith('b'.repeat(32), { role: 'admin' });
  });

  it('shows a temporary password once', async () => {
    const { harness, page, admin } = await open('/admin?tab=people');
    (page.querySelector('tbody tr:nth-child(2) button') as HTMLButtonElement).click();
    await settle(harness);
    [...document.querySelectorAll<HTMLButtonElement>('.menu .menu-item')]
      .find((item) => item.textContent?.trim() === 'Set a temporary password')!
      .click();
    await confirmDialog(harness);
    expect(admin.resetPassword).toHaveBeenCalledWith('b'.repeat(32));
    expect(page.querySelector('.secret')?.textContent).toBe('Tmp-Pass-123456');
    [...page.querySelectorAll<HTMLButtonElement>('.reveal button')]
      .find((item) => item.textContent?.trim() === 'Done')!
      .click();
    await settle(harness);
    expect(page.querySelector('.secret')).toBeNull();
  });
});

describe('settings', () => {
  it('closes registration', async () => {
    const { harness, page, admin } = await open('/admin?tab=settings');
    const toggle = page.querySelector('.switch input') as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    toggle.click();
    await settle(harness);
    expect(admin.changeSettings).toHaveBeenCalledWith(false);
    expect(page.querySelector('.switch + .settings-status')?.textContent?.trim()).toBe(
      'Registration is closed.',
    );
  });
});

describe('formatting', () => {
  it('reads durations and times the way people say them', () => {
    expect(duration(12.4)).toBe('12s');
    expect(duration(245)).toBe('4m 05s');
    expect(duration(3725)).toBe('1h 2m');
    expect(duration(null)).toBe('–');
    expect(millis(180)).toBe('180 ms');
    expect(millis(2400)).toBe('2.4 s');
  });
});
