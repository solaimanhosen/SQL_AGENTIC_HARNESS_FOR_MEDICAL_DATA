import { Chart } from '../api/types';
import {
  barPath,
  formatValue,
  layoutChart,
  niceTicks,
  shortLabel,
  valueDomain,
} from './chart-scale';

function chart(overrides: Partial<Chart> = {}): Chart {
  return {
    kind: 'bar',
    title: 'Visits',
    query_number: 1,
    x_label: 'group',
    y_label: 'visits',
    x: ['diabetic', 'not diabetic'],
    series: [{ name: 'visits', values: [37.5, 12] }],
    ...overrides,
  };
}

describe('niceTicks', () => {
  // The same cases are checked for the report's charts in Backend/tests/test_charts.py.
  it.each([
    [0, 63, [0, 20, 40, 60, 80]],
    [0, 8, [0, 2, 4, 6, 8]],
    [23.5, 31, [22, 24, 26, 28, 30, 32]],
    [0, 0, [0, 0.2, 0.4, 0.6, 0.8, 1]],
    [0, 0.37, [0, 0.1, 0.2, 0.3, 0.4]],
    [-5, 12, [-5, 0, 5, 10, 15]],
    [5, 5, [0, 1, 2, 3, 4, 5]],
  ])('covers %s to %s with round steps', (lo, hi, expected) => {
    expect(niceTicks(lo, hi)).toEqual(expected);
  });
});

describe('valueDomain', () => {
  it('starts bars at zero', () => {
    expect(valueDomain(chart({ series: [{ name: 'v', values: [30, 32] }] }))).toEqual([0, 32]);
  });

  it('lets a line sit away from zero when zero would flatten it', () => {
    const line = chart({ kind: 'line', series: [{ name: 'v', values: [27, null, 31] }] });
    expect(valueDomain(line)).toEqual([27, 31]);
    const low = chart({ kind: 'line', series: [{ name: 'v', values: [3, 40] }] });
    expect(valueDomain(low)).toEqual([0, 40]);
  });
});

describe('layoutChart', () => {
  it('places one rounded bar per value, no wider than 24px, from the baseline', () => {
    const layout = layoutChart(chart(), 640);
    expect(layout.bars.length).toBe(2);
    expect(layout.bars.every((bar) => bar.width <= 24)).toBe(true);
    expect(layout.bars[0].path).toMatch(new RegExp(`^M[\\d.]+,${layout.bottom}V`));
    expect(layout.ticks.map((tick) => tick.label)).toEqual(['0', '10', '20', '30', '40']);
    expect(layout.zeroY).toBe(layout.bottom);
    expect(layout.labelBars).toBe(true);
  });

  it('keeps a 2px gap between the bars of a group', () => {
    const grouped = chart({
      series: [
        { name: 'a', values: [1, 2] },
        { name: 'b', values: [3, 4] },
      ],
    });
    const [a, b] = layoutChart(grouped, 640).bars.filter((_, index) => index % 2 === 0);
    expect(b.x - (a.x + a.width)).toBeCloseTo(2);
  });

  it('breaks a line at a missing value rather than bridging it', () => {
    const line = chart({
      kind: 'line',
      x: ['2026-01', '2026-02', '2026-03', '2026-04'],
      series: [{ name: 'v', values: [1, 2, null, 4] }],
    });
    const [only] = layoutChart(line, 640).lines;
    expect(only.path.match(/M/g)?.length).toBe(2);
    expect(only.points.map((point) => point.index)).toEqual([0, 1, 3]);
  });

  it('shows only every few labels when they would not fit', () => {
    const months = Array.from(
      { length: 36 },
      (_, index) => `2024-${String(index).padStart(2, '0')}`,
    );
    const line = chart({
      kind: 'line',
      x: months,
      series: [{ name: 'v', values: months.map(() => 1) }],
    });
    const narrow = layoutChart(line, 360).slots.filter((slot) => slot.shown).length;
    const wide = layoutChart(line, 1200).slots.filter((slot) => slot.shown).length;
    expect(narrow).toBeLessThan(wide);
    expect(narrow).toBeGreaterThan(1);
  });
});

describe('barPath', () => {
  it('rounds the end at the value and keeps the baseline square', () => {
    expect(barPath(10, 20, 100, 40)).toBe('M10,100V44Q10,40 14,40H26Q30,40 30,44V100Z');
  });

  it('rounds a negative bar at its bottom', () => {
    expect(barPath(10, 20, 100, 150)).toBe('M10,100V146Q10,150 14,150H26Q30,150 30,146V100Z');
  });
});

describe('labels', () => {
  it('formats values and shortens long labels', () => {
    expect(formatValue(12345.678)).toBe('12,345.68');
    expect(formatValue(2_500_000)).toBe('2.5M');
    expect(formatValue(0.01234)).toBe('0.0123');
    expect(shortLabel('Emergency room admission')).toBe('Emergency r…');
    expect(shortLabel('2026-08')).toBe('2026-08');
  });
});
