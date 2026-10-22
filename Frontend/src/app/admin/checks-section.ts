import {
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  afterRenderEffect,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';

import { ApiError } from '../api/agent-api';
import { JobInfo, RunRecord } from '../api/admin-types';
import { formatWhen } from '../account/describe-agent';
import { Auth } from '../auth/auth';
import { Confirm } from '../ui/confirm-dialog';
import { AdminApi } from './admin-api';
import { RUN_STATES, duration } from './format';

/** Lines kept on screen for one run; the service keeps the full capped output. */
const MAX_SCREEN_LINES = 5000;

interface Shown {
  id: string;
  job: string;
  record: RunRecord | null;
  lines: string[];
  following: boolean;
}

/**
 * The checks an admin can run. Each card starts one; its output appears below as it is
 * written. Output is shown as text, never as HTML: it can quote data, test names and errors.
 */
@Component({
  selector: 'app-checks-section',
  template: `
    @if (problem(); as text) {
      <p class="settings-status error" role="alert">{{ text }}</p>
    }
    <div class="jobs">
      @for (job of jobs(); track job.id) {
        <section class="job" [attr.aria-labelledby]="'job-' + job.id">
          <div class="head">
            <h2 [id]="'job-' + job.id">{{ job.label }}</h2>
            <span class="state" [class.warn]="job.paid">{{ job.cost }}</span>
          </div>
          <p class="description">{{ job.description }}</p>
          @for (choice of job.choices; track choice.name) {
            <label class="choice">
              <span>{{ choice.label }}</span>
              <select
                class="field"
                [disabled]="!job.enabled"
                [value]="chosen(job.id, choice.name, choice.default)"
                (change)="choose(job.id, choice.name, $any($event.target).value)"
              >
                @for (option of choice.options; track option) {
                  <option
                    [value]="option"
                    [selected]="option === chosen(job.id, choice.name, choice.default)"
                  >
                    {{ option }}
                  </option>
                }
              </select>
            </label>
          }
          <div class="foot">
            @if (job.latest; as latest) {
              <span class="state {{ states[latest.status].tone }}">{{
                states[latest.status].label
              }}</span>
              <span class="when">{{ when(latest.started_at) }}</span>
            } @else {
              <span class="when">Never run</span>
            }
            <button
              type="button"
              class="run"
              [class.secondary]="job.paid"
              [disabled]="!job.enabled || busy()"
              [title]="job.enabled ? 'Run ' + job.label : (job.disabled_reason ?? '')"
              (click)="start(job)"
            >
              Run
            </button>
          </div>
          @if (!job.enabled && job.disabled_reason) {
            <p class="settings-hint">{{ job.disabled_reason }}</p>
          }
        </section>
      }
    </div>

    @if (shown(); as run) {
      <section class="settings-card output" aria-labelledby="output-title">
        <div class="output-head">
          <h2 id="output-title">{{ label(run.job) }}</h2>
          @if (run.record; as record) {
            <span class="state {{ states[record.status].tone }}">{{
              states[record.status].label
            }}</span>
            <span class="when">{{ seconds(record) }}</span>
          } @else {
            <span class="state busy">Running</span>
          }
          @if (running()) {
            <button type="button" class="secondary cancel" (click)="cancel(run.id)">Cancel</button>
          }
        </div>
        @if (run.record?.summary?.verdict; as verdict) {
          <p class="verdict" role="status">{{ verdict }}</p>
        }
        @if (run.record?.summary?.failed?.length) {
          <ul class="failed">
            @for (name of run.record!.summary.failed!; track name) {
              <li>{{ name }}</li>
            }
          </ul>
        }
        @if (run.record?.truncated) {
          <p class="settings-hint">The output was long, so only its end was kept.</p>
        }
        <pre #log class="log" tabindex="0" aria-label="Output">{{
          run.lines.join(
            '
'
          )
        }}</pre>
      </section>
    }

    <section class="settings-card" aria-labelledby="history-title">
      <h2 id="history-title">History</h2>
      @if (history().length) {
        <div class="data-table">
          <table>
            <thead>
              <tr>
                <th scope="col">Check</th>
                <th scope="col">Result</th>
                <th scope="col">Started</th>
                <th scope="col" class="num">Took</th>
                <th scope="col">By</th>
                <th scope="col"><span class="visually-hidden">Output</span></th>
              </tr>
            </thead>
            <tbody>
              @for (record of history(); track record.id) {
                <tr>
                  <td>{{ label(record.job) }}</td>
                  <td>
                    <span class="state {{ states[record.status].tone }}">{{
                      states[record.status].label
                    }}</span>
                  </td>
                  <td>{{ when(record.started_at) }}</td>
                  <td class="num">{{ seconds(record) }}</td>
                  <td>{{ record.started_by === auth.user()?.id ? 'You' : 'Another admin' }}</td>
                  <td><button type="button" class="tool" (click)="show(record)">Output</button></td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else {
        <p class="settings-hint">No checks have been run yet.</p>
      }
    </section>
  `,
  styles: `
    .jobs {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr));
      gap: var(--space-4);
      margin-bottom: var(--space-5);
    }
    .job {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      padding: var(--space-4);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      background: var(--surface);
      box-shadow: var(--shadow-1);
    }
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
    }
    h2 {
      margin: 0;
      font-size: var(--text-base);
    }
    .head .state {
      white-space: normal;
    }
    .description {
      flex: 1;
      margin: 0;
      color: var(--text-muted);
      font-size: var(--text-sm);
    }
    .choice {
      display: grid;
      gap: var(--space-1);
      font-size: var(--text-xs);
      font-weight: var(--weight-medium);
    }
    .choice select {
      min-height: 2rem;
      appearance: auto;
      font-size: var(--text-sm);
    }
    .foot {
      display: flex;
      align-items: center;
      gap: var(--space-2);
    }
    .run {
      margin-left: auto;
      min-height: 2rem;
    }
    .when {
      color: var(--text-subtle);
      font-size: var(--text-xs);
    }
    .output {
      margin-bottom: var(--space-5);
    }
    .output-head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-3);
      margin-bottom: var(--space-3);
    }
    .output-head h2 {
      font-size: var(--text-lg);
    }
    .cancel {
      margin-left: auto;
      min-height: 2rem;
    }
    .verdict {
      margin: 0 0 var(--space-3);
      font-weight: var(--weight-medium);
    }
    .failed {
      margin: 0 0 var(--space-3);
      padding-left: var(--space-5);
      color: var(--danger);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }
    .log {
      max-height: 26rem;
      overflow: auto;
      white-space: pre;
    }
  `,
})
export class ChecksSection implements OnInit, OnDestroy {
  private readonly admin = inject(AdminApi);
  private readonly confirm = inject(Confirm);
  protected readonly auth = inject(Auth);

  protected readonly jobs = signal<JobInfo[]>([]);
  protected readonly history = signal<RunRecord[]>([]);
  protected readonly shown = signal<Shown | null>(null);
  protected readonly problem = signal<string | null>(null);
  private readonly choices = signal<Record<string, Record<string, string>>>({});
  protected readonly states = RUN_STATES;
  protected readonly when = formatWhen;

  protected readonly running = computed(() => !!this.shown()?.following);
  protected readonly busy = computed(
    () => this.running() || this.jobs().some((job) => job.running),
  );

  private readonly log = viewChild<ElementRef<HTMLElement>>('log');
  private abort: AbortController | null = null;

  constructor() {
    // Keep the newest output in view while a run is followed.
    afterRenderEffect(() => {
      const run = this.shown();
      const element = this.log()?.nativeElement;
      if (run?.following && element) {
        element.scrollTop = element.scrollHeight;
      }
    });
  }

  async ngOnInit(): Promise<void> {
    await this.refresh();
    // A check started before this page was opened is followed from where it is.
    const running = this.jobs().find((job) => job.running && job.latest);
    if (running?.latest) {
      void this.follow(running.latest.id, running.id);
    }
  }

  ngOnDestroy(): void {
    this.abort?.abort();
  }

  protected label(job: string): string {
    return this.jobs().find((item) => item.id === job)?.label ?? job;
  }

  protected seconds(record: RunRecord): string {
    return duration(record.summary.seconds);
  }

  protected chosen(job: string, name: string, fallback: string): string {
    return this.choices()[job]?.[name] ?? fallback;
  }

  protected choose(job: string, name: string, value: string): void {
    this.choices.update((all) => ({ ...all, [job]: { ...all[job], [name]: value } }));
  }

  protected async start(job: JobInfo): Promise<void> {
    if (job.paid) {
      const confirmed = await this.confirm.ask({
        title: `Run ${job.label}?`,
        message: `This calls the model and costs money: ${job.cost}.`,
        confirm: 'Run it',
      });
      if (!confirmed) {
        return;
      }
    }
    this.problem.set(null);
    const settings: Record<string, string> = {};
    for (const choice of job.choices) {
      settings[choice.name] = this.chosen(job.id, choice.name, choice.default);
    }
    try {
      const run = await this.admin.startRun(job.id, settings);
      void this.follow(run.id, job.id);
      await this.refresh();
    } catch (error) {
      this.problem.set(
        error instanceof ApiError ? error.message : 'The check could not be started.',
      );
    }
  }

  protected async cancel(id: string): Promise<void> {
    try {
      await this.admin.cancelRun(id);
    } catch (error) {
      this.problem.set(error instanceof ApiError ? error.message : 'It could not be cancelled.');
    }
  }

  /** Show a finished run's kept output. */
  protected async show(record: RunRecord): Promise<void> {
    if (this.running()) {
      return;
    }
    const full = await this.admin.run(record.id);
    this.shown.set({
      id: full.id,
      job: full.job,
      record: full,
      lines: (full.output ?? '').split('\n'),
      following: false,
    });
  }

  private async follow(id: string, job: string): Promise<void> {
    this.abort?.abort();
    this.abort = new AbortController();
    this.shown.set({ id, job, record: null, lines: [], following: true });
    try {
      for await (const event of this.admin.follow(id, this.abort.signal)) {
        if (event.type === 'line') {
          this.shown.update((run) =>
            run && run.id === id
              ? { ...run, lines: [...run.lines, event.text].slice(-MAX_SCREEN_LINES) }
              : run,
          );
        } else {
          this.shown.update((run) =>
            run && run.id === id ? { ...run, record: event.run, following: false } : run,
          );
        }
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        this.problem.set('Following the output stopped. The check goes on; reload to see it.');
      }
    } finally {
      this.shown.update((run) => (run && run.id === id ? { ...run, following: false } : run));
      await this.refresh();
    }
  }

  private async refresh(): Promise<void> {
    try {
      const [jobs, history] = await Promise.all([this.admin.jobs(), this.admin.runs()]);
      this.jobs.set(jobs);
      this.history.set(history);
    } catch {
      this.problem.set('The checks could not be loaded.');
    }
  }
}
