import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import "./ReportsPage.css";

type Move = { id: string; customer: string; first_signup: string; move_date: string; pickup: string; delivery: string; booked: boolean; issues: string[]; leads: { id: string; company: string; status: string; created_time: string; created_at: string }[] };
type Report = { total_moves: number; booked_moves: number; percentage: number | null; lead_count: number; duplicates_removed: number; review_count: number; undated_moves: number; moves: Move[] };
const today = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const formatDate = (value: string) => value ? new Date(value.length === 10 ? `${value}T12:00:00Z` : value).toLocaleDateString("en-US", { timeZone: "America/New_York" }) : "Not available";

export default function ReportsPage() {
  const { token } = useAuth();
  const [start, setStart] = useState(() => today().slice(0, 8) + "01");
  const [end, setEnd] = useState(today);
  const [range, setRange] = useState({ start, end });
  const [report, setReport] = useState<Report>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reviewOnly, setReviewOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setReport(undefined); setPage(0);
    fetch(`${API_BASE}/api/stats/booking-percentage?${new URLSearchParams(range)}`, { headers: authHeaders(token), signal: controller.signal })
      .then(async response => { const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not load report"); return data as Report; })
      .then(setReport).catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not load report"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [range, token]);
  const filtered = (report?.moves || []).filter(move => (!reviewOnly || move.issues.length > 0) && `${move.customer} ${move.pickup} ${move.delivery} ${move.leads.map(lead => lead.company).join(" ")}`.toLowerCase().includes(search.toLowerCase()));
  return <main className="reports-page">
    <header><div className="reports-eyebrow">Reports</div><h1>Booking Percentage</h1><p>See how many distinct customer moves turned into bookings across all companies.</p></header>
    <nav className="reports-tabs" aria-label="Reports"><Link to="/reports/booking-percentage" aria-current="page">Booking Percentage</Link></nav>
    <form className="reports-filter" onSubmit={event => { event.preventDefault(); setRange({ start, end }); }}>
      <label>First signup from<input type="date" required value={start} max={end} onChange={event => setStart(event.target.value)} /></label>
      <label>Through<input type="date" required value={end} min={start} onChange={event => setEnd(event.target.value)} /></label>
      <button className="reports-primary" disabled={!start || !end || start > end || loading}>Run report</button>
      <button type="button" onClick={() => { const last = today(); const first = last.slice(0, 8) + "01"; setStart(first); setEnd(last); setRange({ start: first, end: last }); }}>This month</button>
      <small>Dates use Eastern time. Both dates are included.</small>
    </form>
    {loading && <p role="status">Calculating customer moves...</p>}
    {error && <div className="reports-error" role="alert">{error}<button onClick={() => setRange({ ...range })}>Try again</button></div>}
    {report && <>
      <div className="reports-range">First signups: {formatDate(range.start)} - {formatDate(range.end)}</div>
      <section className="reports-metrics" aria-label="Booking summary">
        <article><span>Booking percentage</span><strong>{report.percentage == null ? "No data" : `${report.percentage.toFixed(1)}%`}</strong><small>{report.booked_moves} booked / {report.total_moves} distinct moves</small></article>
        <article><span>Distinct customer moves</span><strong>{report.total_moves.toLocaleString()}</strong><small>Counted by first signup</small></article>
        <article><span>Booked moves</span><strong>{report.booked_moves.toLocaleString()}</strong><small>Across all matching companies</small></article>
        <article><span>Duplicate leads combined</span><strong>{report.duplicates_removed.toLocaleString()}</strong><small>{report.lead_count.toLocaleString()} leads in these moves</small></article>
      </section>
      {(report.review_count > 0 || report.undated_moves > 0) && <p className="reports-warning">{report.review_count} moves in this range need data review. {report.undated_moves > 0 ? `${report.undated_moves} moves across all dates have no usable SmartMoving signup time and are excluded.` : "Open the rows below to see details."}</p>}
      <section className="reports-results"><div className="reports-toolbar"><h2>Customer moves</h2><input aria-label="Search customer moves" placeholder="Search customer, company or location" value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} /><label><input type="checkbox" checked={reviewOnly} onChange={event => { setReviewOnly(event.target.checked); setPage(0); }} /> Needs review only</label></div>
        <div className="reports-table"><table><thead><tr>{["Customer / matching leads", "First signup", "Move date", "Pickup", "Delivery", "Result"].map(title => <th key={title}>{title}</th>)}</tr></thead><tbody>
          {filtered.slice(page * 50, (page + 1) * 50).map(move => <tr key={move.id}><td><Link to={`/leads/${move.id}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0176d3", fontWeight: 600 }}>{move.customer}</Link><details><summary>{move.leads.length} lead{move.leads.length === 1 ? "" : "s"}{move.issues.length ? " - Needs review" : ""}</summary>{move.leads.map(lead => <div className="reports-lead" key={lead.id}><Link to={`/leads/${lead.id}`} target="_blank" rel="noopener noreferrer">{lead.company || "Open lead"}</Link><span>{lead.status}</span><small>SmartMoving signup: {lead.created_time || "Missing"}<br/>CRM created: {lead.created_at || "Missing"}</small></div>)}{move.issues.map(issue => <p className="reports-issue" key={issue}>{issue}</p>)}</details></td><td>{formatDate(move.first_signup)}</td><td>{formatDate(move.move_date)}</td><td>{move.pickup || "Not available"}</td><td>{move.delivery || "Not available"}</td><td><span className={`reports-badge ${move.booked ? "booked" : ""}`}>{move.booked ? "Booked" : "Not booked"}</span></td></tr>)}
          {!filtered.length && <tr><td colSpan={6} className="reports-empty">No customer moves match this range and these filters.</td></tr>}
        </tbody></table></div>
        <footer><span>{filtered.length.toLocaleString()} moves{filtered.length > 0 ? ` - Page ${page + 1} of ${Math.ceil(filtered.length / 50)}` : ""}</span><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button disabled={(page + 1) * 50 >= filtered.length} onClick={() => setPage(page + 1)}>Next</button></footer>
      </section>
    </>}
  </main>;
}
