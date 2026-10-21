import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { AgentApi, ApiError } from '../api/agent-api';
import { AuthUser, MyUsage, SessionInfo } from '../api/types';
import { provideAppRouter } from '../app.config';
import { catalogFixture, userFixture } from '../testing/fixtures';
import { THEME_KEY } from '../ui/theme';
import { describeAgent, isMobileAgent } from './describe-agent';
import { dollars } from './usage-section';

const CHROME_MAC =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
const SAFARI_IPHONE =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';

const SESSIONS: SessionInfo[] = [
  {
    id: 'here',
    created_at: '2026-10-20T10:00:00Z',
    last_used_at: '2026-10-21T10:00:00Z',
    expires_at: '2027-01-18T10:00:00Z',
    user_agent: CHROME_MAC,
    current: true,
  },
  {
    id: 'phone',
    created_at: '2026-10-01T10:00:00Z',
    last_used_at: '2026-10-02T10:00:00Z',
    expires_at: '2026-12-30T10:00:00Z',
    user_agent: SAFARI_IPHONE,
    current: false,
  },
];

const USAGE: MyUsage = {
  day: '2026-10-21',
  today_tokens: 250_000,
  daily_budget: 1_000_000,
  month_start: '2026-10-01',
  questions: 3,
  input_tokens: 50_000,
  output_tokens: 1_000,
  estimated_cost_usd: 0.2519,
  by_model: [
    {
      model: 'claude-opus-5',
      label: 'Opus 5',
      questions: 1,
      input_tokens: 17_000,
      output_tokens: 400,
      estimated_cost_usd: 0.095,
    },
    {
      model: 'claude-haiku-5-5',
      label: 'Haiku 5.5',
      questions: 2,
      input_tokens: 33_000,
      output_tokens: 600,
      estimated_cost_usd: 0.0036,
    },
  ],
};

function fakeApi(user: AuthUser = userFixture(), { google = true } = {}) {
  let current = user;
  return {
    signedOut: signal(0),
    me: vi.fn(async () => current),
    authConfig: vi.fn(async () => ({ registration_open: true, google_enabled: google })),
    logout: vi.fn(async () => undefined),
    models: vi.fn(async () => catalogFixture()),
    updateAccount: vi.fn(async (changes: Partial<AuthUser>) => {
      current = { ...current, ...changes };
      return current;
    }),
    changePassword: vi.fn(async (currentPassword: string | null, _next: string) => {
      if (current.has_password && currentPassword !== 'the old password') {
        throw new ApiError(403, 'wrong_password', 'The current password is not correct.');
      }
      current = { ...current, has_password: true };
    }),
    sessions: vi.fn(async () => SESSIONS),
    revokeSession: vi.fn(async (_id: string) => undefined),
    revokeOtherSessions: vi.fn(async () => 1),
    disconnectGoogle: vi.fn(async () => (current = { ...current, google_linked: false })),
    myUsage: vi.fn(async () => USAGE),
  };
}

async function open(api: ReturnType<typeof fakeApi>, url = '/account') {
  TestBed.configureTestingModule({
    providers: [{ provide: AgentApi, useValue: api }, provideAppRouter()],
  });
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(url);
  await settle(harness);
  return { harness, page: harness.routeNativeElement as HTMLElement };
}

async function settle(harness: RouterTestingHarness) {
  for (let i = 0; i < 3; i++) {
    await harness.fixture.whenStable();
  }
}

const type = (page: Element, selector: string, value: string) => {
  const input = page.querySelector(selector) as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event('input'));
};
const texts = (page: Element, selector: string) =>
  [...page.querySelectorAll(selector)].map((item) => item.textContent?.trim());

describe('the account page', () => {
  it('opens on the profile, with the sections in the address', async () => {
    const { harness, page } = await open(fakeApi());
    expect(texts(page, '.tab')).toEqual(['Profile', 'Security', 'Preferences', 'Usage']);
    expect(page.querySelector('.tab[aria-current=page]')?.textContent?.trim()).toBe('Profile');
    expect((page.querySelector('#profile-email') as HTMLInputElement).value).toBe(
      'ann@example.org',
    );

    await harness.navigateByUrl('/account?tab=usage');
    await settle(harness);
    expect(page.querySelector('.tab[aria-current=page]')?.textContent?.trim()).toBe('Usage');
  });

  it('saves a new name', async () => {
    const api = fakeApi();
    const { harness, page } = await open(api);
    const save = page.querySelector('app-profile-section button') as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    type(page, '#profile-name', '  Ann Marie Lee ');
    await settle(harness);
    (page.querySelector('app-profile-section form') as HTMLFormElement).dispatchEvent(
      new Event('submit'),
    );
    await settle(harness);
    expect(api.updateAccount).toHaveBeenCalledWith({ name: 'Ann Marie Lee' });
    expect(page.querySelector('app-profile-section [role=status]')?.textContent?.trim()).toBe(
      'Saved.',
    );
    expect(page.querySelector('app-profile-menu button')?.getAttribute('aria-label')).toBe(
      'Account: Ann Marie Lee',
    );
  });
});

describe('security', () => {
  it('changes a password only with the current one and two matching new ones', async () => {
    const api = fakeApi();
    const { harness, page } = await open(api, '/account?tab=security');
    const button = () =>
      page.querySelector('app-security-section form button') as HTMLButtonElement;
    type(page, '#current-password', 'wrong');
    type(page, '#new-password', 'a brand new password');
    type(page, '#repeat-password', 'a brand new passworD');
    await settle(harness);
    expect(button().disabled).toBe(true);

    type(page, '#repeat-password', 'a brand new password');
    await settle(harness);
    button().closest('form')!.dispatchEvent(new Event('submit'));
    await settle(harness);
    expect(page.querySelector('app-security-section [role=status]')?.textContent?.trim()).toBe(
      'The current password is not correct.',
    );
    expect((page.querySelector('#new-password') as HTMLInputElement).value).toBe('');

    type(page, '#current-password', 'the old password');
    type(page, '#new-password', 'a brand new password');
    type(page, '#repeat-password', 'a brand new password');
    await settle(harness);
    button().closest('form')!.dispatchEvent(new Event('submit'));
    await settle(harness);
    expect(api.changePassword).toHaveBeenLastCalledWith('the old password', 'a brand new password');
    expect(page.querySelector('app-security-section [role=status]')?.textContent?.trim()).toBe(
      'Password changed.',
    );
  });

  it('lets a Google-only account set its first password, and keeps Google until it has one', async () => {
    const api = fakeApi(userFixture({ has_password: false, google_linked: true }));
    const { page } = await open(api, '/account?tab=security');
    expect(page.querySelector('#password-title')?.textContent?.trim()).toBe('Set a password');
    expect(page.querySelector('#current-password')).toBeNull();
    const disconnect = [...page.querySelectorAll<HTMLButtonElement>('button')].find(
      (button) => button.textContent?.trim() === 'Disconnect Google',
    )!;
    expect(disconnect.disabled).toBe(true);
  });

  it('offers to connect Google, back to this section, when the service has it', async () => {
    const { page } = await open(fakeApi(), '/account?tab=security');
    const link = [...page.querySelectorAll('a')].find(
      (a) => a.textContent?.trim() === 'Connect Google',
    )!;
    expect(link.getAttribute('href')).toBe(
      '/api/auth/google/start?link=true&next=%2Faccount%3Ftab%3Dsecurity',
    );
  });

  it('says so when Google is not set up, and shows a failed connection as text', async () => {
    const { page } = await open(
      fakeApi(userFixture(), { google: false }),
      '/account?tab=security&error=google_in_use',
    );
    expect(page.textContent).toContain('Google sign-in is not set up on this service.');
    expect(page.querySelector('app-security-section [role=alert]')?.textContent?.trim()).toBe(
      'That Google account is already connected to another account.',
    );
  });

  it('lists signed-in devices and signs another one out', async () => {
    const api = fakeApi();
    const { harness, page } = await open(api, '/account?tab=security');
    expect(texts(page, '.sessions .device')).toEqual([
      'Chrome on macOS This device',
      'Safari on iOS',
    ]);
    const signOut = page.querySelector('.sessions li:nth-child(2) button') as HTMLButtonElement;
    expect(page.querySelector('.sessions li:nth-child(1) button')).toBeNull();
    signOut.click();
    await settle(harness);
    expect(api.revokeSession).toHaveBeenCalledWith('phone');
  });
});

describe('preferences', () => {
  it('saves a default model and effort, and new chats start on it', async () => {
    const api = fakeApi();
    const { harness, page } = await open(api, '/account?tab=preferences');
    const model = page.querySelector('#default-model') as HTMLSelectElement;
    expect([...model.options].map((option) => option.textContent?.trim())).toEqual([
      "The service's default",
      'Opus 5 · $5 / $25 per million tokens',
      'Haiku 5.5 · $0.10 / $0.50 per million tokens',
    ]);
    model.value = 'claude-haiku-5-5';
    model.dispatchEvent(new Event('change'));
    await settle(harness);
    const effort = page.querySelector('#default-effort') as HTMLSelectElement;
    expect([...effort.options].map((option) => option.value)).toEqual(['low', 'medium', 'high']);
    effort.value = 'low';
    effort.dispatchEvent(new Event('change'));
    await settle(harness);
    (page.querySelector('app-preferences-section form') as HTMLFormElement).dispatchEvent(
      new Event('submit'),
    );
    await settle(harness);
    expect(api.updateAccount).toHaveBeenCalledWith({
      default_model: 'claude-haiku-5-5',
      default_effort: 'low',
    });
    expect(api.models).toHaveBeenCalledTimes(2);
  });

  it('switches the theme for this browser', async () => {
    localStorage.removeItem(THEME_KEY);
    const { harness, page } = await open(fakeApi(), '/account?tab=preferences');
    const dark = page.querySelector('input[value=dark]') as HTMLInputElement;
    dark.click();
    await settle(harness);
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    localStorage.removeItem(THEME_KEY);
    document.documentElement.removeAttribute('data-theme');
  });
});

describe('usage', () => {
  it('shows today against the budget and this month by model', async () => {
    const { page } = await open(fakeApi(), '/account?tab=usage');
    expect(page.querySelector('#today-title + .settings-lead')?.textContent).toContain(
      '250,000 of 1,000,000 model tokens',
    );
    expect(page.querySelector('[role=meter]')?.getAttribute('aria-valuenow')).toBe('250000');
    expect(page.querySelector('#month-title')?.textContent).toBe('This month, October 2026');
    expect(texts(page, 'tbody tr td:first-child')).toEqual(['Opus 5', 'Haiku 5.5']);
    expect(texts(page, 'tbody tr td:last-child')).toEqual(['$0.10', '$0.0036']);
  });
});

describe('the profile menu', () => {
  it('opens the account settings', async () => {
    const { harness } = await open(fakeApi(), '/account?tab=usage');
    (document.querySelector('app-profile-menu button') as HTMLButtonElement).click();
    await settle(harness);
    const item = [...document.querySelectorAll<HTMLButtonElement>('.profile .menu-item')].find(
      (button) => button.textContent?.trim() === 'Account settings',
    )!;
    item.click();
    await settle(harness);
    expect(TestBed.inject(Router).url).toBe('/account');
  });
});

describe('helpers', () => {
  it('names a device people can recognise', () => {
    expect(describeAgent(CHROME_MAC)).toBe('Chrome on macOS');
    expect(describeAgent(SAFARI_IPHONE)).toBe('Safari on iOS');
    expect(describeAgent('Mozilla/5.0 (Windows NT 10.0) Firefox/131.0')).toBe('Firefox on Windows');
    expect(describeAgent('Mozilla/5.0 (Windows NT 10.0) Chrome/130 Safari/537 Edg/130')).toBe(
      'Edge on Windows',
    );
    expect(describeAgent('curl/8.7.1')).toBe('curl');
    expect(describeAgent('')).toBe('Unknown browser');
    expect(isMobileAgent(SAFARI_IPHONE)).toBe(true);
    expect(isMobileAgent(CHROME_MAC)).toBe(false);
  });

  it('shows small costs with enough places to be read', () => {
    expect(dollars(0)).toBe('$0');
    expect(dollars(0.0019)).toBe('$0.0019');
    expect(dollars(1.234)).toBe('$1.23');
    expect(dollars(null)).toBe('unknown');
  });
});
