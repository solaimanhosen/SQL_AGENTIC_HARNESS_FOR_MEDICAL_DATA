import { Component } from '@angular/core';

import { ThemeToggle } from '../ui/theme-toggle';

/**
 * The frame every signed-out page shares: the theme menu, a centred card with the brand, and
 * the note about where questions go. The page's own content goes inside the card, styled by
 * `auth-form.css`.
 */
@Component({
  selector: 'app-auth-shell',
  imports: [ThemeToggle],
  template: `
    <div class="corner"><app-theme-toggle /></div>
    <main class="auth">
      <div class="card panel">
        <p class="brand">
          <span class="mark" aria-hidden="true">PQ</span>
          <span>Patient data questions</span>
        </p>
        <ng-content />
      </div>
      <p class="note">
        Synthetic Synthea data. Questions and results are sent to the Anthropic API.
      </p>
    </main>
  `,
  styles: `
    :host {
      display: block;
      min-height: 100dvh;
      background:
        radial-gradient(60rem 30rem at 50% -10%, var(--accent-soft), transparent 70%), var(--bg);
    }
    .corner {
      position: absolute;
      top: var(--space-2-5);
      right: var(--space-4);
    }
    .auth {
      display: grid;
      justify-items: center;
      align-content: center;
      gap: var(--space-4);
      min-height: 100dvh;
      padding: var(--space-8) var(--space-4);
    }
    .panel {
      width: min(24rem, 100%);
      padding: var(--space-8) var(--space-6);
      box-shadow: var(--shadow-2);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      margin: 0 0 var(--space-6);
      font-size: var(--text-sm);
      font-weight: var(--weight-semibold);
    }
    .mark {
      display: grid;
      place-items: center;
      width: 1.75rem;
      height: 1.75rem;
      border-radius: var(--radius-md);
      background: var(--accent);
      color: var(--on-accent);
      font-size: 0.6875rem;
      font-weight: 700;
    }
    .note {
      margin: 0;
      color: var(--text-subtle);
      font-size: var(--text-xs);
      text-align: center;
    }
  `,
})
export class AuthShell {}
