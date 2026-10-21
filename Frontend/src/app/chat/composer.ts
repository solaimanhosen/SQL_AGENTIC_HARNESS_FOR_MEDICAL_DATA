import { Component, computed, input, output, signal } from '@angular/core';
import { LucideArrowUp } from '@lucide/angular';

import { ModelCatalog, ModelChoice } from '../api/types';
import { MAX_QUESTION_CHARS } from './chat-store';
import { ModelPicker } from './model-picker';

/** The question box. Enter sends, Shift+Enter starts a new line. */
@Component({
  selector: 'app-composer',
  imports: [LucideArrowUp, ModelPicker],
  template: `
    <form class="composer" (submit)="send($event)">
      <label class="visually-hidden" for="question">Your question</label>
      <textarea
        id="question"
        rows="2"
        [placeholder]="placeholder()"
        [value]="text()"
        [attr.maxlength]="max"
        (input)="text.set($any($event.target).value)"
        (keydown.enter)="onEnter($any($event))"
      ></textarea>
      <div class="actions">
        <app-model-picker
          class="picker"
          [catalog]="catalog()"
          [choice]="choice()"
          [disabled]="busy()"
          (choiceChange)="choiceChange.emit($event)"
        />
        @if (text().length > max * 0.8) {
          <span class="count">{{ text().length }} / {{ max }}</span>
        }
        <button
          type="submit"
          class="icon send"
          aria-label="Ask"
          title="Ask"
          [disabled]="!canSend()"
        >
          <svg lucideArrowUp [size]="18"></svg>
        </button>
      </div>
    </form>
  `,
  styles: `
    .composer {
      display: grid;
      gap: var(--space-1);
      padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-xl);
      background: var(--surface);
      box-shadow: var(--shadow-2);
      transition: border-color var(--duration-fast) var(--ease);
    }
    .composer:focus-within {
      border-color: var(--accent);
      box-shadow:
        0 0 0 3px var(--focus-ring),
        var(--shadow-2);
    }
    textarea {
      width: 100%;
      min-height: 3rem;
      padding: var(--space-2) 0 0;
      border: 0;
      resize: none;
      background: transparent;
      font-size: var(--text-base);
      line-height: var(--leading);
    }
    textarea:focus-visible {
      outline: none;
    }
    textarea::placeholder {
      color: var(--text-subtle);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--space-2);
    }
    .picker {
      flex: 1;
      margin-left: calc(-1 * var(--space-2));
    }
    .count {
      color: var(--text-subtle);
      font-size: var(--text-xs);
      font-variant-numeric: tabular-nums;
    }
    .send {
      border-radius: var(--radius-full);
    }
  `,
})
export class Composer {
  readonly busy = input(false);
  readonly placeholder = input('Ask a question about the patient data');
  readonly ask = output<string>();
  readonly catalog = input<ModelCatalog | null>(null);
  readonly choice = input<ModelChoice | null>(null);
  readonly choiceChange = output<ModelChoice>();

  protected readonly max = MAX_QUESTION_CHARS;
  protected readonly text = signal('');
  protected readonly canSend = computed(() => !this.busy() && this.text().trim().length > 0);

  protected onEnter(event: KeyboardEvent): void {
    if (event.shiftKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    this.send();
  }

  protected send(event?: Event): void {
    event?.preventDefault();
    if (!this.canSend()) {
      return;
    }
    this.ask.emit(this.text().trim());
    this.text.set('');
  }
}
