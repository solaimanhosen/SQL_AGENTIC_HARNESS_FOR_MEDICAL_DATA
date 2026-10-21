import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { LucideLaptop, LucideSmartphone } from '@lucide/angular';

import { AgentApi, ApiError } from '../api/agent-api';
import { SessionInfo } from '../api/types';
import { Auth, signInError } from '../auth/auth';
import { MIN_PASSWORD_CHARS } from '../auth/auth-page';
import { Confirm } from '../ui/confirm-dialog';
import { describeAgent, formatWhen, isMobileAgent } from './describe-agent';

/** The password, the Google connection, and every browser or device that is signed in. */
@Component({
  selector: 'app-security-section',
  imports: [LucideLaptop, LucideSmartphone],
  template: `
    @if (auth.user(); as user) {
      <section class="settings-card" aria-labelledby="password-title">
        <h2 id="password-title">{{ user.has_password ? 'Password' : 'Set a password' }}</h2>
        <p class="settings-lead">
          @if (user.has_password) {
            Change the password you sign in with.
          } @else {
            You sign in with Google. A password lets you sign in without it too.
          }
        </p>
        <form (submit)="changePassword($event)">
          @if (user.has_password) {
            <div class="settings-row">
              <label for="current-password">Current password</label>
              <input
                id="current-password"
                class="field"
                type="password"
                autocomplete="current-password"
                maxlength="128"
                [value]="current()"
                (input)="current.set($any($event.target).value)"
              />
            </div>
          }
          <div class="settings-row">
            <label for="new-password">New password</label>
            <input
              id="new-password"
              class="field"
              type="password"
              autocomplete="new-password"
              maxlength="128"
              aria-describedby="new-password-hint"
              [value]="next()"
              (input)="next.set($any($event.target).value)"
            />
            <p id="new-password-hint" class="settings-hint">
              At least {{ minPassword }} characters.
            </p>
          </div>
          <div class="settings-row">
            <label for="repeat-password">New password again</label>
            <input
              id="repeat-password"
              class="field"
              type="password"
              autocomplete="new-password"
              maxlength="128"
              [value]="repeat()"
              (input)="repeat.set($any($event.target).value)"
            />
          </div>
          <div class="settings-actions">
            <button type="submit" [disabled]="!canChange() || busy()">
              {{ user.has_password ? 'Change password' : 'Set password' }}
            </button>
            @if (passwordStatus(); as text) {
              <p
                class="settings-status"
                [class.ok]="!passwordFailed()"
                [class.error]="passwordFailed()"
                role="status"
              >
                {{ text }}
              </p>
            }
          </div>
        </form>
      </section>

      <section class="settings-card" aria-labelledby="google-title">
        <h2 id="google-title">Google</h2>
        @if (googleError(); as text) {
          <p class="settings-status error" role="alert">{{ text }}</p>
        }
        @if (!googleEnabled()) {
          <p class="settings-lead">Google sign-in is not set up on this service.</p>
        } @else if (user.google_linked) {
          <p class="settings-lead">Connected. You can sign in with Google as well.</p>
          <div class="settings-actions">
            <button
              type="button"
              class="secondary"
              [disabled]="!user.has_password || busy()"
              (click)="disconnectGoogle()"
            >
              Disconnect Google
            </button>
            @if (!user.has_password) {
              <p class="settings-hint">Set a password first, or you could not sign in after.</p>
            }
          </div>
        } @else {
          <p class="settings-lead">Connect a Google account to sign in with it.</p>
          <a class="button-link secondary-link" [href]="connectHref">Connect Google</a>
        }
      </section>

      <section class="settings-card" aria-labelledby="sessions-title">
        <h2 id="sessions-title">Where you are signed in</h2>
        <p class="settings-lead">
          Sign out of a browser or device you no longer use, or do not recognise.
        </p>
        @if (sessionsFailed()) {
          <p class="settings-status error" role="alert">
            The list of sessions could not be loaded.
          </p>
        }
        <ul class="sessions">
          @for (session of sessions(); track session.id) {
            <li>
              @if (mobile(session)) {
                <svg lucideSmartphone [size]="18" aria-hidden="true"></svg>
              } @else {
                <svg lucideLaptop [size]="18" aria-hidden="true"></svg>
              }
              <div class="what">
                <p class="device">
                  {{ describe(session.user_agent) }}
                  @if (session.current) {
                    <span class="this">This device</span>
                  }
                </p>
                <p class="when">
                  Last active {{ when(session.last_used_at) }} · signed in
                  {{ when(session.created_at) }}
                </p>
              </div>
              @if (!session.current) {
                <button type="button" class="tool" (click)="revoke(session)">Sign out</button>
              }
            </li>
          }
        </ul>
        @if (others() > 0) {
          <div class="settings-actions">
            <button type="button" class="secondary" (click)="revokeOthers()">
              Sign out everywhere else
            </button>
          </div>
        }
      </section>
    }
  `,
  styles: `
    .sessions {
      display: grid;
      gap: var(--space-1);
      margin: 0 0 var(--space-4);
      padding: 0;
      list-style: none;
    }
    li {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      padding: var(--space-3);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
    }
    li > svg {
      flex: none;
      color: var(--text-subtle);
    }
    .what {
      flex: 1;
      min-width: 0;
    }
    .what p {
      margin: 0;
    }
    .device {
      font-size: var(--text-sm);
      font-weight: var(--weight-medium);
    }
    .this {
      margin-left: var(--space-2);
      padding: 0 var(--space-1-5);
      border-radius: var(--radius-full);
      background: var(--ok-bg);
      color: var(--ok-text);
      font-size: var(--text-xs);
      font-weight: var(--weight-medium);
    }
    .when {
      color: var(--text-subtle);
      font-size: var(--text-xs);
    }
    .button-link {
      display: inline-flex;
      align-items: center;
      min-height: var(--control-height);
      padding: 0 var(--space-4);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      background: var(--surface);
      color: var(--text);
      font-size: var(--text-sm);
      font-weight: var(--weight-medium);
      text-decoration: none;
    }
    .button-link:hover {
      background: var(--surface-hover);
    }
  `,
})
export class SecuritySection implements OnInit {
  protected readonly auth = inject(Auth);
  private readonly api = inject(AgentApi);
  private readonly confirm = inject(Confirm);

  /** A code from connecting Google, passed back in the address. */
  readonly error = input<string | null>(null);

  protected readonly minPassword = MIN_PASSWORD_CHARS;
  protected readonly connectHref =
    '/api/auth/google/start?link=true&next=%2Faccount%3Ftab%3Dsecurity';
  protected readonly describe = describeAgent;
  protected readonly mobile = (session: SessionInfo) => isMobileAgent(session.user_agent);
  protected readonly when = formatWhen;

  protected readonly current = signal('');
  protected readonly next = signal('');
  protected readonly repeat = signal('');
  protected readonly busy = signal(false);
  protected readonly passwordStatus = signal<string | null>(null);
  protected readonly passwordFailed = signal(false);
  protected readonly sessions = signal<SessionInfo[]>([]);
  protected readonly sessionsFailed = signal(false);
  protected readonly others = computed(
    () => this.sessions().filter((item) => !item.current).length,
  );
  protected readonly googleEnabled = computed(() => this.auth.config()?.google_enabled ?? false);
  protected readonly googleError = computed(() => {
    const code = this.error();
    return code ? signInError(code) : null;
  });
  protected readonly canChange = computed(
    () =>
      this.next().length >= MIN_PASSWORD_CHARS &&
      this.next() === this.repeat() &&
      (!this.auth.user()?.has_password || this.current().length > 0),
  );

  ngOnInit(): void {
    void this.auth.loadConfig();
    void this.loadSessions();
  }

  protected async changePassword(event: Event): Promise<void> {
    event.preventDefault();
    if (!this.canChange()) {
      return;
    }
    this.busy.set(true);
    const hadPassword = this.auth.user()?.has_password ?? false;
    try {
      await this.api.changePassword(hadPassword ? this.current() : null, this.next());
      await this.auth.load();
      this.passwordStatus.set(hadPassword ? 'Password changed.' : 'Password set.');
      this.passwordFailed.set(false);
    } catch (error) {
      this.passwordStatus.set(
        error instanceof ApiError ? error.message : 'It could not be changed.',
      );
      this.passwordFailed.set(true);
    } finally {
      this.current.set('');
      this.next.set('');
      this.repeat.set('');
      this.busy.set(false);
    }
  }

  protected async disconnectGoogle(): Promise<void> {
    const confirmed = await this.confirm.ask({
      title: 'Disconnect Google?',
      message:
        'You will sign in with your email and password only. You can connect Google again later.',
      confirm: 'Disconnect',
    });
    if (!confirmed) {
      return;
    }
    this.busy.set(true);
    try {
      this.auth.user.set(await this.api.disconnectGoogle());
    } finally {
      this.busy.set(false);
    }
  }

  protected async revoke(session: SessionInfo): Promise<void> {
    await this.api.revokeSession(session.id);
    await this.loadSessions();
  }

  protected async revokeOthers(): Promise<void> {
    const confirmed = await this.confirm.ask({
      title: 'Sign out everywhere else?',
      message: `Every other browser and device (${this.others()}) will need to sign in again. This one stays signed in.`,
      confirm: 'Sign out others',
    });
    if (confirmed) {
      await this.api.revokeOtherSessions();
      await this.loadSessions();
    }
  }

  private async loadSessions(): Promise<void> {
    try {
      this.sessions.set(await this.api.sessions());
      this.sessionsFailed.set(false);
    } catch {
      this.sessionsFailed.set(true);
    }
  }
}
