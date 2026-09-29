import { Component, computed, input, output } from '@angular/core';

import { Exchange } from './chat-store';
import { describeStep, queriesRun } from './steps';

/**
 * One question and its answer. Every string from the service is rendered through Angular
 * interpolation, which escapes it: stored data can carry injected text, and the agent is told
 * to quote such text when it reports it, so nothing here is ever treated as HTML.
 */
@Component({
  selector: 'app-exchange-view',
  templateUrl: './exchange-view.html',
  styleUrl: './exchange-view.css',
})
export class ExchangeView {
  readonly exchange = input.required<Exchange>();
  readonly retry = output<number>();

  protected readonly latestStep = computed(() => {
    const steps = this.exchange().steps;
    return steps.length ? describeStep(steps[steps.length - 1]) : 'Reading the question';
  });
  protected readonly queriesRun = computed(() => queriesRun(this.exchange().steps));
  protected readonly successfulQueries = computed(
    () => this.exchange().answer?.queries.filter((query) => query.ok).length ?? 0,
  );

  protected citation(numbers: number[]): string {
    return numbers.length ? `Query ${numbers.join(', ')}` : 'No query cited';
  }
}
