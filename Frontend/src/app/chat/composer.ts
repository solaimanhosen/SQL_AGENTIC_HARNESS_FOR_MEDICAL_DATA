import { Component, computed, input, output, signal } from '@angular/core';

import { MAX_QUESTION_CHARS } from './chat-store';

/** The question box. Enter sends, Shift+Enter starts a new line. */
@Component({
  selector: 'app-composer',
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
        @if (text().length > max * 0.8) {
          <span class="count">{{ text().length }} / {{ max }}</span>
        }
        <button type="submit" [disabled]="!canSend()">Ask</button>
      </div>
    </form>
  `,
  styles: `
    .composer {
      display: flex;
      gap: 0.6rem;
      align-items: flex-end;
    }
    textarea {
      flex: 1;
      resize: none;
      padding: 0.65rem 0.8rem;
      border: 1px solid var(--border);
      border-radius: 0.6rem;
      background: var(--surface);
      color: var(--text);
      font: inherit;
    }
    textarea:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 1px;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .count {
      color: var(--text-muted);
      font-size: 0.8rem;
    }
  `,
})
export class Composer {
  readonly busy = input(false);
  readonly placeholder = input('Ask a question about the patient data');
  readonly ask = output<string>();

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
