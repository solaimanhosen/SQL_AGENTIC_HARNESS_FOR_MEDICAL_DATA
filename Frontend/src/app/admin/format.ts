import { RunStatus } from '../api/admin-types';

/** How a run's status reads, and the colour of its label. */
export const RUN_STATES: Record<RunStatus, { label: string; tone: string }> = {
  running: { label: 'Running', tone: 'busy' },
  passed: { label: 'Passed', tone: 'good' },
  failed: { label: 'Failed', tone: 'bad' },
  timed_out: { label: 'Timed out', tone: 'bad' },
  cancelled: { label: 'Cancelled', tone: 'warn' },
  error: { label: 'Could not start', tone: 'bad' },
  interrupted: { label: 'Interrupted', tone: 'warn' },
};

const NUMBER = new Intl.NumberFormat('en-US');

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : NUMBER.format(value);
}

/** "3h 12m", "4m 05s" or "12s". */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '–';
  }
  const whole = Math.round(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  if (hours) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes) {
    return `${minutes}m ${String(rest).padStart(2, '0')}s`;
  }
  return `${rest}s`;
}

/** Milliseconds as people read them: "180 ms" or "2.4 s". */
export function millis(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '–';
  }
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
}
