// Day-by-day view for short date ranges (Today, Next 7 days) on the calendars in the new look.
// Longer ranges keep the month grid.
import type { CSSProperties, ReactNode } from "react";
import { dayKey, fromKey } from "./dateRange";

export default function RangeDays<T>({ days, jobsByDate, renderJob, renderDayTools }: {
  days: string[];
  jobsByDate: Map<string, T[]>;
  renderJob: (job: T, index: number) => ReactNode;
  renderDayTools?: (day: string) => ReactNode;
}) {
  const today = dayKey(new Date());
  return (
    <div className={`aur-range-days${days.length === 1 ? " is-single" : ""}`} style={{ "--range-columns": Math.min(days.length, 7) } as CSSProperties}>
      {days.map(day => {
        const date = fromKey(day);
        const jobs = jobsByDate.get(day) || [];
        return (
          <section key={day} className={`aur-range-day${day === today ? " is-today" : ""}`} aria-label={date.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}>
            <header>
              <span className="aur-range-date"><small>{date.toLocaleDateString(undefined, { weekday: "short" })}</small><strong>{date.getDate()}</strong><small>{date.toLocaleDateString(undefined, { month: "short" })}</small></span>
              <span className="aur-range-count">{jobs.length ? `${jobs.length} job${jobs.length === 1 ? "" : "s"}` : "No jobs"}</span>
              {renderDayTools?.(day)}
            </header>
            {jobs.length ? <div className="aur-range-jobs">{jobs.map(renderJob)}</div> : null}
          </section>
        );
      })}
    </div>
  );
}
