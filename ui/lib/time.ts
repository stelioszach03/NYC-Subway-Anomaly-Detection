export const fmtNY = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  hour12: true,
});

function parseUtc(isoUtc?: string): Date | null {
  if (!isoUtc) return null;
  // If string already has timezone (Z or +hh:mm / -hh:mm) use as-is.
  const hasTz = /Z|[+-]\d\d:?\d\d$/.test(isoUtc);
  const s = hasTz ? isoUtc : `${isoUtc}Z`;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

export function asNYTime(isoUtc: string): string {
  const d = parseUtc(isoUtc);
  if (!d) return '—';
  return fmtNY.format(d);
}

export const relFmt = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

export function fromNow(isoUtc: string): string {
  const d = parseUtc(isoUtc);
  if (!d) return '—';
  const deltaMin = Math.round((Date.now() - d.getTime()) / 60000);
  return relFmt.format(-deltaMin, 'minute');
}

// New epoch-based helpers (no string parsing)
export function formatNYFromEpoch(epochMs: number | undefined | null): string {
  if (!epochMs && epochMs !== 0) return '—';
  return fmtNY.format(new Date(Number(epochMs)));
}

export function fromNowEpoch(epochMs: number | undefined | null): string {
  if (!epochMs && epochMs !== 0) return '—';
  const deltaMin = Math.round((Date.now() - Number(epochMs)) / 60000);
  // negative delta => future, positive => past
  return deltaMin >= 0 ? relFmt.format(-deltaMin, 'minute') : relFmt.format(Math.abs(deltaMin), 'minute');
}
