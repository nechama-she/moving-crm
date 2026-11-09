// Date range helpers for the day-by-day calendar view (RangeDays.tsx).
const MAX_RANGE_DAYS = 14;

export const dayKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
export const fromKey = (key: string) => new Date(`${key}T00:00:00`);

/** The dates of a range as YYYY-MM-DD keys, or null when there is no range or it is too long for columns. */
export function rangeDays(range: { from: string; to: string } | null): string[] | null {
  if (!range) return null;
  const days: string[] = [];
  for (const date = fromKey(range.from); dayKey(date) <= range.to && days.length <= MAX_RANGE_DAYS; date.setDate(date.getDate() + 1)) days.push(dayKey(date));
  return days.length && days.length <= MAX_RANGE_DAYS ? days : null;
}

export function rangeLabel(days: string[]) {
  const first = fromKey(days[0]);
  const last = fromKey(days[days.length - 1]);
  if (days.length === 1) return first.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  return `${first.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${last.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
}
