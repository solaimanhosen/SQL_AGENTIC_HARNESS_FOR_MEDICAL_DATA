import { Component, OnInit, computed, inject, output, signal } from '@angular/core';

import { AdminOverview } from '../api/admin-types';
import { formatWhen } from '../account/describe-agent';
import { AdminApi } from './admin-api';
import { RUN_STATES, count, duration } from './format';

const CHECK_LABELS: Record<string, string> = {
  tests: 'Unit tests',
  security: 'Security catalogue',
  semantics: 'Semantic layer',
  evaluation_dry_run: 'Evaluation, dry run',
  connections: 'Setup and connections',
  models_ping: 'Ping every model',
  evaluation_live: 'Evaluation, live',
};

/** Whether each part of the service is up, who uses it, what it spent today, and the latest checks. */
@Component({
  selector: 'app-overview-section',
  template: `
    @if (overview(); as data) {
      <div class="tiles">
        <section class="tile">
          <p class="name">Patient database</p>
          <p class="value">
            <span class="state" [class.good]="data.database.ok" [class.bad]="!data.database.ok">
              {{ data.database.ok ? 'Readable' : 'Not readable' }}
            </span>
          </p>
          <p class="detail">
            {{ data.database.tables }} tables · data as of {{ data.database.as_of }}
          </p>
        </section>
        <section class="tile">
          <p class="name">Anthropic API key</p>
          <p class="value">
            <span
              class="state"
              [class.good]="data.anthropic_key_set"
              [class.bad]="!data.anthropic_key_set"
            >
              {{ data.anthropic_key_set ? 'Set' : 'Missing' }}
            </span>
          </p>
          <p class="detail">Default {{ data.default_model }} at {{ data.default_effort }} effort</p>
        </section>
        <section class="tile">
          <p class="name">Sign-in</p>
          <p class="value">
            <span class="state" [class.good]="data.registration_open">
              Registration {{ data.registration_open ? 'open' : 'closed' }}
            </span>
          </p>
          <p class="detail">Google sign-in {{ data.google_enabled ? 'on' : 'off' }}</p>
        </section>
        <section class="tile">
          <p class="name">Service</p>
          <p class="value big">{{ uptime() }}</p>
          <p class="detail">
            Up since {{ when(data.service.started_at) }} · schema
            {{ data.application_database.schema_version }}
          </p>
        </section>
        <section class="tile">
          <p class="name">People</p>
          <p class="value big">{{ count(data.people.accounts) }}</p>
          <p class="detail">
            {{ data.people.admins }} admin{{ data.people.admins === 1 ? '' : 's' }} ·
            {{ data.people.disabled }} disabled
          </p>
        </section>
        <section class="tile">
          <p class="name">Conversations</p>
          <p class="value big">{{ count(data.conversations.conversations) }}</p>
          <p class="detail">{{ count(data.conversations.questions) }} questions today (UTC)</p>
        </section>
      </div>

      <section class="settings-card" aria-labelledby="budget-title">
        <h2 id="budget-title">Today's budget</h2>
        <p class="settings-lead">
          {{ count(data.budget.spent_today) }} spent and
          {{ count(data.budget.reserved_today) }} held for running questions, of
          {{ count(data.budget.daily_token_budget) }} model tokens. {{ data.budget.running }} of
          {{ data.budget.max_concurrent_runs }} questions running now.
        </p>
        <div
          class="meter"
          role="meter"
          aria-label="Today's budget used"
          aria-valuemin="0"
          [attr.aria-valuemax]="data.budget.daily_token_budget"
          [attr.aria-valuenow]="data.budget.spent_today + data.budget.reserved_today"
        >
          <span [style.width.%]="budgetShare()"></span>
        </div>
      </section>

      <section class="settings-card" aria-labelledby="checks-title">
        <h2 id="checks-title">Latest checks</h2>
        @if (checks().length) {
          <ul class="checks">
            @for (check of checks(); track check.job) {
              <li>
                <span class="state {{ states[check.status].tone }}">{{
                  states[check.status].label
                }}</span>
                <span class="check-name">{{ labels[check.job] ?? check.job }}</span>
                <span class="verdict">{{ check.summary.verdict }}</span>
                <span class="when">{{ when(check.started_at) }}</span>
              </li>
            }
          </ul>
        } @else {
          <p class="settings-hint">No checks have been run yet.</p>
        }
        <div class="settings-actions">
          <button type="button" class="secondary" (click)="openChecks.emit()">Run checks</button>
        </div>
      </section>
    } @else if (failed()) {
      <p class="settings-status error" role="alert">The overview could not be loaded.</p>
    } @else {
      <p class="settings-hint">Loading…</p>
    }
  `,
  styles: `
    .tiles {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(min(13rem, 100%), 1fr));
      gap: var(--space-4);
      margin-bottom: var(--space-5);
    }
    .tile {
      padding: var(--space-4);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      background: var(--surface);
      box-shadow: var(--shadow-1);
    }
    .tile p {
      margin: 0;
    }
    .name {
      color: var(--text-muted);
      font-size: var(--text-xs);
      font-weight: var(--weight-medium);
    }
    .value {
      margin: var(--space-2) 0 !important;
    }
    .big {
      font-size: var(--text-xl);
      font-weight: var(--weight-semibold);
      font-variant-numeric: tabular-nums;
    }
    .detail {
      color: var(--text-subtle);
      font-size: var(--text-xs);
    }
    .meter {
      height: 0.5rem;
      overflow: hidden;
      border-radius: var(--radius-full);
      background: var(--chip);
    }
    .meter span {
      display: block;
      height: 100%;
      background: var(--accent);
    }
    .checks {
      display: grid;
      gap: var(--space-2);
      margin: 0 0 var(--space-4);
      padding: 0;
      list-style: none;
    }
    .checks li {
      display: grid;
      grid-template-columns: 7rem 11rem minmax(0, 1fr) auto;
      align-items: center;
      gap: var(--space-3);
      font-size: var(--text-sm);
    }
    .checks .state {
      justify-self: start;
    }
    .check-name {
      font-weight: var(--weight-medium);
    }
    .verdict {
      overflow: hidden;
      color: var(--text-muted);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .when {
      color: var(--text-subtle);
      font-size: var(--text-xs);
    }
    @media (max-width: 48rem) {
      .checks li {
        grid-template-columns: auto minmax(0, 1fr);
      }
      .verdict,
      .when {
        grid-column: 2;
      }
    }
  `,
})
export class OverviewSection implements OnInit {
  private readonly admin = inject(AdminApi);
  /** Asks the page to switch to the Checks section. */
  readonly openChecks = output<void>();

  protected readonly overview = signal<AdminOverview | null>(null);
  protected readonly failed = signal(false);
  protected readonly states = RUN_STATES;
  protected readonly labels = CHECK_LABELS;
  protected readonly count = count;
  protected readonly when = formatWhen;

  protected readonly uptime = computed(() => duration(this.overview()?.service.uptime_seconds));
  protected readonly budgetShare = computed(() => {
    const budget = this.overview()?.budget;
    return budget
      ? Math.min(
          100,
          (100 * (budget.spent_today + budget.reserved_today)) / budget.daily_token_budget,
        )
      : 0;
  });
  protected readonly checks = computed(() =>
    Object.values(this.overview()?.latest_checks ?? {}).sort((a, b) =>
      b.started_at.localeCompare(a.started_at),
    ),
  );

  async ngOnInit(): Promise<void> {
    try {
      this.overview.set(await this.admin.overview());
    } catch {
      this.failed.set(true);
    }
  }
}
