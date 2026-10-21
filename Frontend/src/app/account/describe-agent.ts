/**
 * "Chrome on macOS" from a browser's user-agent string, so a person can recognise their own
 * devices in the list of sessions. Only the common cases are named; anything else is
 * "Unknown browser".
 */
export function describeAgent(userAgent: string): string {
  const agent = userAgent || '';
  const browser =
    [
      [/Edg\//, 'Edge'],
      [/OPR\//, 'Opera'],
      [/Firefox\//, 'Firefox'],
      [/Chrome\//, 'Chrome'],
      [/Safari\//, 'Safari'],
      [/curl\//, 'curl'],
    ].find(([pattern]) => (pattern as RegExp).test(agent))?.[1] ?? null;
  const system =
    [
      [/iPhone|iPad/, 'iOS'],
      [/Android/, 'Android'],
      [/Mac OS X|Macintosh/, 'macOS'],
      [/Windows/, 'Windows'],
      [/CrOS/, 'ChromeOS'],
      [/Linux/, 'Linux'],
    ].find(([pattern]) => (pattern as RegExp).test(agent))?.[1] ?? null;
  if (browser && system) {
    return `${browser} on ${system}`;
  }
  return (browser as string | null) ?? (system ? `A browser on ${system}` : 'Unknown browser');
}

/** Whether the device is a phone or tablet, to pick its icon. */
export function isMobileAgent(userAgent: string): boolean {
  return /iPhone|iPad|Android|Mobile/.test(userAgent || '');
}

const WHEN = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' });

/** A stored ISO time as people read it, in their own time zone. */
export function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : WHEN.format(date);
}
