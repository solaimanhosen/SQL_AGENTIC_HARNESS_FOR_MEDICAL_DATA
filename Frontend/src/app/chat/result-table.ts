import { Component, computed, input, signal } from '@angular/core';

export const PREVIEW_ROWS = 10;

/**
 * The rows one query returned. Short results are shown whole, longer ones start with a
 * preview. Cells are rendered as text: they come straight from the database.
 */
@Component({
  selector: 'app-result-table',
  template: `
    <div class="scroll" tabindex="0" role="region" [attr.aria-label]="label()">
      <table>
        <thead>
          <tr>
            @for (column of columns(); track $index) {
              <th scope="col" [class.num]="numeric()[$index]">{{ column }}</th>
            }
          </tr>
        </thead>
        <tbody>
          @for (row of shown(); track $index) {
            <tr>
              @for (cell of row; track $index) {
                @if (cell === null) {
                  <td class="null">null</td>
                } @else {
                  <td [class.num]="isNumber(cell)">{{ cell }}</td>
                }
              }
            </tr>
          }
        </tbody>
      </table>
    </div>
    @if (hidden()) {
      <button type="button" class="tool" (click)="all.set(true)">
        Show all {{ rows().length }} rows
      </button>
    }
  `,
  styles: `
    :host {
      display: block;
      min-width: 0;
    }
    .scroll {
      overflow-x: auto;
      margin-top: 0.4rem;
      border: 1px solid var(--border);
      border-radius: 0.4rem;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }
    th,
    td {
      padding: 0.3rem 0.6rem;
      text-align: left;
      vertical-align: top;
      overflow-wrap: normal;
    }
    th {
      background: var(--code-bg);
      color: var(--text-muted);
      font-weight: 600;
      white-space: nowrap;
    }
    tbody tr + tr td {
      border-top: 1px solid var(--border);
    }
    .num {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    .null {
      color: var(--text-muted);
      font-style: italic;
    }
    button {
      margin-top: 0.4rem;
    }
  `,
})
export class ResultTable {
  readonly columns = input.required<string[]>();
  readonly rows = input.required<unknown[][]>();
  readonly label = input('Query result');

  protected readonly all = signal(false);
  protected readonly shown = computed(() =>
    this.all() ? this.rows() : this.rows().slice(0, PREVIEW_ROWS),
  );
  protected readonly hidden = computed(() => !this.all() && this.rows().length > PREVIEW_ROWS);

  /** Columns whose values are all numbers, so their headers line up with the figures. */
  protected readonly numeric = computed(() =>
    this.columns().map((_, index) => {
      const values = this.rows()
        .map((row) => row[index])
        .filter((value) => value !== null);
      return values.length > 0 && values.every((value) => typeof value === 'number');
    }),
  );

  protected isNumber(cell: unknown): boolean {
    return typeof cell === 'number';
  }
}
