import { Component, Injectable, inject, signal } from '@angular/core';
import { LucideCircleAlert, LucideX } from '@lucide/angular';

export interface Toast {
  id: number;
  message: string;
  tone: 'info' | 'error';
}

/** How long a toast stays, unless closed sooner. */
export const TOAST_MS = 6000;

/**
 * Short notices for things that happen out of sight, such as a rename that could not be
 * saved. They are announced to screen readers and fade on their own.
 */
@Injectable({ providedIn: 'root' })
export class Toasts {
  readonly items = signal<Toast[]>([]);
  private nextId = 1;

  show(message: string, tone: Toast['tone'] = 'info'): void {
    const id = this.nextId++;
    this.items.update((items) => [...items.slice(-2), { id, message, tone }]);
    setTimeout(() => this.close(id), TOAST_MS);
  }

  error(message: string): void {
    this.show(message, 'error');
  }

  close(id: number): void {
    this.items.update((items) => items.filter((item) => item.id !== id));
  }
}

/** Where toasts appear: the bottom-right corner, above everything. */
@Component({
  selector: 'app-toasts',
  imports: [LucideCircleAlert, LucideX],
  template: `
    <div class="stack" role="status" aria-live="polite">
      @for (toast of toasts.items(); track toast.id) {
        <div class="toast" [class.error]="toast.tone === 'error'">
          @if (toast.tone === 'error') {
            <svg lucideCircleAlert [size]="16" aria-hidden="true"></svg>
          }
          <p>{{ toast.message }}</p>
          <button
            type="button"
            class="ghost icon sm"
            aria-label="Dismiss"
            title="Dismiss"
            (click)="toasts.close(toast.id)"
          >
            <svg lucideX [size]="14"></svg>
          </button>
        </div>
      }
    </div>
  `,
  styles: `
    .stack {
      position: fixed;
      right: var(--space-4);
      bottom: var(--space-4);
      z-index: 1100;
      display: grid;
      gap: var(--space-2);
      width: min(22rem, calc(100vw - 2 * var(--space-4)));
      pointer-events: none;
    }
    .toast {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      background: var(--surface);
      box-shadow: var(--shadow-3);
      font-size: var(--text-sm);
      pointer-events: auto;
      animation: rise var(--duration) var(--ease);
    }
    .toast.error {
      border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
    }
    .toast.error svg {
      color: var(--danger);
    }
    p {
      flex: 1;
      margin: 0;
    }
    @keyframes rise {
      from {
        opacity: 0;
        transform: translateY(0.5rem);
      }
    }
  `,
})
export class ToastHost {
  protected readonly toasts = inject(Toasts);
}
