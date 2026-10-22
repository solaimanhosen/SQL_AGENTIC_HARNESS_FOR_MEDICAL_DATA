import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { AdminMetrics } from '../api/admin-types';
import { Chart } from '../api/types';
import { dollars } from '../account/usage-section';
import { ChartView } from '../chat/chart-view';
import { AdminApi } from './admin-api';
import { count, millis } from './format';

export const PERIODS = [7, 14, 30];

/** "10-21" for 2026-10-21: short enough for a daily axis. */
function shortDay(day: string): string {
  return day.slice(5);
}

/** The four daily charts, built from the metrics. They cite no query, as they come from the logs. */
export function monitoringCharts(metrics: AdminMetrics): Chart[] {
  const requestDays = metrics.requests.days;
  const runDays = metrics.runs.days;
  const chart = (
    kind: 'bar' | 'line',
    title: string,
    y: string,
    days: { day: string }[],
    series: Chart['series'],
  ): Chart => ({
    kind,
    title,
    query_number: 0,
    x_label: 'day',
    y_label: y,
    x: days.map((item) => shortDay(item.day)),
    series,
  });
  return [
    chart('line', 'Requests per day', 'requests', requestDays, [
      { name: 'All', values: requestDays.map((day) => day.requests) },
      { name: 'Refused', values: requestDays.map((day) => day.refused) },
      { name: 'Errors', values: requestDays.map((day) => day.errors) },
    ]),
    chart('line', 'Response time per day (ms)', 'ms', requestDays, [
      { name: 'Median', values: requestDays.map((day) => day.p50_ms) },
      { name: '95th percentile', values: requestDays.map((day) => day.p95_ms) },
    ]),
    chart('bar', 'Questions answered per day', 'questions', runDays, [
      { name: 'Questions', values: runDays.map((day) => day.questions) },
    ]),
    chart('bar', 'Estimated model cost per day (USD)', 'USD', runDays, [
      { name: 'Cost', values: runDays.map((day) => Number(day.estimated_cost_usd.toFixed(4))) },
    ]),
  ];
}

/** Requests, refusals, errors, latency, questions and cost over recent days, from the logs. */
@Component({
  selector: 'app-monitoring-section',
  imports: [ChartView],
  template: `
    <div class="toolbar">
      <label for="period">Period</label>
      <select
        id="period"
        class="field"
        [value]="days()"
        (change)="load(+$any($event.target).value)"
      >
        @for (period of periods; track period) {
          <option [value]="period" [selected]="period === days()">Last {{ period }} days</option>
        }
      </select>
    </div>

    @if (metrics(); as data) {
      @if (!data.logs.requests || !data.logs.runs) {
        <p class="settings-status error" role="alert">
          A log is switched off, so some figures are missing: SQL_AGENT_REQUEST_LOG_PATH and
          SQL_AGENT_LOG_PATH must not be "off".
        </p>
      }
      <div class="figures">
        <p>
          <span class="figure">{{ count(data.requests.total) }}</span
          ><span class="what">requests</span>
        </p>
        <p>
          <span class="figure">{{ count(data.requests.refused) }}</span
          ><span class="what">refused</span>
        </p>
        <p>
          <span class="figure">{{ count(data.requests.errors) }}</span
          ><span class="what">server errors</span>
        </p>
        <p>
          <span class="figure">{{ ms(data.requests.p95_ms) }}</span
          ><span class="what">95th-percentile time</span>
        </p>
        <p>
          <span class="figure">{{ count(data.runs.questions) }}</span
          ><span class="what">questions</span>
        </p>
        <p>
          <span class="figure">{{ money(data.runs.estimated_cost_usd) }}</span
          ><span class="what">estimated cost</span>
        </p>
      </div>

      <div class="charts">
        @for (chart of charts(); track chart.title) {
          <section class="settings-card chart-card"><app-chart-view [chart]="chart" /></section>
        }
      </div>

      <section class="settings-card" aria-labelledby="models-title">
        <h2 id="models-title">By model</h2>
        @if (data.runs.by_model.length) {
          <div class="data-table">
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
                @for (row of data.runs.by_model; track row.model) {
                  <tr>
                    <td>{{ row.label }}</td>
                    <td class="num">{{ count(row.questions) }}</td>
                    <td class="num">{{ count(row.input_tokens) }}</td>
                    <td class="num">{{ count(row.output_tokens) }}</td>
                    <td class="num">{{ money(row.estimated_cost_usd) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        } @else {
          <p class="settings-hint">No questions in this period.</p>
        }
      </section>

      <section class="settings-card" aria-labelledby="people-title">
        <h2 id="people-title">By person</h2>
        @if (data.runs.by_user.length) {
          <div class="data-table">
            <table>
              <thead>
                <tr>
                  <th scope="col">Person</th>
                  <th scope="col" class="num">Questions</th>
                  <th scope="col" class="num">Tokens</th>
                  <th scope="col" class="num">Estimated cost</th>
                </tr>
              </thead>
              <tbody>
                @for (row of data.runs.by_user; track row.user_id) {
                  <tr>
                    <td>
                      {{
                        row.email ??
                          (row.user_id === 'before accounts'
                            ? 'Before accounts'
                            : 'A deleted account')
                      }}
                    </td>
                    <td class="num">{{ count(row.questions) }}</td>
                    <td class="num">{{ count(row.input_tokens + row.output_tokens) }}</td>
                    <td class="num">{{ money(row.estimated_cost_usd) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        } @else {
          <p class="settings-hint">No questions in this period.</p>
        }
      </section>

      <section class="settings-card" aria-labelledby="refusals-title">
        <h2 id="refusals-title">Refused requests, by reason</h2>
        @if (refusals().length) {
          <ul class="refusals">
            @for (item of refusals(); track item.reason) {
              <li>
                <code>{{ item.reason }}</code
                ><span>{{ count(item.count) }}</span>
              </li>
            }
          </ul>
        } @else {
          <p class="settings-hint">Nothing was refused in this period.</p>
        }
      </section>
    } @else if (failed()) {
      <p class="settings-status error" role="alert">The figures could not be loaded.</p>
    } @else {
      <p class="settings-hint">Loading…</p>
    }
  `,
  styles: `
    .toolbar {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      margin-bottom: var(--space-4);
      font-size: var(--text-sm);
      font-weight: var(--weight-medium);
    }
    .toolbar select {
      width: auto;
      min-height: 2rem;
      appearance: auto;
    }
    .figures {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
      gap: var(--space-3);
      margin-bottom: var(--space-5);
    }
    .figures p {
      display: grid;
      margin: 0;
      padding: var(--space-3) var(--space-4);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      background: var(--surface);
    }
    .figure {
      font-size: var(--text-xl);
      font-weight: var(--weight-semibold);
      font-variant-numeric: tabular-nums;
    }
    .what {
      color: var(--text-subtle);
      font-size: var(--text-xs);
    }
    .charts {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr));
      gap: var(--space-4);
      margin-bottom: var(--space-5);
    }
    .charts .settings-card + .settings-card {
      margin-top: 0;
    }
    .chart-card {
      padding: var(--space-4);
    }
    .refusals {
      display: grid;
      gap: var(--space-1);
      margin: 0;
      padding: 0;
      list-style: none;
      font-size: var(--text-sm);
    }
    .refusals li {
      display: flex;
      justify-content: space-between;
      max-width: 24rem;
    }
  `,
})
export class MonitoringSection implements OnInit {
  private readonly admin = inject(AdminApi);

  protected readonly periods = PERIODS;
  protected readonly days = signal(14);
  protected readonly metrics = signal<AdminMetrics | null>(null);
  protected readonly failed = signal(false);
  protected readonly count = count;
  protected readonly money = dollars;
  protected readonly ms = millis;
  protected readonly charts = computed(() => {
    const data = this.metrics();
    return data ? monitoringCharts(data) : [];
  });
  protected readonly refusals = computed(() =>
    Object.entries(this.metrics()?.requests.refusals ?? {}).map(([reason, total]) => ({
      reason,
      count: total,
    })),
  );

  ngOnInit(): void {
    void this.load(this.days());
  }

  protected async load(days: number): Promise<void> {
    this.days.set(days);
    try {
      this.metrics.set(await this.admin.metrics(days));
      this.failed.set(false);
    } catch {
      this.failed.set(true);
    }
  }
}
