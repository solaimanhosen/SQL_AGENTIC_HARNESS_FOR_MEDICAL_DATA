import { Component, output, signal } from '@angular/core';

/**
 * Asks for the service's shared access token after a question was refused without it. The
 * token stays in memory for this page only and is never saved to browser storage.
 */
@Component({
  selector: 'app-token-prompt',
  template: `
    <form class="token card" (submit)="submit($event)">
      <label for="token">This service needs its access token.</label>
      <div class="row">
        <input
          id="token"
          class="field"
          type="password"
          autocomplete="off"
          [value]="token()"
          (input)="token.set($any($event.target).value)"
        />
        <button type="submit" [disabled]="!token().trim()">Use token</button>
      </div>
      <p class="hint">It is kept only until this page is closed or reloaded.</p>
    </form>
  `,
  styles: `
    .token {
      display: grid;
      gap: var(--space-2);
    }
    label {
      font-weight: var(--weight-medium);
    }
    .row {
      display: flex;
      gap: var(--space-2);
    }
    .hint {
      margin: 0;
      color: var(--text-subtle);
      font-size: var(--text-xs);
    }
  `,
})
export class TokenPrompt {
  readonly save = output<string>();
  protected readonly token = signal('');

  protected submit(event: Event): void {
    event.preventDefault();
    const token = this.token().trim();
    if (token) {
      this.save.emit(token);
      this.token.set('');
    }
  }
}
