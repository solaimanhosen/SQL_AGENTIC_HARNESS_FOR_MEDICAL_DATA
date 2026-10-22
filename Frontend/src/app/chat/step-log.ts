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
      gap: var(--space-1-5);
      margin: var(--space-2-5) 0 0;
      padding-left: var(--space-6);
      font-size: var(--text-sm);
      color: var(--text-muted);
    }
    pre {
      margin-top: var(--space-1);
    }
    .bad span,
    .detail {
      color: var(--warning-text);
    }
    .detail {
      margin: var(--space-1) 0 0;
    }
  `,
})
export class StepLog {
  readonly steps = input.required<Step[]>();
  protected readonly describe = describeStep;
}
