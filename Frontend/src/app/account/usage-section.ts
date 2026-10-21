import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { AgentApi } from '../api/agent-api';
import { MyUsage } from '../api/types';

const NUMBER = new Intl.NumberFormat('en-US');
const MONTH = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });

/** "$0.0019" for a small cost, "$1.24" for a larger one, so cheap models do not read as $0.00. */
export function dollars(value: number | null): string {
  if (value === null) {
    return 'unknown';
  }
  if (value === 0) {
    return '$0';
  }
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

/** What you have spent: today against your daily budget, and this month by model. */
@Component({
  selector: 'app-usage-section',
  template: `
    <section class="settings-card" aria-labelledby="today-title">
      <h2 id="today-title">Today</h2>
      @if (usage(); as usage) {
        <p class="settings-lead">
          {{ count(usage.today_tokens) }} of
          {{ usage.daily_budget ? count(usage.daily_budget) : 'unlimited' }}
          model tokens. Your budget resets at midnight UTC.
        </p>
        @if (usage.daily_budget) {
          <div
            class="meter"
            role="meter"
            aria-label="Today's budget used"
            [attr.aria-valuenow]="usage.today_tokens"
            aria-valuemin="0"
            [attr.aria-valuemax]="usage.daily_budget"
          >
            <span [style.width.%]="share()"></span>
          </div>
        }
      } @else if (failed()) {
        <p class="settings-status error" role="alert">Your usage could not be loaded.</p>
      } @else {
        <p class="settings-hint">Loading…</p>
      }
    </section>

    @if (usage(); as usage) {
      <section class="settings-card" aria-labelledby="month-title">
        <h2 id="month-title">{{ month() }}</h2>
        <p class="settings-lead">
          {{ usage.questions }} {{ usage.questions === 1 ? 'question' : 'questions' }} ·
          {{ count(usage.input_tokens) }} in and {{ count(usage.output_tokens) }} out tokens · about
          {{ money(usage.estimated_cost_usd) }}
        </p>
        @if (usage.by_model.length) {
          <div class="scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col" class="num">Questions</th>
                  <th scope="col" class="num">Tokens in</th>
                  <th scope="col" class="num">Tokens out</th>
                  <th scope="col" class="num">Estimated cost</th>
                </tr>
              </thead>
              <tbody>
                @for (row of usage.by_model; track row.model) {
                  <tr>
                    <td>{{ row.label }}</td>
                    <td class="num">{{ row.questions }}</td>
                    <td class="num">{{ count(row.input_tokens) }}</td>
                    <td class="num">{{ count(row.output_tokens) }}</td>
                    <td class="num">{{ money(row.estimated_cost_usd) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        } @else {
          <p class="settings-hint">No questions yet this month.</p>
        }
        <p class="settings-hint note">
          Costs are estimates at each model's list price. Questions in conversations you deleted no
          longer count here.
        </p>
      </section>
    }
  `,
  styles: `
    .meter {
      height: 0.5rem;
      overflow: hidden;
      border-radius: var(--radius-full);
      background: var(--chip);
    }
    .meter span {
      display: block;
      height: 100%;
      border-radius: inherit;
      background: var(--accent);
    }
    .scroll {
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: var(--text-sm);
    }
    th,
    td {
      padding: var(--space-2) var(--space-3);
      text-align: left;
      white-space: nowrap;
    }
    th {
      background: var(--surface-2);
      color: var(--text-muted);
      font-weight: var(--weight-medium);
    }
    tbody tr + tr td {
      border-top: 1px solid var(--border);
    }
    .num {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    .note {
      margin-top: var(--space-3);
    }
  `,
})
export class UsageSection implements OnInit {
  private readonly api = inject(AgentApi);

  protected readonly usage = signal<MyUsage | null>(null);
  protected readonly failed = signal(false);
  protected readonly count = (value: number) => NUMBER.format(value);
  protected readonly money = dollars;
  protected readonly share = computed(() => {
    const usage = this.usage();
    return usage?.daily_budget ? Math.min(100, (100 * usage.today_tokens) / usage.daily_budget) : 0;
  });
  protected readonly month = computed(() => {
    const usage = this.usage();
    return usage ? `This month, ${MONTH.format(new Date(usage.month_start + 'T00:00:00Z'))}` : '';
  });

  async ngOnInit(): Promise<void> {
    try {
      this.usage.set(await this.api.myUsage());
    } catch {
      this.failed.set(true);
    }
  }
}
