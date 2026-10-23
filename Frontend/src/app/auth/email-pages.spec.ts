import { Location } from '@angular/common';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { AgentApi, ApiError } from '../api/agent-api';
import { AuthUser } from '../api/types';
import { provideAppRouter } from '../app.config';
import { catalogFixture, userFixture } from '../testing/fixtures';
import { Toasts } from '../ui/toasts';

const TOKEN = 'abcdefghijklmnopqrstuvwxyz012345';

function fakeApi({ email = true, signedIn = false, user = userFixture() } = {}) {
  let current: AuthUser | null = signedIn ? user : null;
  return {
    signedOut: signal(0),
    me: vi.fn(async () => {
      if (!current) {
        throw new ApiError(401, 'unauthenticated', 'Sign in to continue.');
      }
      return current;
    }),
    authConfig: vi.fn(async () => ({
      registration_open: true,
      google_enabled: false,
      email_enabled: email,
    })),
    forgotPassword: vi.fn(async (_email: string) => undefined),
    resetPassword: vi.fn(async (token: string, _password: string) => {
      if (token !== TOKEN) {
        throw new ApiError(
          400,
          'invalid_link',
          'This link has expired or was already used. Ask for a new one.',
        );
      }
      current = null; // every session of the account ended
    }),
    verifyEmail: vi.fn(async (token: string) => {
      if (token !== TOKEN) {
        throw new ApiError(
          400,
          'invalid_link',
          'This link has expired or was already used. Ask for a new one.',
        );
      }
      if (current) {
        current = { ...current, email_verified: true };
      }
    }),
    sendVerification: vi.fn(async () => undefined),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(async () => undefined),
    health: vi.fn(async () => ({
      status: 'ok',
      database: true,
      tables: 18,
      model: 'm',
      as_of: '2026-08-16',
    })),
    conversations: vi.fn(async () => []),
    models: vi.fn(async () => catalogFixture()),
    sessions: vi.fn(async () => []),
    myUsage: vi.fn(),
  };
}

async function open(api: ReturnType<typeof fakeApi>, url: string, state?: object) {
  TestBed.configureTestingModule({
    providers: [{ provide: AgentApi, useValue: api }, provideAppRouter()],
  });
  const harness = await RouterTestingHarness.create();
  if (state) {
    await TestBed.inject(Router).navigateByUrl(url, { state });
  } else {
    await harness.navigateByUrl(url);
  }
  await settle(harness);
  return { harness, page: () => harness.routeNativeElement as HTMLElement };
}

async function settle(harness: RouterTestingHarness) {
  for (let i = 0; i < 3; i++) {
    await harness.fixture.whenStable();
  }
}

const address = () => TestBed.inject(Router).url;
const type = (page: Element, selector: string, value: string) => {
  const input = page.querySelector(selector) as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event('input'));
};
const submit = (page: Element) =>
  (page.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));

describe('the sign-in page', () => {
  it('offers "Forgot password?" only when the service can send email', async () => {
    const { page } = await open(fakeApi({ email: true }), '/login');
    expect(page().querySelector('.label-row a')?.textContent?.trim()).toBe('Forgot password?');
    TestBed.resetTestingModule();
    const off = await open(fakeApi({ email: false }), '/login');
    expect(off.page().querySelector('.label-row')).toBeNull();
  });

  it('carries the typed email to the reset page', async () => {
    const { harness, page } = await open(fakeApi(), '/login');
    type(page(), '#email', 'ann@example.org');
    await settle(harness);
    (page().querySelector('.label-row a') as HTMLAnchorElement).click();
    await vi.waitFor(async () => {
      await settle(harness);
      expect(address()).toBe('/forgot-password');
    });
    expect((page().querySelector('#email') as HTMLInputElement).value).toBe('ann@example.org');
  });
});

describe('asking for a reset link', () => {
  it('says the same thing whatever the service knows, and suggests the spam folder', async () => {
    const api = fakeApi();
    const { harness, page } = await open(api, '/forgot-password');
    type(page(), '#email', '  ann@example.org ');
    await settle(harness);
    submit(page());
    await vi.waitFor(async () => {
      await settle(harness);
      expect(page().querySelector('.done')?.textContent).toContain(
        'If an account uses ann@example.org, a link to reset its password is on its way.',
      );
    });
    expect(api.forgotPassword).toHaveBeenCalledWith('ann@example.org');
    expect(page().querySelector('form')).toBeNull();
    expect(page().textContent).toContain('check your spam folder');
  });

  it('shows the service’s message when it refuses, such as too many requests', async () => {
    const api = fakeApi();
    api.forgotPassword.mockRejectedValueOnce(
      new ApiError(429, 'too_many_attempts', 'Too many emails asked for.'),
    );
    const { harness, page } = await open(api, '/forgot-password');
    type(page(), '#email', 'ann@example.org');
    await settle(harness);
    submit(page());
    await vi.waitFor(async () => {
      await settle(harness);
      expect(page().querySelector('[role=alert]')?.textContent?.trim()).toBe(
        'Too many emails asked for.',
      );
    });
  });

  it('explains that an administrator resets passwords when email is off', async () => {
    const { page } = await open(fakeApi({ email: false }), '/forgot-password');
    expect(page().querySelector('form')).toBeNull();
    expect(page().querySelector('.lead')?.textContent).toContain('an administrator resets');
  });
});

describe('choosing a new password from a link', () => {
  it('reads the token from the fragment and takes it out of the address', async () => {
    await open(fakeApi(), `/reset-password#token=${TOKEN}`);
    expect(TestBed.inject(Location).path(true)).toBe('/reset-password');
  });

  it('needs the two passwords to match, then sends the person to sign in', async () => {
    const api = fakeApi();
    const { harness, page } = await open(api, `/reset-password#token=${TOKEN}`);
    type(page(), '#password', 'a brand new password');
    type(page(), '#confirm', 'a brand new passwor');
    await settle(harness);
    expect(page().querySelector('#confirm-hint')?.textContent).toContain('not the same');
    expect((page().querySelector('button.submit') as HTMLButtonElement).disabled).toBe(true);

    type(page(), '#confirm', 'a brand new password');
    await settle(harness);
    submit(page());
    await vi.waitFor(async () => {
      await settle(harness);
      expect(address()).toBe('/login');
    });
    expect(api.resetPassword).toHaveBeenCalledWith(TOKEN, 'a brand new password');
    expect(TestBed.inject(Toasts).items()[0].message).toBe(
      'Your password is changed. Sign in with the new one.',
    );
  });

  it('offers a new link when this one has expired', async () => {
    const other = 'zyxwvutsrqponmlkjihgfedcba543210';
    const { harness, page } = await open(fakeApi(), `/reset-password#token=${other}`);
    type(page(), '#password', 'a brand new password');
    type(page(), '#confirm', 'a brand new password');
    await settle(harness);
    submit(page());
    await vi.waitFor(async () => {
      await settle(harness);
      expect(page().querySelector('[role=alert]')?.textContent).toContain('expired');
    });
    expect(page().querySelector('.switch a')?.textContent?.trim()).toBe('Ask for a new link');
    expect(TestBed.inject(Location).path()).toBe('/reset-password');
  });

  it('says so when the link lost its token', async () => {
    const { page } = await open(fakeApi(), '/reset-password');
    expect(page().querySelector('form')).toBeNull();
    expect(page().querySelector('[role=alert]')?.textContent).toContain('incomplete');
  });
});

describe('confirming an email from a link', () => {
  it('confirms, and refreshes the person signed in here', async () => {
    const api = fakeApi({ signedIn: true, user: userFixture({ email_verified: false }) });
    const { harness, page } = await open(api, `/verify-email#token=${TOKEN}`);
    await vi.waitFor(async () => {
      await settle(harness);
      expect(page().querySelector('.done')?.textContent).toContain('Your email is confirmed.');
    });
    expect(api.verifyEmail).toHaveBeenCalledWith(TOKEN);
    expect(page().querySelector('.switch a')?.textContent?.trim()).toBe('Go to your conversations');
    expect(TestBed.inject(Location).path(true)).toBe('/verify-email');
  });

  it('works signed out too, and says when a link has expired', async () => {
    const { harness, page } = await open(
      fakeApi(),
      '/verify-email#token=zyxwvutsrqponmlkjihgfedcba543210',
    );
    await vi.waitFor(async () => {
      await settle(harness);
      expect(page().querySelector('[role=alert]')?.textContent).toContain('expired');
    });
    expect(page().querySelector('.switch a')?.textContent?.trim()).toBe('Sign in');
  });
});

describe('the reminder on the account page', () => {
  it('appears for an unconfirmed email and sends the link again', async () => {
    const api = fakeApi({ signedIn: true, user: userFixture({ email_verified: false }) });
    const { harness, page } = await open(api, '/account');
    const button = page().querySelector('.unverified button') as HTMLButtonElement;
    expect(button.textContent?.trim()).toBe('Send confirmation email');
    button.click();
    await vi.waitFor(async () => {
      await settle(harness);
      expect(page().querySelector('.unverified [role=status]')?.textContent).toContain(
        'Sent to ann@example.org',
      );
    });
    expect(api.sendVerification).toHaveBeenCalledOnce();
  });

  it('is not shown once the email is confirmed, or when email is off', async () => {
    const confirmed = await open(fakeApi({ signedIn: true }), '/account');
    expect(confirmed.page().querySelector('.unverified')).toBeNull();
    TestBed.resetTestingModule();
    const off = await open(
      fakeApi({ signedIn: true, email: false, user: userFixture({ email_verified: false }) }),
      '/account',
    );
    expect(off.page().querySelector('.unverified')).toBeNull();
  });
});
