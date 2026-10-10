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
      gap: 0.5rem;
      padding: 0.9rem 1.1rem;
      border: 1px solid var(--border);
      border-radius: 0.75rem;
      background: var(--surface);
    }
    .row {
      display: flex;
      gap: 0.5rem;
    }
    input {
      flex: 1;
      padding: 0.5rem 0.7rem;
      border: 1px solid var(--border);
      border-radius: 0.5rem;
      background: var(--bg);
      color: var(--text);
      font: inherit;
    }
    .hint {
      margin: 0;
      color: var(--text-muted);
      font-size: 0.8rem;
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
