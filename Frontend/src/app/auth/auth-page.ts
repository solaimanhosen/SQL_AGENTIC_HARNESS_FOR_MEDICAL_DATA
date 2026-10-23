import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { ApiError } from '../api/agent-api';
import { Auth, signInError } from './auth';
import { AuthShell } from './auth-shell';

export const MIN_PASSWORD_CHARS = 12;

/**
 * Sign in or create an account: email and password, and Google when the service offers it.
 * Messages come from the service or from the short codes it puts in the address after a
 * Google sign-in, and are shown as text.
 */
@Component({
  selector: 'app-auth-page',
  imports: [AuthShell, RouterLink],
  styleUrl: './auth-form.css',
  template: `
    <app-auth-shell>
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
        @if (forgotOffered()) {
          <div class="label-row">
            <label for="password">Password</label>
            <a routerLink="/forgot-password" [state]="{ email: email().trim() }"
              >Forgot password?</a
            >
          </div>
        } @else {
          <label for="password">Password</label>
        }
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
    </app-auth-shell>
  `,
  styles: `
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
  protected readonly forgotOffered = computed(
    () => !this.registering() && (this.auth.config()?.email_enabled ?? false),
  );
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
