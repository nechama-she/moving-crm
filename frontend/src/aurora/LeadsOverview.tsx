// The Leads page's greeting (what needs attention now) and its pipeline funnel for the selected month.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "../apiConfig";
import { authHeaders, useAuth } from "../AuthContext";
import { reducedMotion, useCountUp } from "./motion";

type QueueCounts = { messages?: { unanswered?: number }; missed_calls?: number; first_contact?: { new?: number; overdue?: number } };

/** What is waiting right now, from the work queue (admins only; others see just the new leads). */
export function Attention({ newToday }: { newToday?: number }) {
  const { token } = useAuth();
  const [queue, setQueue] = useState<QueueCounts | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/api/unanswered-messages/summary`, { headers: authHeaders(token), signal: controller.signal })
      .then(r => (r.ok ? r.json() : null)).then(setQueue).catch(() => {});
    return () => controller.abort();
  }, [token]);
  const plural = (n: number, one: string, many: string) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
  const waiting = queue?.messages?.unanswered ?? 0;
  const missed = queue?.missed_calls ?? 0;
  const uncontacted = (queue?.first_contact?.new ?? 0) + (queue?.first_contact?.overdue ?? 0);
  const items = [
    newToday ? <span key="new">{plural(newToday, "new lead", "new leads")} today</span> : null,
    waiting ? <Link key="waiting" to="/sales-work-queue">{plural(waiting, "customer is", "customers are")} waiting for a reply</Link> : null,
    missed ? <Link key="missed" to="/sales-work-queue">{plural(missed, "missed call", "missed calls")}</Link> : null,
    uncontacted ? <Link key="first" to="/sales-work-queue">{plural(uncontacted, "new lead", "new leads")} not contacted yet</Link> : null,
  ].filter(Boolean);
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  // Written as a sentence, so it wraps naturally on narrow screens.
  return (
    <p className="aur-attention">
      <span className="aur-attention-date">{today}.</span>{" "}
      {items.length ? items.map((item, i) => (
        <span key={item!.key}>{i === 0 ? "" : i === items.length - 1 ? " and " : ", "}{item}{i === items.length - 1 ? "." : ""}</span>
      )) : queue ? "Nothing is waiting for a reply." : null}
    </p>
  );
}

// Leads created in the month, by current status. A lead that is now Quoted also went through Contacted,
// so each stage counts every lead at that stage or further along.
const STATUSES = ["new", "contacted", "quoted", "booked", "scheduled", "completed", "lost", "cancelled"] as const;
const STAGES: Array<{ label: string; statuses: string[] }> = [
  { label: "Created", statuses: [...STATUSES] },
  { label: "Contacted", statuses: ["contacted", "quoted", "booked", "scheduled", "completed"] },
  { label: "Quoted", statuses: ["quoted", "booked", "scheduled", "completed"] },
  { label: "Booked", statuses: ["booked", "scheduled", "completed"] },
];
const CountTo = ({ value }: { value: number }) => <>{Math.round(useCountUp(value, 1100)).toLocaleString()}</>;
const percent = (part: number, whole: number) => (whole ? `${((part / whole) * 100).toFixed(part / whole < 0.1 ? 1 : 0)}%` : "—");

export function PipelineFunnel({ month, monthLabel, company, rep }: { month: string; monthLabel: string; company: string; rep: string }) {
  const { token } = useAuth();
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [failed, setFailed] = useState(false);
  const cols = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setCounts(null); setFailed(false);
    // One small request per status: the server's monthly summary follows the list's filters.
    Promise.all(["", ...STATUSES].map(async status => {
      const params = new URLSearchParams({ limit: "1", overview_month: month });
      if (status) params.set("status", status);
      if (company) params.set("company_id", company);
      if (rep) params.set("assigned_to", rep);
      const response = await fetch(`${API_BASE}/api/leads?${params}`, { headers: authHeaders(token), signal: controller.signal });
      if (!response.ok) throw new Error(String(response.status));
      return [status || "all", Number((await response.json()).summary?.new_month) || 0] as const;
    })).then(entries => setCounts(Object.fromEntries(entries))).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [token, month, company, rep]);

  const total = counts?.all ?? 0;
  const stages = STAGES.map((stage, i) => ({ ...stage, value: !counts ? 0 : i === 0 ? total : stage.statuses.reduce((sum, s) => sum + (counts[s] || 0), 0) }));
  const lost = counts ? (counts.lost || 0) + (counts.cancelled || 0) : 0;

  // Bars grow up from the floor one after another, then the step rates pop in.
  useLayoutEffect(() => {
    if (!counts || reducedMotion() || !cols.current) return;
    cols.current.querySelectorAll<HTMLElement>(".aur-funnel-fill").forEach((fill, i) => fill.animate(
      [{ transform: "scaleY(0)" }, { transform: "scaleY(1)" }], { duration: 1100, delay: 200 + i * 90, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "backwards" }));
    cols.current.querySelectorAll<HTMLElement>(".aur-funnel-rate").forEach((rate, i) => rate.animate(
      [{ opacity: 0, transform: "translate(-50%, 50%) scale(0.6)" }, { opacity: 1, transform: "translate(-50%, 50%)" }], { duration: 600, delay: 650 + i * 90, easing: "cubic-bezier(0.34, 1.9, 0.64, 1)", fill: "backwards" }));
  }, [counts]);

  return (
    <section className="aur-card aur-funnel" aria-label={`Pipeline for ${monthLabel}`} aria-busy={!counts && !failed}>
      <header className="aur-funnel-head">
        <div>
          <h2>Pipeline</h2>
          <p className="aur-muted">Leads created in {monthLabel}, by how far they have got</p>
        </div>
        {counts && <div className="aur-funnel-overall"><strong>{percent(stages[3].value, total)}</strong><span>booked overall</span></div>}
      </header>
      {failed ? <p className="aur-muted aur-funnel-note">The pipeline could not be loaded.</p> : (
        <div className="aur-funnel-cols" ref={cols}>
          {stages.map((stage, i) => (
            <div className="aur-funnel-stage" key={stage.label}>
              <div className="aur-funnel-label"><span>{i + 1}. {stage.label}</span>
                {counts ? <strong><CountTo value={stage.value} /></strong> : <span className="aur-skeleton aur-funnel-skeleton" aria-hidden="true" />}
                <small>{counts ? (i === 0 ? "100% of created" : `${percent(stage.value, total)} of created`) : " "}</small>
              </div>
              <div className="aur-funnel-col">
                {counts && <div className="aur-funnel-fill" style={{ height: `${total ? Math.max(2, (stage.value / total) * 100) : 0}%` }} />}
              </div>
              {counts && i > 0 && <span className="aur-funnel-rate" title={`${stage.label} out of ${stages[i - 1].label.toLowerCase()}`}>{percent(stage.value, stages[i - 1].value)}</span>}
            </div>
          ))}
        </div>
      )}
      {counts && <p className="aur-muted aur-funnel-note">Lost or cancelled: {lost.toLocaleString()} ({percent(lost, total)}). Each stage counts leads at that stage or further along.</p>}
    </section>
  );
}
