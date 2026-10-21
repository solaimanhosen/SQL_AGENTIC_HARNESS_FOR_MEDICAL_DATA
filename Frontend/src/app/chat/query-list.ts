import {
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';

import { QueryRecord } from '../api/types';
import { Exporter, toCsv } from './export';
import { ResultTable } from './result-table';

/**
 * The SQL behind an answer, as the service recorded it while it ran. Successful queries carry
 * the numbers the findings cite. Failed attempts are kept apart, since no figure came from them.
 */
@Component({
  selector: 'app-query-list',
  imports: [ResultTable],
  templateUrl: './query-list.html',
  styleUrl: './query-list.css',
})
export class QueryList {
  readonly queries = input.required<QueryRecord[]>();
  /** Start of each CSV file name, tying it to the conversation and question. */
  readonly fileStem = input('answer');

  private readonly host: ElementRef<HTMLElement> = inject(ElementRef);
  private readonly injector = inject(Injector);
  private readonly exporter = inject(Exporter);

  protected readonly open = signal(false);
  protected readonly lit = signal<number | null>(null);
  /** The query whose copy button was just used, and whether the copy worked. */
  protected readonly copied = signal<{ number: number | null; ok: boolean } | null>(null);
  protected readonly ran = computed(() => this.queries().filter((query) => query.ok));
  protected readonly failed = computed(() => this.queries().filter((query) => !query.ok));

  /** Open the panel and bring one query into view, for a citation that was clicked. */
  reveal(number: number): void {
    this.open.set(true);
    this.lit.set(number);
    afterNextRender(
      () => {
        const target = this.host.nativeElement.querySelector<HTMLElement>(
          `[data-query="${number}"]`,
        );
        target?.scrollIntoView?.({ block: 'nearest' });
        target?.focus({ preventScroll: true });
      },
      { injector: this.injector },
    );
  }

  protected async copySql(query: QueryRecord): Promise<void> {
    const ok = await this.exporter.copy(query.sql);
    const mark = { number: query.number, ok };
    this.copied.set(mark);
    setTimeout(() => this.copied() === mark && this.copied.set(null), 2000);
  }

  protected copyLabel(query: QueryRecord): string {
    const mark = this.copied();
    if (mark?.number !== query.number) {
      return 'Copy SQL';
    }
    return mark.ok ? 'Copied' : 'Copy failed';
  }

  protected downloadCsv(query: QueryRecord): void {
    this.exporter.saveCsv(
      `${this.fileStem()}-query${query.number}.csv`,
      toCsv(query.columns, query.rows),
    );
  }

  /** True for a stored answer whose rows were left out, by the service's setting. */
  protected rowsLeftOut(query: QueryRecord): boolean {
    return !query.rows.length && (query.row_count ?? 0) > 0;
  }

  protected onToggle(event: Event): void {
    this.open.set((event.target as HTMLDetailsElement).open);
  }

  protected summary(query: QueryRecord): string {
    const rows = query.row_count ?? 0;
    const parts = [`${rows} ${rows === 1 ? 'row' : 'rows'}`];
    if (query.elapsed_ms !== null) {
      parts.push(`${Math.round(query.elapsed_ms)} ms`);
    }
    return parts.join(' in ');
  }
}
