import { TestBed } from '@angular/core/testing';

import { Chart } from '../api/types';
import { ChartView } from './chart-view';

const TWO_GROUPS: Chart = {
  kind: 'bar',
  title: 'Share with an ER visit',
  query_number: 3,
  x_label: 'grp',
  y_label: 'rate_pct',
  x: ['diabetic', 'non-diabetic'],
  series: [{ name: 'rate_pct', values: [37.5, 12] }],
};

const MONTHLY: Chart = {
  kind: 'line',
  title: 'Monthly visits',
  query_number: 2,
  x_label: 'month',
  y_label: 'visits',
  x: ['2026-05', '2026-06', '2026-07'],
  series: [
    { name: 'diabetic', values: [5, 7, null] },
    { name: 'non-diabetic', values: [1, 0, 3] },
  ],
};

async function render(chart: Chart) {
  const fixture = TestBed.createComponent(ChartView);
  fixture.componentRef.setInput('chart', chart);
  await fixture.whenStable();
  return { fixture, element: fixture.nativeElement as HTMLElement };
}

function text(element: Element | null): string {
  return (element?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

describe('ChartView', () => {
  it('draws one bar per value with its value at the tip, and no legend for one series', async () => {
    const { element } = await render(TWO_GROUPS);
    expect(text(element.querySelector('.title'))).toBe('Share with an ER visit');
    expect(element.querySelectorAll('path.bar').length).toBe(2);
    expect([...element.querySelectorAll('text.value')].map(text)).toEqual(['37.5', '12']);
    expect(element.querySelector('.legend')).toBeNull();
    expect(element.querySelector('svg')?.getAttribute('aria-label')).toBe(
      'Bar chart: Share with an ER visit. 2 grp values. The values are in the table of query 3.',
    );
  });

  it('gives several series a legend and a colour each, in a fixed order', async () => {
    const { element } = await render(MONTHLY);
    expect([...element.querySelectorAll('.legend li')].map(text)).toEqual([
      'diabetic',
      'non-diabetic',
    ]);
    const lines = [...element.querySelectorAll('path.line')];
    expect(lines[0].classList.contains('s1')).toBe(true);
    expect(lines[1].classList.contains('s2')).toBe(true);
  });

  it('opens the source query', async () => {
    const { fixture, element } = await render(TWO_GROUPS);
    const opened: number[] = [];
    fixture.componentInstance.source.subscribe((number) => opened.push(number));
    element.querySelector<HTMLButtonElement>('figcaption .cite')!.click();
    expect(opened).toEqual([3]);
    expect(text(element.querySelector('figcaption .cite'))).toBe('Query 3');
  });

  it('reads out every series at one category from the keyboard', async () => {
    const { fixture, element } = await render(MONTHLY);
    const svg = element.querySelector('svg')!;
    svg.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
    svg.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
    await fixture.whenStable();
    expect(text(element.querySelector('.readout .at'))).toBe('2026-06');
    expect(
      [...element.querySelectorAll('.readout .row')].map((row) => [
        text(row.querySelector('strong')),
        text(row.querySelector('.name')),
      ]),
    ).toEqual([
      ['7', 'diabetic'],
      ['0', 'non-diabetic'],
    ]);

    svg.dispatchEvent(new KeyboardEvent('keydown', { key: 'End' }));
    await fixture.whenStable();
    expect(text(element.querySelector('.readout .row strong'))).toBe('no value');

    svg.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await fixture.whenStable();
    expect(element.querySelector('.readout')).toBeNull();
  });

  it('reads out the category under the pointer', async () => {
    const { fixture, element } = await render(TWO_GROUPS);
    element.querySelectorAll('rect.hit')[1].dispatchEvent(new Event('pointerenter'));
    await fixture.whenStable();
    expect(text(element.querySelector('.readout .at'))).toBe('non-diabetic');
    expect(element.querySelector('rect.wash')).not.toBeNull();
  });

  it('shows labels from the data as text, never as markup', async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    const { element } = await render({
      ...MONTHLY,
      title: hostile,
      x: [hostile, 'b', 'c'],
      series: [
        { name: hostile, values: [1, 2, 3] },
        { name: 'other', values: [3, 2, 1] },
      ],
    });
    expect(element.querySelector('img')).toBeNull();
    expect(text(element.querySelector('.title'))).toBe(hostile);
    expect(text(element.querySelector('.legend li'))).toBe(hostile);
  });
});
