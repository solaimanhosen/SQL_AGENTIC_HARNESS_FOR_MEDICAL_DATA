import { Location } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AgentApi, ApiError } from '../api/agent-api';
import { Toasts } from '../ui/toasts';
import { Auth } from './auth';
import { MIN_PASSWORD_CHARS } from './auth-page';
import { AuthShell } from './auth-shell';

const FAILED = 'Something went wrong. Try again.';

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : FAILED;
}

/**
 * The token a link carries after `#token=`. It is in the fragment so it never reaches a
 * server log. Once read, it is taken out of the address, so it does not stay in the history.
 */
function takeToken(route: ActivatedRoute, location: Location): string | null {
  const token = new URLSearchParams(route.snapshot.fragment ?? '').get('token');
  location.replaceState(location.path(false).split('#')[0]);
  return token && /^[A-Za-z0-9_-]{16,200}$/.test(token) ? token : null;
}

/** Ask for a reset link. The page says the same whether or not the account exists. */
@Component({
  selector: 'app-forgot-password-page',
  imports: [AuthShell, RouterLink],
  styleUrl: './auth-form.css',
  template: `
    <app-auth-shell>
      <h1>Reset your password</h1>
      @if (emailOff()) {
        <p class="lead">
          Email is not set up on this service, so an administrator resets forgotten passwords. Ask
          yours for a temporary password.
        </p>
      } @else if (sentTo(); as address) {
        <p class="done" role="status">
          If an account uses {{ address }}, a link to reset its password is on its way. It works for
          30 minutes.
        </p>
        <p class="lead">If nothing arrives in a few minutes, check your spam folder.</p>
      } @else {
        <p class="lead">Enter the email you sign in with, and we will send you a link.</p>
        @if (failure(); as text) {
          <p class="alert" role="alert">{{ text }}</p>
        }
        <form (submit)="submit($event)" novalidate>
          <label for="email">Email</label>
          <input
            id="email"
            class="field"
            type="email"
            autocomplete="email"
            required
            maxlength="254"
            [value]="email()"
            (input)="email.set($any($event.target).value)"
          />
          <button type="submit" class="submit" [disabled]="busy() || !email().trim()">
            {{ busy() ? 'One moment…' : 'Send reset link' }}
          </button>
        </form>
      }
      <p class="switch"><a routerLink="/login">Back to sign in</a></p>
    </app-auth-shell>
  `,
})
export class ForgotPasswordPage implements OnInit {
  private readonly api = inject(AgentApi);
  private readonly auth = inject(Auth);

  /** Carried over from the sign-in page, so it need not be typed again. */
  protected readonly email = signal(initialEmail(inject(Router), inject(Location)));
  protected readonly busy = signal(false);
  protected readonly failure = signal<string | null>(null);
  protected readonly sentTo = signal<string | null>(null);
  protected readonly emailOff = computed(() => this.auth.config()?.email_enabled === false);

  ngOnInit(): void {
    void this.auth.loadConfig();
  }

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    const email = this.email().trim();
    if (!email || this.busy()) {
      return;
    }
    this.busy.set(true);
    this.failure.set(null);
    try {
      await this.api.forgotPassword(email);
      this.sentTo.set(email);
    } catch (error) {
      this.failure.set(messageOf(error));
    } finally {
      this.busy.set(false);
    }
  }
}

/** The email the sign-in page passed along in the navigation's state, if any. */
function initialEmail(router: Router, location: Location): string {
  const state = (router.currentNavigation()?.extras.state ?? location.getState()) as {
    email?: unknown;
  } | null;
  const email = state?.email;
  return typeof email === 'string' ? email.slice(0, 254) : '';
}

/** Choose a new password, from the link in a reset email. */
@Component({
  selector: 'app-reset-password-page',
  imports: [AuthShell, RouterLink],
  styleUrl: './auth-form.css',
  template: `
    <app-auth-shell>
      <h1>Choose a new password</h1>
      @if (!token) {
        <p class="alert" role="alert">
          This link is incomplete. Open the whole link from the email, or ask for a new one.
        </p>
        <p class="switch"><a routerLink="/forgot-password">Ask for a new link</a></p>
      } @else {
        <p class="lead">Every browser signed in to your account is signed out when you save it.</p>
        @if (failure(); as text) {
          <p class="alert" role="alert">{{ text }}</p>
        }
        <form (submit)="submit($event)" novalidate>
          <label for="password">New password</label>
          <input
            id="password"
            class="field"
            type="password"
            autocomplete="new-password"
            required
            maxlength="128"
            aria-describedby="password-hint"
            [value]="password()"
            (input)="password.set($any($event.target).value)"
          />
          <p id="password-hint" class="hint">At least {{ minPassword }} characters.</p>
          <label for="confirm">Type it again</label>
          <input
            id="confirm"
            class="field"
            type="password"
            autocomplete="new-password"
            required
            maxlength="128"
            [attr.aria-invalid]="mismatch() || null"
            [attr.aria-describedby]="mismatch() ? 'confirm-hint' : null"
            [value]="confirm()"
            (input)="confirm.set($any($event.target).value)"
          />
          @if (mismatch()) {
            <p id="confirm-hint" class="hint">The two passwords are not the same yet.</p>
          }
          <button type="submit" class="submit" [disabled]="busy() || !canSubmit()">
            {{ busy() ? 'One moment…' : 'Save password' }}
          </button>
        </form>
        @if (expired()) {
          <p class="switch"><a routerLink="/forgot-password">Ask for a new link</a></p>
        } @else {
          <p class="switch"><a routerLink="/login">Back to sign in</a></p>
        }
      }
    </app-auth-shell>
  `,
})
export class ResetPasswordPage {
  private readonly api = inject(AgentApi);
  private readonly auth = inject(Auth);
  private readonly router = inject(Router);
  private readonly toasts = inject(Toasts);

  protected readonly token = takeToken(inject(ActivatedRoute), inject(Location));
  protected readonly minPassword = MIN_PASSWORD_CHARS;
  protected readonly password = signal('');
  protected readonly confirm = signal('');
  protected readonly busy = signal(false);
  protected readonly failure = signal<string | null>(null);
  protected readonly expired = signal(false);
  protected readonly mismatch = computed(
    () => this.confirm().length > 0 && this.confirm() !== this.password(),
  );
  protected readonly canSubmit = computed(
    () => this.password().length >= MIN_PASSWORD_CHARS && this.confirm() === this.password(),
  );

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    if (!this.token || !this.canSubmit() || this.busy()) {
      return;
    }
    this.busy.set(true);
    this.failure.set(null);
    try {
      await this.api.resetPassword(this.token, this.password());
    } catch (error) {
      this.failure.set(messageOf(error));
      this.expired.set(error instanceof ApiError && error.kind === 'invalid_link');
      this.busy.set(false);
      return;
    }
    // The reset ended every session of that account, perhaps this browser's own.
    await this.auth.load().catch(() => null);
    this.toasts.show('Your password is changed. Sign in with the new one.');
    await this.router.navigate(['/login']);
  }
}

/** Confirm an email address, from the link in a confirmation email. */
@Component({
  selector: 'app-verify-email-page',
  imports: [AuthShell, RouterLink],
  styleUrl: './auth-form.css',
  template: `
    <app-auth-shell>
      <h1>Confirm your email</h1>
      @switch (state()) {
        @case ('working') {
          <p class="lead" role="status">Confirming…</p>
        }
        @case ('done') {
          <p class="done" role="status">
            Your email is confirmed. Signing in with Google as this address now reaches the same
            account.
          </p>
        }
        @case ('missing') {
          <p class="alert" role="alert">
            This link is incomplete. Open the whole link from the email.
          </p>
        }
        @case ('failed') {
          <p class="alert" role="alert">{{ failure() }}</p>
          <p class="lead">You can ask for a new link from Account settings, under Profile.</p>
        }
      }
      <p class="switch">
        @if (auth.user()) {
          <a routerLink="/">Go to your conversations</a>
        } @else {
          <a routerLink="/login">Sign in</a>
        }
      </p>
    </app-auth-shell>
  `,
})
export class VerifyEmailPage implements OnInit {
  protected readonly auth = inject(Auth);
  private readonly api = inject(AgentApi);

  private readonly token = takeToken(inject(ActivatedRoute), inject(Location));
  protected readonly state = signal<'working' | 'done' | 'missing' | 'failed'>(
    this.token ? 'working' : 'missing',
  );
  protected readonly failure = signal(FAILED);

  async ngOnInit(): Promise<void> {
    if (!this.token) {
      return;
    }
    try {
      await this.api.verifyEmail(this.token);
      this.state.set('done');
    } catch (error) {
      this.failure.set(messageOf(error));
      this.state.set('failed');
    }
    // Whoever is signed in here sees the change at once, if it was their own address.
    await this.auth.load().catch(() => null);
  }
}
