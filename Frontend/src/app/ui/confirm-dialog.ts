import { DIALOG_DATA, Dialog, DialogRef } from '@angular/cdk/dialog';
import { Component, Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

export interface ConfirmOptions {
  title: string;
  /** Plain text. Titles typed by users may appear in it, so it is never read as HTML. */
  message: string;
  confirm: string;
  cancel?: string;
  /** Draws the confirm button in the danger colour, for actions that cannot be undone. */
  danger?: boolean;
}

/**
 * A small modal that asks before an action. The CDK dialog traps focus inside it, closes on
 * Escape, and returns focus to whatever opened it. Cancel has the initial focus, so pressing
 * Enter by habit never confirms something destructive.
 */
@Component({
  selector: 'app-confirm-dialog',
  template: `
    <div class="dialog">
      <h2 id="confirm-title">{{ options.title }}</h2>
      <p id="confirm-message">{{ options.message }}</p>
      <div class="actions">
        <button type="button" class="secondary" cdkFocusInitial (click)="ref.close(false)">
          {{ options.cancel ?? 'Cancel' }}
        </button>
        <button
          type="button"
          class="confirm"
          [class.danger]="options.danger"
          (click)="ref.close(true)"
        >
          {{ options.confirm }}
        </button>
      </div>
    </div>
  `,
  styles: `
    .dialog {
      width: min(26rem, calc(100vw - 2 * var(--space-4)));
      padding: var(--space-5);
      border: 1px solid var(--border);
      border-radius: var(--radius-xl);
      background: var(--surface);
      box-shadow: var(--shadow-3);
    }
    h2 {
      margin: 0 0 var(--space-2);
      font-size: var(--text-lg);
    }
    p {
      margin: 0;
      color: var(--text-muted);
      overflow-wrap: anywhere;
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: var(--space-2);
      margin-top: var(--space-5);
    }
  `,
})
export class ConfirmDialog {
  protected readonly options = inject<ConfirmOptions>(DIALOG_DATA);
  protected readonly ref = inject<DialogRef<boolean>>(DialogRef);
}

@Injectable({ providedIn: 'root' })
export class Confirm {
  private readonly dialog = inject(Dialog);

  /** Resolves true only if the confirm button was pressed. */
  ask(options: ConfirmOptions): Promise<boolean> {
    const ref = this.dialog.open<boolean>(ConfirmDialog, {
      data: options,
      role: 'alertdialog',
      ariaModal: true,
      ariaLabelledBy: 'confirm-title',
      ariaDescribedBy: 'confirm-message',
      backdropClass: 'dialog-backdrop',
    });
    return firstValueFrom(ref.closed).then((result) => result === true);
  }
}
