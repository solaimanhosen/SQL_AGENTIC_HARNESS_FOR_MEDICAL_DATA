import { Component, computed, input, output } from '@angular/core';

import { AnswerView } from './answer-view';
import { Exchange } from './chat-store';
import { StepLog } from './step-log';
import { describeStep, queriesRun } from './steps';

/**
 * One question and what became of it: the live steps while the agent works, then the answer
 * or the failure. Every string from the service is rendered through Angular interpolation,
 * which escapes it: stored data can carry injected text, and the agent is told to quote such
 * text when it reports it, so nothing here or in the views below is ever treated as HTML.
 */
@Component({
  selector: 'app-exchange-view',
  imports: [AnswerView, StepLog],
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
}
