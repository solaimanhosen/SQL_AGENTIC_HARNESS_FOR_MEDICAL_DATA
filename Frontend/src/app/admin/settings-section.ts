import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { ApiError } from '../api/agent-api';
import { JobInfo } from '../api/admin-types';
import { Auth } from '../auth/auth';
import { AdminApi } from './admin-api';

/** Who may sign up, and the switches that live in Backend/.env, shown for reference. */
@Component({
  selector: 'app-settings-section',
  template: `
    <section class="settings-card" aria-labelledby="registration-title">
      <h2 id="registration-title">Registration</h2>
      <p class="settings-lead">
        Whether anyone who reaches the service may create an account. People who already have one
        can always sign in. Close it before the service is reachable from the internet.
      </p>
      @if (open() !== null) {
        <label class="switch">
          <input
            type="checkbox"
            role="switch"
            [checked]="open()"
            [disabled]="busy()"
            (change)="toggle($any($event.target).checked)"
          />
          <span class="track" aria-hidden="true"><span class="thumb"></span></span>
          <span>Anyone may sign up</span>
        </label>
        @if (status(); as text) {
          <p class="settings-status" [class.ok]="!failed()" [class.error]="failed()" role="status">
            {{ text }}
          </p>
        }
      }
    </section>

    <section class="settings-card" aria-labelledby="env-title">
      <h2 id="env-title">Set in Backend/.env</h2>
      <p class="settings-lead">These change only on the server, with a restart.</p>
      <dl class="facts">
        <div>
          <dt>Google sign-in</dt>
          <dd>
            {{ googleEnabled() ? 'On' : 'Off' }} <code>SQL_AGENT_GOOGLE_CLIENT_ID</code>,
            <code>_SECRET</code>
          </dd>
        </div>
        <div>
          <dt>Live evaluation from the console</dt>
          <dd>{{ liveEvaluation() ? 'Allowed' : 'Off' }} <code>SQL_AGENT_ADMIN_LIVE_EVAL</code></dd>
        </div>
      </dl>
    </section>
  `,
  styles: `
    .switch {
      display: inline-flex;
      align-items: center;
      gap: var(--space-3);
      font-size: var(--text-sm);
      cursor: pointer;
    }
    .switch input {
      position: absolute;
      opacity: 0;
    }
    .track {
      position: relative;
      width: 2.25rem;
      height: 1.25rem;
      border-radius: var(--radius-full);
      background: var(--border-strong);
      transition: background var(--duration-fast) var(--ease);
    }
    .thumb {
      position: absolute;
      top: 0.125rem;
      left: 0.125rem;
      width: 1rem;
      height: 1rem;
      border-radius: var(--radius-full);
      background: var(--surface);
      box-shadow: var(--shadow-1);
      transition: transform var(--duration-fast) var(--ease);
    }
    .switch input:checked + .track {
      background: var(--accent);
    }
    .switch input:checked + .track .thumb {
      transform: translateX(1rem);
    }
    .switch input:focus-visible + .track {
      outline: 2px solid var(--focus-ring);
      outline-offset: 2px;
    }
    .switch + .settings-status {
      margin-top: var(--space-3);
    }
    .facts {
      display: grid;
      gap: var(--space-3);
      margin: 0;
      font-size: var(--text-sm);
    }
    dt {
      font-weight: var(--weight-medium);
    }
    dd {
      margin: 0;
      color: var(--text-muted);
    }
  `,
})
export class SettingsSection implements OnInit {
  private readonly admin = inject(AdminApi);
  private readonly auth = inject(Auth);

  protected readonly open = signal<boolean | null>(null);
  protected readonly busy = signal(false);
  protected readonly status = signal<string | null>(null);
  protected readonly failed = signal(false);
  private readonly jobs = signal<JobInfo[]>([]);

  protected readonly googleEnabled = computed(() => this.auth.config()?.google_enabled ?? false);
  protected readonly liveEvaluation = computed(
    () => this.jobs().find((job) => job.id === 'evaluation_live')?.enabled ?? false,
  );

  async ngOnInit(): Promise<void> {
    void this.auth.loadConfig();
    try {
      const [settings, jobs] = await Promise.all([this.admin.settings(), this.admin.jobs()]);
      this.open.set(settings.registration_open);
      this.jobs.set(jobs);
    } catch {
      this.status.set('The settings could not be loaded.');
      this.failed.set(true);
    }
  }

  protected async toggle(open: boolean): Promise<void> {
    this.busy.set(true);
    try {
      const settings = await this.admin.changeSettings(open);
      this.open.set(settings.registration_open);
      this.status.set(
        settings.registration_open ? 'Registration is open.' : 'Registration is closed.',
      );
      this.failed.set(false);
      void this.auth.loadConfig();
    } catch (error) {
      this.status.set(error instanceof ApiError ? error.message : 'It could not be changed.');
      this.failed.set(true);
    } finally {
      this.busy.set(false);
    }
  }
}
