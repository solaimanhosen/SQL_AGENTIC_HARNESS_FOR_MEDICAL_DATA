import { Component, input } from '@angular/core';

import { Step } from '../api/types';
import { describeStep } from './steps';

/** Every step the agent took, in order, with the SQL it ran. */
@Component({
  selector: 'app-step-log',
  template: `
    <ol class="steps">
      @for (step of steps(); track $index) {
        <li [class.bad]="step.kind === 'sql_error'">
          <span>{{ describe(step) }}</span>
          @if (step.kind === 'sql') {
            <pre><code>{{ step.detail }}</code></pre>
          } @else if (step.kind === 'sql_error') {
            <p class="detail">{{ step.detail }}</p>
          }
        </li>
      }
    </ol>
  `,
  styles: `
    .steps {
      display: grid;
      gap: 0.4rem;
      margin: 0.6rem 0 0;
      padding-left: 1.4rem;
      font-size: 0.85rem;
      color: var(--text-muted);
    }
    pre {
      margin-top: 0.3rem;
    }
    .bad span,
    .detail {
      color: var(--warning-text);
    }
    .detail {
      margin: 0.2rem 0 0;
    }
  `,
})
export class StepLog {
  readonly steps = input.required<Step[]>();
  protected readonly describe = describeStep;
}
