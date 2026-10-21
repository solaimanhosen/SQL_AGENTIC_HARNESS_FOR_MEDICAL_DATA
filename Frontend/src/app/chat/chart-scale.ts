import { Chart } from '../api/types';

/**
 * The geometry of a chart, worked out from its values and the width it has to fill. It is
 * kept apart from the component so it can be tested without a browser. The report's charts
 * in Backend/sql_agent/charts.py follow the same tick rule, so both read the same.
 */

export const PLOT_HEIGHT = 220;
export const TOP = 18;
export const AXIS_BAND = 34;
export const MAX_BAR = 24;
export const BAR_GAP = 2;
const CHAR_WIDTH = 6.6;
const MAX_LABEL_CHARS = 12;

/** Round tick values covering lo to hi, about `target` of them, stepped by 1, 2 or 5. */
export function niceTicks(lo: number, hi: number, target = 5): number[] {
  if (lo === hi) {
    if (lo === 0) {
      hi = 1;
    } else if (lo > 0) {
      lo = 0;
    } else {
      hi = 0;
    }
  }
  const step = niceStep((hi - lo) / target);
  const start = Math.floor(lo / step + 1e-9) * step;
  const end = Math.ceil(hi / step - 1e-9) * step;
  const decimals = Math.max(0, -Math.floor(Math.log10(step)));
  const ticks: number[] = [];
  for (let value = start; value <= end + step / 2; value += step) {
    ticks.push(Number(value.toFixed(decimals)));
  }
  return ticks;
}

function niceStep(raw: number): number {
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * power;
}

/**
 * The value range to draw. Bars always start at zero, since their length is the value. A
 * line starts at zero too unless its values sit far above it, where zero would flatten it.
 */
export function valueDomain(chart: Chart): [number, number] {
  const values = chart.series.flatMap((series) => series.values).filter(isNumber);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (chart.kind === 'bar' || (lo >= 0 && lo <= hi / 2)) {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  }
  return [lo, hi];
}

export function formatValue(value: number): string {
  const size = Math.abs(value);
  if (size >= 1_000_000) {
    return `${trim(value / 1_000_000)}M`;
  }
  return value.toLocaleString('en-US', { maximumFractionDigits: size < 1 ? 4 : 2 });
}

function trim(value: number): string {
  return value.toLocaleString('en-US', { maximumFractionDigits: 1 });
}

export function shortLabel(label: string): string {
  return label.length > MAX_LABEL_CHARS ? `${label.slice(0, MAX_LABEL_CHARS - 1)}…` : label;
}

export function isNumber(value: number | null): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export interface Tick {
  value: number;
  y: number;
  label: string;
}

export interface Bar {
  series: number;
  x: number;
  width: number;
  path: string;
  /** Where a value label goes, just past the bar's end. */
  labelY: number;
  value: number;
}

export interface Line {
  series: number;
  path: string;
  points: { x: number; y: number; index: number }[];
}

export interface Layout {
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
  ticks: Tick[];
  zeroY: number;
  /** The centre of each category, and the width it may be hovered over. */
  slots: { x: number; width: number; label: string; shown: boolean }[];
  bars: Bar[];
  lines: Line[];
  /** True when every bar is wide enough apart to carry its value as text. */
  labelBars: boolean;
}

export function layoutChart(chart: Chart, width: number): Layout {
  const [lo, hi] = valueDomain(chart);
  const ticks = niceTicks(lo, hi);
  const min = ticks[0];
  const max = ticks[ticks.length - 1];
  const tickLabels = ticks.map(formatValue);
  const longest = Math.min(Math.max(...chart.x.map((label) => label.length)), MAX_LABEL_CHARS);
  // A line's first and last points sit on the plot's edges, so their labels need room
  // beside it to stay whole.
  const edge = chart.kind === 'line' ? Math.round((longest * CHAR_WIDTH) / 2 + 4) : 0;
  const left = Math.max(
    Math.round(Math.max(...tickLabels.map((label) => label.length)) * CHAR_WIDTH + 14),
    edge,
  );
  // A line's last value is written just past its end, so leave room for the longest.
  const endValues = chart.series
    .map((series) => series.values.filter(isNumber).at(-1))
    .filter((value): value is number => value !== undefined)
    .map((value) => formatValue(value).length * CHAR_WIDTH + 12);
  const right = chart.kind === 'line' ? Math.round(Math.max(16, edge, ...endValues)) : 8;
  const top = TOP;
  const bottom = top + PLOT_HEIGHT;
  const plotWidth = Math.max(width - left - right, 40);
  const y = (value: number) => bottom - ((value - min) / (max - min || 1)) * PLOT_HEIGHT;
  const zeroY = y(Math.min(Math.max(0, min), max));

  const count = chart.x.length;
  const slotWidth = chart.kind === 'bar' || count < 2 ? plotWidth / count : plotWidth / (count - 1);
  const centre = (index: number) =>
    chart.kind === 'bar' || count < 2 ? left + slotWidth * (index + 0.5) : left + slotWidth * index;
  const stride = Math.max(1, Math.ceil((longest * CHAR_WIDTH + 10) / (plotWidth / count)));
  const slots = chart.x.map((label, index) => ({
    x: centre(index),
    width: chart.kind === 'bar' || count < 2 ? slotWidth : Math.max(slotWidth, 8),
    label,
    shown: index % stride === 0,
  }));

  const bars: Bar[] = [];
  const lines: Line[] = [];
  const seriesCount = chart.series.length;
  if (chart.kind === 'bar') {
    const barWidth = Math.max(
      2,
      Math.min(MAX_BAR, (slotWidth * 0.75 - BAR_GAP * (seriesCount - 1)) / seriesCount),
    );
    const group = barWidth * seriesCount + BAR_GAP * (seriesCount - 1);
    chart.series.forEach((series, s) => {
      series.values.forEach((value, index) => {
        if (!isNumber(value)) {
          return;
        }
        const x = centre(index) - group / 2 + s * (barWidth + BAR_GAP);
        const end = y(value);
        bars.push({
          series: s,
          x,
          width: barWidth,
          path: barPath(x, barWidth, zeroY, end),
          labelY: value >= 0 ? end - 5 : end + 13,
          value,
        });
      });
    });
  } else {
    chart.series.forEach((series, s) => {
      const points = series.values
        .map((value, index) => (isNumber(value) ? { x: centre(index), y: y(value), index } : null))
        .filter((point): point is { x: number; y: number; index: number } => point !== null);
      // A gap in the values breaks the line rather than bridging it.
      let path = '';
      let previous = -2;
      for (const point of points) {
        path += `${point.index === previous + 1 ? 'L' : 'M'}${round(point.x)},${round(point.y)}`;
        previous = point.index;
      }
      lines.push({ series: s, path, points });
    });
  }

  return {
    width,
    height: bottom + AXIS_BAND,
    left,
    right,
    top,
    bottom,
    ticks: ticks.map((value, index) => ({ value, y: y(value), label: tickLabels[index] })),
    zeroY,
    slots,
    bars,
    lines,
    labelBars: bars.length <= 12 && bars.every((bar) => bar.width >= 14),
  };
}

/** A bar with a 4px rounded end at its value and a square end on the baseline. */
export function barPath(x: number, width: number, base: number, end: number): string {
  const height = Math.abs(base - end);
  const r = Math.min(4, width / 2, height);
  const [x0, x1] = [round(x), round(x + width)];
  if (height === 0) {
    return `M${x0},${round(base)}H${x1}`;
  }
  if (end < base) {
    return (
      `M${x0},${round(base)}V${round(end + r)}Q${x0},${round(end)} ${round(x + r)},${round(end)}` +
      `H${round(x + width - r)}Q${x1},${round(end)} ${x1},${round(end + r)}V${round(base)}Z`
    );
  }
  return (
    `M${x0},${round(base)}V${round(end - r)}Q${x0},${round(end)} ${round(x + r)},${round(end)}` +
    `H${round(x + width - r)}Q${x1},${round(end)} ${x1},${round(end - r)}V${round(base)}Z`
  );
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}
