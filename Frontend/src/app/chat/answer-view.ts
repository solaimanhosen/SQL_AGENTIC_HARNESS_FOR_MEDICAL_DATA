import { Component, computed, inject, input, signal, viewChild } from '@angular/core';

import { AgentApi, ApiError } from '../api/agent-api';
import { Answer, DefinitionStatus, Step } from '../api/types';
import { Exporter, answerJson, fileStem } from './export';
import { ChartView } from './chart-view';
import { QueryList } from './query-list';
import { StepLog } from './step-log';

const STATUS_LABELS: Record<DefinitionStatus, string> = {
  confirmed: 'Confirmed',
  assumed: 'Assumed, not yet confirmed',
  unknown: 'Not a shared definition',
};

/**
 * An answer with everything behind it: the findings and the queries they cite, the time
 * window, the definitions and their status, assumptions, caveats, the SQL that ran, and
 * anything the service could not trace. It shows what the command line shows.
 *
 * Nothing exact is worked out here. Definition statuses, window dates and traceability
 * warnings all arrive from the service's own records and are only laid out.
 */
@Component({
  selector: 'app-answer-view',
  imports: [ChartView, QueryList, StepLog],
  templateUrl: './answer-view.html',
  styleUrl: './answer-view.css',
})
export class AnswerView {
  readonly answer = input.required<Answer>();
  readonly steps = input<Step[]>([]);

  private readonly queryList = viewChild(QueryList);
  private readonly exporter = inject(Exporter);
  private readonly api = inject(AgentApi);

  /** True while the report is being made, and the reason when it could not be. */
  protected readonly reporting = signal(false);
  protected readonly reportError = signal<string | null>(null);

  protected readonly stem = computed(() => fileStem(this.answer()));

  private readonly ranNumbers = computed(
    () =>
      new Set(
        this.answer()
          .queries.filter((query) => query.ok)
          .map((query) => query.number),
      ),
  );
  protected readonly ranCount = computed(() => this.ranNumbers().size);
  protected readonly failedCount = computed(
    () => this.answer().queries.filter((query) => !query.ok).length,
  );

  /** What the run took, as the last line of the command line output does. */
  protected readonly meta = computed(() => {
    const answer = this.answer();
    const ran = this.ranCount();
    const failed = this.failedCount();
    const count = (value: number) => value.toLocaleString('en-US');
    return [
      `${ran} ${ran === 1 ? 'query' : 'queries'}` + (failed ? `, ${failed} failed` : ''),
      `${answer.elapsed_s}s`,
      `${count(answer.input_tokens)} in and ${count(answer.output_tokens)} out tokens`,
      answer.model,
    ].join(' · ');
  });

  protected ran(number: number): boolean {
    return this.ranNumbers().has(number);
  }

  protected showQuery(number: number): void {
    this.queryList()?.reveal(number);
  }

  /** The whole answer as the service sent it, rows included. */
  protected downloadJson(): void {
    this.exporter.save(`${this.stem()}-answer.json`, answerJson(this.answer()), 'application/json');
  }

  /**
   * The answer as one HTML file with its charts, tables and SQL, which opens with no network.
   * The service makes it from the stored answer, so it matches what was shown here.
   */
  protected async downloadReport(): Promise<void> {
    const answer = this.answer();
    this.reporting.set(true);
    this.reportError.set(null);
    try {
      const html = await this.api.report(answer.conversation_id, answer.turn);
      this.exporter.save(`${this.stem()}-report.html`, html, 'text/html;charset=utf-8');
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'The report could not be made.';
      this.reportError.set(message);
    } finally {
      this.reporting.set(false);
    }
  }

  protected statusLabel(status: DefinitionStatus): string {
    return STATUS_LABELS[status];
  }
}
