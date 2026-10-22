import {
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';

import { Chart } from '../api/types';
import { formatValue, isNumber, layoutChart, shortLabel } from './chart-scale';

const DEFAULT_WIDTH = 640;

/**
 * One chart of an answer. The values were read by the service from the cited query's rows,
 * and only the title was written by the model. Every label is bound as text, never as HTML.
 *
 * Hovering, or focusing the plot and using the arrow keys, shows every series at one
 * category. The values are also always in the query's table, which the source button opens.
 */
@Component({
  selector: 'app-chart-view',
  templateUrl: './chart-view.html',
  styleUrl: './chart-view.css',
})
export class ChartView {
  readonly chart = input.required<Chart>();
  /** Asks the answer to open the query the chart was drawn from. */
  readonly source = output<number>();

  private readonly host: ElementRef<HTMLElement> = inject(ElementRef);
  protected readonly width = signal(DEFAULT_WIDTH);
  protected readonly active = signal<number | null>(null);

  protected readonly layout = computed(() => layoutChart(this.chart(), this.width()));
  protected readonly multi = computed(() => this.chart().series.length > 1);
  protected readonly description = computed(() => {
    const chart = this.chart();
    const names = chart.series.map((series) => series.name).join(', ');
    return (
      `${chart.kind === 'bar' ? 'Bar' : 'Line'} chart: ${chart.title}. ` +
      `${chart.x.length} ${chart.x_label} values` +
      (this.multi() ? `, series ${names}.` : '.') +
      (chart.query_number > 0 ? ` The values are in the table of query ${chart.query_number}.` : '')
    );
  });
  /** End labels for up to four lines, dropped if any two would collide. */
  protected readonly endLabels = computed(() => {
    const layout = this.layout();
    if (this.chart().kind !== 'line' || layout.lines.length > 4) {
      return [];
    }
    const labels = layout.lines
      .filter((line) => line.points.length)
      .map((line) => {
        const last = line.points[line.points.length - 1];
        const value = this.chart().series[line.series].values[last.index] as number;
        return { series: line.series, x: last.x, y: last.y, text: formatValue(value) };
      });
    const ys = labels.map((label) => label.y).sort((a, b) => a - b);
    return ys.every((y, index) => index === 0 || y - ys[index - 1] >= 14) ? labels : [];
  });
  protected readonly readout = computed(() => {
    const index = this.active();
    if (index === null) {
      return null;
    }
    const chart = this.chart();
    const slot = this.layout().slots[index];
    return {
      label: chart.x[index],
      // Beside the hovered category, on whichever side has more room, so it never
      // covers the point being read.
      left: slot.x < this.width() / 2 ? slot.x + slot.width / 2 + 8 : null,
      right: slot.x < this.width() / 2 ? null : this.width() - slot.x + slot.width / 2 + 8,
      rows: chart.series.map((series, s) => ({
        series: s,
        name: series.name,
        value: isNumber(series.values[index])
          ? formatValue(series.values[index] as number)
          : 'no value',
      })),
    };
  });

  protected readonly format = formatValue;
  protected readonly short = shortLabel;

  constructor() {
    const destroyRef = inject(DestroyRef);
    afterNextRender(() => {
      const element = this.host.nativeElement;
      if (typeof ResizeObserver === 'undefined') {
        return;
      }
      const observer = new ResizeObserver(([entry]) => {
        const measured = Math.round(entry.contentRect.width);
        if (measured > 0) {
          this.width.set(measured);
        }
      });
      observer.observe(element);
      destroyRef.onDestroy(() => observer.disconnect());
    });
  }

  protected point(index: number): void {
    this.active.set(index);
  }

  protected leave(): void {
    this.active.set(null);
  }

  protected step(event: KeyboardEvent): void {
    const last = this.chart().x.length - 1;
    const current = this.active();
    const moves: Record<string, number> = {
      ArrowRight: current === null ? 0 : Math.min(current + 1, last),
      ArrowLeft: current === null ? last : Math.max(current - 1, 0),
      Home: 0,
      End: last,
    };
    if (event.key in moves) {
      event.preventDefault();
      this.active.set(moves[event.key]);
    } else if (event.key === 'Escape') {
      this.active.set(null);
    }
  }

  protected seriesClass(index: number): string {
    return `s${(index % 8) + 1}`;
  }
}
