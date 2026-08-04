import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type MonthSeries = {
  month: string;
  label: string;
  values: (number | null)[];
  total: number;
};

type RepPerformance = {
  id: string;
  name: string;
  series: MonthSeries[];
};

type PerformanceResponse = {
  months: { month: string; label: string }[];
  reps: RepPerformance[];
};

const COLORS = [
  "#0176d3", "#2e844a", "#9050e9", "#fe9339", "#ba0517", "#0b5cab",
  "#45c65a", "#8c4b02", "#5c5c5c", "#7526c2", "#0e7c86", "#d45087",
];

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

function SalesChart({ rep, visibleMonths, onToggleMonth }: { rep: RepPerformance; visibleMonths: Set<string>; onToggleMonth: (month: string) => void }) {
  const [activeDay, setActiveDay] = useState<number | null>(null);
  const width = 1000;
  const height = 390;
  const margin = { top: 24, right: 24, bottom: 44, left: 76 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const displayedSeries = rep.series.filter((series) => visibleMonths.has(series.month));
  const maxValue = Math.max(1, ...displayedSeries.flatMap((series) => series.values.filter((value): value is number => value !== null)));
  const gridMax = Math.ceil(maxValue / 4 / 100) * 400 || 400;
  const x = (day: number) => margin.left + ((day - 1) / 30) * plotWidth;
  const y = (value: number) => margin.top + plotHeight - (value / gridMax) * plotHeight;
  const currentMonth = rep.series[rep.series.length - 1];
  const activeValues = activeDay === null
    ? []
    : [...displayedSeries].reverse().map((series) => ({
        series,
        value: series.values[activeDay - 1],
        colorIndex: rep.series.findIndex((item) => item.month === series.month),
      })).filter((item): item is typeof item & { value: number } => item.value !== null);

  return (
    <article className="performance-card">
      <header>
        <div>
          <span className="performance-avatar">{rep.name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase()}</span>
          <div>
            <h2>{rep.name}</h2>
            <p>Cumulative booked sales by day</p>
          </div>
        </div>
        <strong>{money.format(currentMonth?.total || 0)} <small>this month</small></strong>
      </header>

      <div className="performance-chart-scroll" onPointerLeave={() => setActiveDay(null)}>
        <svg className="performance-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${rep.name} cumulative sales for the last 12 months`}>
          {[0, 1, 2, 3, 4].map((step) => {
            const value = (gridMax / 4) * step;
            return (
              <g key={step}>
                <line x1={margin.left} x2={width - margin.right} y1={y(value)} y2={y(value)} stroke="#e5e5e5" />
                <text x={margin.left - 12} y={y(value) + 4} textAnchor="end">{money.format(value)}</text>
              </g>
            );
          })}
          {[1, 5, 10, 15, 20, 25, 31].map((day) => (
            <g key={day}>
              <line x1={x(day)} x2={x(day)} y1={margin.top} y2={height - margin.bottom} stroke="#f1f1f1" />
              <text x={x(day)} y={height - 17} textAnchor="middle">{day}</text>
            </g>
          ))}
          <text className="performance-axis-title" x={margin.left + plotWidth / 2} y={height - 2} textAnchor="middle">Day of month</text>
          {displayedSeries.map((series) => {
            const originalIndex = rep.series.findIndex((item) => item.month === series.month);
            const points = series.values
              .map((value, dayIndex) => value === null ? null : `${x(dayIndex + 1)},${y(value)}`)
              .filter((point): point is string => point !== null)
              .join(" ");
            return <polyline key={series.month} points={points} fill="none" stroke={COLORS[originalIndex]} strokeWidth={originalIndex === rep.series.length - 1 ? 4 : 2.4} strokeLinecap="round" strokeLinejoin="round" opacity={originalIndex === rep.series.length - 1 ? 1 : 0.78} />;
          })}
          {activeDay !== null ? (
            <>
              <line x1={x(activeDay)} x2={x(activeDay)} y1={margin.top} y2={height - margin.bottom} stroke="#032d60" strokeWidth="1.5" strokeDasharray="5 5" />
              {activeValues.map(({ series, value, colorIndex }) => (
                <circle key={series.month} cx={x(activeDay)} cy={y(value)} r="6" fill="#fff" stroke={COLORS[colorIndex]} strokeWidth="3" />
              ))}
            </>
          ) : null}
          {Array.from({ length: 31 }, (_, index) => index + 1).map((day) => {
            const left = day === 1 ? margin.left : (x(day - 1) + x(day)) / 2;
            const right = day === 31 ? width - margin.right : (x(day) + x(day + 1)) / 2;
            return (
              <rect
                key={`hit-${day}`}
                x={left}
                y={margin.top}
                width={right - left}
                height={plotHeight}
                fill="transparent"
                style={{ cursor: "crosshair", touchAction: "pan-y" }}
                onPointerEnter={() => setActiveDay(day)}
                onPointerDown={() => setActiveDay(day)}
                aria-label={`Day ${day}`}
              />
            );
          })}
        </svg>
        {activeDay !== null ? (
          <div
            className="performance-tooltip"
            style={{ left: `${Math.min(82, Math.max(18, ((activeDay - 1) / 30) * 100))}%` }}
          >
            <strong>Day {activeDay}</strong>
            <div>
              {activeValues.map(({ series, value, colorIndex }) => (
                <span key={series.month}>
                  <i style={{ background: COLORS[colorIndex] }} />
                  <b>{series.label}</b>
                  <em>{money.format(value)}</em>
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <div className="performance-legend">
        {[...rep.series].reverse().map((series, reverseIndex) => {
          const colorIndex = rep.series.length - 1 - reverseIndex;
          return (
            <button type="button" key={series.month} className={visibleMonths.has(series.month) ? "active" : ""} onClick={() => onToggleMonth(series.month)} title={`${visibleMonths.has(series.month) ? "Hide" : "Show"} ${series.label}`}>
              <i style={{ background: COLORS[colorIndex] }} />
              <span>{series.label}</span>
              <strong>{money.format(series.total)}</strong>
            </button>
          );
        })}
      </div>
    </article>
  );
}

export default function SalesPerformancePage() {
  const { token } = useAuth();
  const [data, setData] = useState<PerformanceResponse>({ months: [], reps: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [visibleMonths, setVisibleMonths] = useState<Set<string>>(new Set());

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetch(`${API_BASE}/api/sales-performance`, { headers: authHeaders(token) })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || "Unable to load sales performance");
        }
        return response.json();
      })
      .then((body: PerformanceResponse) => {
        if (active) {
          setData(body);
          setVisibleMonths(new Set(body.months.map((month) => month.month)));
        }
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load sales performance");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [token]);

  const total = useMemo(
    () => data.reps.reduce((sum, rep) => sum + (rep.series[rep.series.length - 1]?.total || 0), 0),
    [data.reps],
  );

  function toggleMonth(month: string) {
    setVisibleMonths((current) => {
      const next = new Set(current);
      if (next.has(month) && next.size > 1) next.delete(month);
      else next.add(month);
      return next;
    });
  }

  return (
    <main className="performance-page">
      <section className="performance-heading">
        <div>
          <span className="performance-eyebrow">SALES</span>
          <h1>Sales Performance</h1>
          <p>Compare cumulative booked sales from the beginning of each month through the same calendar day.</p>
        </div>
        <div className="performance-heading-actions">
          {visibleMonths.size < data.months.length ? <button type="button" className="performance-show-all" onClick={() => setVisibleMonths(new Set(data.months.map((month) => month.month)))}>Show all months</button> : null}
          <div className="performance-summary">
            <span>Current month</span>
            <strong>{money.format(total)}</strong>
            <small>{data.reps.length} salesperson{data.reps.length === 1 ? "" : "s"}</small>
          </div>
        </div>
      </section>

      {loading ? <div className="performance-state">Loading sales performance…</div> : null}
      {error ? <div className="performance-state error">{error}</div> : null}
      {!loading && !error && data.reps.length === 0 ? (
        <div className="performance-state">No booked sales were found for the last 12 months.</div>
      ) : null}
      {!loading && !error ? <section className="performance-grid">{data.reps.map((rep) => <SalesChart key={rep.id} rep={rep} visibleMonths={visibleMonths} onToggleMonth={toggleMonth} />)}</section> : null}
    </main>
  );
}
