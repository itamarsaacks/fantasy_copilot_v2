/**
 * Single source of truth for date helpers used by all tabs.
 * Consolidates scattered helpers from team-view, player-detail-drawer,
 * waivers-view per master plan §3.
 *
 * All helpers operate in the user's local timezone for display; ISO dates
 * (YYYY-MM-DD) are timezone-naive and round-trip via the backend.
 */

export function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function parseISODate(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export function isFutureDate(d: Date, today: Date = new Date()): boolean {
  return toISODate(d) > toISODate(today);
}

export function addDays(d: Date, n: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}

/** "Mon, Mar 22" — compact format for date toggles. */
export function formatDateHeadline(d: Date): string {
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** "Mar 22" — for tighter contexts (table cells). */
export function fmtDateShort(d: Date): string {
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/** Last N days INCLUSIVE of `today`, newest first. */
export function lastNDays(n: number, today: Date = new Date()): Date[] {
  const out: Date[] = [];
  for (let i = 0; i < n; i++) {
    out.push(addDays(today, -i));
  }
  return out;
}

/** Range [start, end] inclusive, ascending. */
export function dateRange(start: Date, end: Date): Date[] {
  if (toISODate(start) > toISODate(end)) return [];
  const out: Date[] = [];
  let cursor = start;
  while (toISODate(cursor) <= toISODate(end)) {
    out.push(cursor);
    cursor = addDays(cursor, 1);
  }
  return out;
}

/** Format e.g. "Mar 22 → Mar 28" for window pickers. */
export function formatWindowRange(start: Date, end: Date): string {
  return `${fmtDateShort(start)} → ${fmtDateShort(end)}`;
}
