import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { ApiError } from '../api/agent-api';
import { ThemeToggle } from '../ui/theme-toggle';
import { Auth, signInError } from './auth';

export const MIN_PASSWORD_CHARS = 12;

/**
 * Sign in or create an account: email and password, and Google when the service offers it.
 * Messages come from the service or from the short codes it puts in the address after a
 * Google sign-in, and are shown as text.
 */
@Component({
  selector: 'app-auth-page',
  imports: [RouterLink, ThemeToggle],
  template: `
    <div class="corner"><app-theme-toggle /></div>
    <main class="auth">
      <div class="card panel">
        <p class="brand">
          <span class="mark" aria-hidden="true">PQ</span>
          <span>Patient data questions</span>
        </p>
        <h1>{{ registering() ? 'Create your account' : 'Sign in' }}</h1>
        <p class="lead">
          {{
            registering()
              ? 'Ask questions about the synthetic patient database in plain language.'
              : 'Welcome back. Your conversations are waiting.'
          }}
        </p>

        @if (message(); as text) {
          <p class="alert" role="alert">{{ text }}</p>
        }

        @if (googleEnabled()) {
          <a class="google" [href]="googleHref()">
            <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
              <path
                fill="#4285F4"
                d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"
              />
              <path
                fill="#34A853"
                d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"
              />
              <path
                fill="#FBBC05"
                d="M3.97 10.72A5.41 5.41 0 0 1 3.69 9c0-.6.1-1.18.28-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z"
              />
              <path
                fill="#EA4335"
                d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"
              />
            </svg>
            <span>Continue with Google</span>
          </a>
          <p class="divider" aria-hidden="true"><span>or</span></p>
        }

        <form (submit)="submit($event)" novalidate>
          @if (registering()) {
            <label for="name">Name <span class="optional">(optional)</span></label>
            <input
              id="name"
              class="field"
              autocomplete="name"
              maxlength="100"
              [value]="name()"
              (input)="name.set($any($event.target).value)"
            />
          }
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
          <label for="password">Password</label>
          <input
            id="password"
            class="field"
            type="password"
            required
            maxlength="128"
            [attr.autocomplete]="registering() ? 'new-password' : 'current-password'"
            [attr.aria-describedby]="registering() ? 'password-hint' : null"
            [value]="password()"
            (input)="password.set($any($event.target).value)"
          />
          @if (registering()) {
            <p id="password-hint" class="hint">At least {{ minPassword }} characters.</p>
          }
          <button type="submit" class="submit" [disabled]="busy() || !canSubmit()">
            {{ busy() ? 'One moment…' : registering() ? 'Create account' : 'Sign in' }}
          </button>
        </form>

        <p class="switch">
          @if (registering()) {
            Already have an account?
            <a [routerLink]="['/login']" [queryParams]="nextParams()">Sign in</a>
          } @else if (registrationOpen()) {
            New here?
            <a [routerLink]="['/register']" [queryParams]="nextParams()">Create an account</a>
          }
        </p>
      </div>
      <p class="note">
        Synthetic Synthea data. Questions and results are sent to the Anthropic API.
      </p>
    </main>
  `,
  styles: `
    :host {
      display: block;
      min-height: 100dvh;
      background:
        radial-gradient(60rem 30rem at 50% -10%, var(--accent-soft), transparent 70%), var(--bg);
    }
    .corner {
      position: absolute;
      top: var(--space-2-5);
      right: var(--space-4);
    }
    .auth {
      display: grid;
      justify-items: center;
      align-content: center;
      gap: var(--space-4);
      min-height: 100dvh;
      padding: var(--space-8) var(--space-4);
    }
    .panel {
      width: min(24rem, 100%);
      padding: var(--space-8) var(--space-6);
      box-shadow: var(--shadow-2);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      margin: 0 0 var(--space-6);
      font-size: var(--text-sm);
      font-weight: var(--weight-semibold);
    }
    .mark {
      display: grid;
      place-items: center;
      width: 1.75rem;
      height: 1.75rem;
      border-radius: var(--radius-md);
      background: var(--accent);
      color: var(--on-accent);
      font-size: 0.6875rem;
      font-weight: 700;
    }
    h1 {
      margin: 0 0 var(--space-1);
      font-size: var(--text-xl);
    }
    .lead {
      margin: 0 0 var(--space-6);
      color: var(--text-muted);
      font-size: var(--text-sm);
    }
    .alert {
      margin: 0 0 var(--space-4);
      padding: var(--space-2-5) var(--space-3);
      border: 1px solid color-mix(in srgb, var(--danger) 35%, var(--border));
      border-radius: var(--radius-md);
      background: var(--danger-bg);
      color: var(--text);
      font-size: var(--text-sm);
    }
    .google {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: var(--space-2-5);
      min-height: 2.5rem;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      background: var(--surface);
      color: var(--text);
      font-size: var(--text-sm);
      font-weight: var(--weight-medium);
      text-decoration: none;
    }
    .google:hover {
      background: var(--surface-hover);
    }
    .divider {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      margin: var(--space-5) 0;
      color: var(--text-subtle);
      font-size: var(--text-xs);
    }
    .divider::before,
    .divider::after {
      content: '';
      flex: 1;
      height: 1px;
      background: var(--border);
    }
    form {
      display: grid;
      gap: var(--space-1-5);
    }
    label {
      margin-top: var(--space-2);
      font-size: var(--text-sm);
      font-weight: var(--weight-medium);
    }
    .optional,
    .hint {
      color: var(--text-subtle);
      font-weight: 400;
    }
    .hint {
      margin: 0;
      font-size: var(--text-xs);
    }
    .submit {
      min-height: 2.5rem;
      margin-top: var(--space-4);
    }
    .switch {
      margin: var(--space-5) 0 0;
      color: var(--text-muted);
      font-size: var(--text-sm);
      text-align: center;
    }
    .switch a {
      color: var(--accent);
      font-weight: var(--weight-medium);
    }
    .note {
      margin: 0;
      color: var(--text-subtle);
      font-size: var(--text-xs);
      text-align: center;
    }
  `,
})
export class AuthPage implements OnInit {
  private readonly auth = inject(Auth);
  private readonly router = inject(Router);

  /** From the route's data: which page this is. */
  readonly mode = input<'login' | 'register'>('login');
  /** From the address: where to go after signing in, and a code from a Google sign-in. */
  readonly next = input<string>();
  readonly error = input<string>();

  protected readonly minPassword = MIN_PASSWORD_CHARS;
  protected readonly name = signal('');
  protected readonly email = signal('');
  protected readonly password = signal('');
  protected readonly busy = signal(false);
  private readonly failure = signal<string | null>(null);

  protected readonly registering = computed(() => this.mode() === 'register');
  protected readonly googleEnabled = computed(() => this.auth.config()?.google_enabled ?? false);
  protected readonly registrationOpen = computed(
    () => this.auth.config()?.registration_open ?? true,
  );
  protected readonly message = computed(() => this.failure() ?? signInError(this.error() ?? null));
  protected readonly nextParams = computed(() => (this.next() ? { next: this.next() } : {}));
  protected readonly googleHref = computed(
    () => `/api/auth/google/start?next=${encodeURIComponent(this.safeNext())}`,
  );
  protected readonly canSubmit = computed(
    () =>
      this.email().trim().length > 0 &&
      (this.registering()
        ? this.password().length >= MIN_PASSWORD_CHARS
        : this.password().length > 0),
  );

  ngOnInit(): void {
    void this.auth.loadConfig();
  }

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    if (!this.canSubmit() || this.busy()) {
      return;
    }
    this.busy.set(true);
    this.failure.set(null);
    try {
      if (this.registering()) {
        await this.auth.register(this.email().trim(), this.password(), this.name().trim());
      } else {
        await this.auth.login(this.email().trim(), this.password());
      }
      await this.router.navigateByUrl(this.safeNext());
    } catch (error) {
      this.failure.set(
        error instanceof ApiError ? error.message : 'Something went wrong. Try again.',
      );
      this.password.set('');
    } finally {
      this.busy.set(false);
    }
  }

  /** Only a path inside this application, so a crafted link cannot send anyone elsewhere. */
  private safeNext(): string {
    const next = this.next() ?? '/';
    return next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\') ? next : '/';
  }
}
