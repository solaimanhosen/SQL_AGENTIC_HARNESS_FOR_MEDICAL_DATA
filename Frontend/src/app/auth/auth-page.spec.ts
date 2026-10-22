import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { AgentApi, ApiError } from '../api/agent-api';
import { AuthUser } from '../api/types';
import { provideAppRouter } from '../app.config';
import { ChatPage } from '../chat/chat-page';
import { catalogFixture, userFixture } from '../testing/fixtures';
import { initials } from '../ui/profile-menu';

function fakeApi({ signedIn = false, google = false, registration = true } = {}) {
  let user: AuthUser | null = signedIn ? userFixture() : null;
  return {
    signedOut: signal(0),
    me: vi.fn(async () => {
      if (!user) {
        throw new ApiError(401, 'unauthenticated', 'Sign in to continue.');
      }
      return user;
    }),
    authConfig: vi.fn(async () => ({ registration_open: registration, google_enabled: google })),
    login: vi.fn(async (email: string, password: string) => {
      if (password !== 'the right password') {
        throw new ApiError(401, 'invalid_credentials', 'The email or password is not correct.');
      }
      user = userFixture({ email });
      return user;
    }),
    register: vi.fn(async (email: string, _password: string, name: string) => {
      user = userFixture({ email, name });
      return user;
    }),
    logout: vi.fn(async () => undefined),
    health: vi.fn(async () => ({
      status: 'ok',
      database: true,
      tables: 18,
      model: 'm',
      as_of: '2026-08-16',
    })),
    conversations: vi.fn(async () => []),
    conversation: vi.fn(),
    models: vi.fn(async () => catalogFixture()),
  };
}

async function open(api: ReturnType<typeof fakeApi>, url: string) {
  TestBed.configureTestingModule({
    providers: [{ provide: AgentApi, useValue: api }, provideAppRouter()],
  });
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(url);
  await harness.fixture.whenStable();
  return harness;
}

const address = () => TestBed.inject(Router).url;
const type = (element: Element, selector: string, value: string) => {
  const input = element.querySelector(selector) as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event('input'));
};

describe('signing in', () => {
  it('sends someone signed out from the chat to sign in, remembering where they were', async () => {
    await open(fakeApi(), '/c/' + 'a'.repeat(32));
    expect(address()).toBe('/login?next=%2Fc%2F' + 'a'.repeat(32));
  });

  it('signs in and returns to where the person was going', async () => {
    const api = fakeApi();
    const harness = await open(api, '/login?next=%2Fc%2F' + 'a'.repeat(32));
    const page = harness.routeNativeElement!;
    expect(page.querySelector('h1')?.textContent).toBe('Sign in');

    type(page, '#email', 'ann@example.org');
    type(page, '#password', 'the right password');
    await harness.fixture.whenStable();
    (page.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
    await vi.waitFor(async () => {
      await harness.fixture.whenStable();
      expect(address()).toBe('/c/' + 'a'.repeat(32));
    });
    expect(api.login).toHaveBeenCalledWith('ann@example.org', 'the right password');
  });

  it('says a wrong password plainly and clears the box', async () => {
    const harness = await open(fakeApi(), '/login');
    const page = harness.routeNativeElement!;
    type(page, '#email', 'ann@example.org');
    type(page, '#password', 'wrong');
    await harness.fixture.whenStable();
    (page.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
    await vi.waitFor(async () => {
      await harness.fixture.whenStable();
      expect(page.querySelector('[role=alert]')?.textContent?.trim()).toBe(
        'The email or password is not correct.',
      );
    });
    expect((page.querySelector('#password') as HTMLInputElement).value).toBe('');
    expect(address()).toBe('/login');
  });

  it('never follows a "next" that leaves the application', async () => {
    const harness = await open(fakeApi(), '/login?next=%2F%2Fevil.example');
    const page = harness.routeNativeElement!;
    type(page, '#email', 'ann@example.org');
    type(page, '#password', 'the right password');
    await harness.fixture.whenStable();
    (page.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
    await vi.waitFor(async () => {
      await harness.fixture.whenStable();
      expect(address()).toBe('/');
    });
  });

  it('shows the message for a code from a Google sign-in, as text', async () => {
    const harness = await open(fakeApi({ google: true }), '/login?error=link_required');
    const page = harness.routeNativeElement!;
    expect(page.querySelector('[role=alert]')?.textContent).toContain(
      'Sign in with your password, then connect Google',
    );
    const google = page.querySelector('a.google') as HTMLAnchorElement;
    expect(google.getAttribute('href')).toBe('/api/auth/google/start?next=%2F');
  });

  it('offers Google only when the service has it, and sign-up only when it is open', async () => {
    const harness = await open(fakeApi({ google: false, registration: false }), '/login');
    const page = harness.routeNativeElement!;
    expect(page.querySelector('a.google')).toBeNull();
    expect(page.querySelector('.switch a')).toBeNull();
  });

  it('skips the sign-in page for someone already signed in', async () => {
    await open(fakeApi({ signedIn: true }), '/login');
    expect(address()).toBe('/');
  });
});

describe('creating an account', () => {
  it('needs a 12-character password before it can be sent, then signs the person in', async () => {
    const api = fakeApi();
    const harness = await open(api, '/register');
    const page = harness.routeNativeElement!;
    expect(page.querySelector('h1')?.textContent).toBe('Create your account');
    expect(page.querySelector('#password-hint')?.textContent).toBe('At least 12 characters.');
    const submit = page.querySelector('button.submit') as HTMLButtonElement;

    type(page, '#name', 'Bo Ray');
    type(page, '#email', 'bo@example.org');
    type(page, '#password', 'elevenchars');
    await harness.fixture.whenStable();
    expect(submit.disabled).toBe(true);

    type(page, '#password', 'twelve chars');
    await harness.fixture.whenStable();
    expect(submit.disabled).toBe(false);
    (page.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
    await vi.waitFor(async () => {
      await harness.fixture.whenStable();
      expect(address()).toBe('/');
    });
    expect(api.register).toHaveBeenCalledWith('bo@example.org', 'twelve chars', 'Bo Ray');
    expect(harness.routeDebugElement?.componentInstance).toBeInstanceOf(ChatPage);
  });
});

describe('initials', () => {
  it('takes the first and last names, or the email', () => {
    expect(initials('Ann Lee', 'a@x.org')).toBe('AL');
    expect(initials('  ann   marie lee ', 'a@x.org')).toBe('AL');
    expect(initials('Cher', 'c@x.org')).toBe('C');
    expect(initials('', 'bo@x.org')).toBe('B');
  });
});
