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

/**
 * The SQL behind an answer, as the service recorded it while it ran. Successful queries carry
 * the numbers the findings cite. Failed attempts are kept apart, since no figure came from them.
 */
@Component({
  selector: 'app-query-list',
  templateUrl: './query-list.html',
  styleUrl: './query-list.css',
})
export class QueryList {
  readonly queries = input.required<QueryRecord[]>();

  private readonly host: ElementRef<HTMLElement> = inject(ElementRef);
  private readonly injector = inject(Injector);

  protected readonly open = signal(false);
  protected readonly lit = signal<number | null>(null);
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
