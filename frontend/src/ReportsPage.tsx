import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import "./ReportsPage.css";
import { period } from "./reportPeriods";
import ReportControls, { type ReportOptions } from "./ReportControls";

type Move = { id: string; customer: string; first_signup: string; move_date: string; pickup: string; delivery: string; booked: boolean; issues: string[]; leads: { id: string; company: string; status: string; created_time: string; created_at: string; issues: string[] }[] };
type Report = { options: ReportOptions; total_moves: number; booked_moves: number; percentage: number | null; lead_count: number; duplicates_removed: number; review_count: number; undated_moves: number; moves: Move[] };
const formatDate = (value: string) => value ? new Date(value.length === 10 ? `${value}T12:00:00Z` : value).toLocaleDateString("en-US", { timeZone: "America/New_York" }) : "Not available";

export default function ReportsPage() {
  const { token } = useAuth();
  const [range, setRange] = useState(() => period("This Month"));
  const [companies, setCompanies] = useState<string[]>([]);
  const [reps, setReps] = useState<string[]>([]);
  const [options, setOptions] = useState<ReportOptions>({ companies: [], reps: [] });
  const [report, setReport] = useState<Report>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reviewOnly, setReviewOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setReport(undefined); setPage(0);
    const params = new URLSearchParams({ start: range.start, end: range.end });
    companies.forEach(id => params.append("company_ids", id));
    reps.forEach(id => params.append("rep_ids", id));
    fetch(`${API_BASE}/api/stats/booking-percentage?${params}`, { headers: authHeaders(token), signal: controller.signal })
      .then(async response => { const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not load report"); return data as Report; })
      .then(data => { setReport(data); setOptions(data.options); }).catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not load report"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [range, token, companies, reps]);
  const filtered = (report?.moves || []).filter(move => (!reviewOnly || move.issues.length > 0) && `${move.customer} ${move.pickup} ${move.delivery} ${move.leads.map(lead => lead.company).join(" ")}`.toLowerCase().includes(search.toLowerCase()));
  return <main className="reports-page">
    <header><div className="reports-eyebrow">Reports</div><h1>Booking Percentage</h1><p>See how many distinct customer moves turned into bookings within your selected companies and reps.</p></header>
    <nav className="reports-tabs" aria-label="Reports"><Link to="/reports/booking-percentage" aria-current="page">Booking Percentage</Link></nav>
    <ReportControls range={range} companies={companies} reps={reps} options={options} onApply={(next, nextCompanies, nextReps) => { setRange(next); setCompanies(nextCompanies); setReps(nextReps); }} />
    {loading && <p role="status">Calculating customer moves...</p>}
    {error && <div className="reports-error" role="alert">{error}<button className="slds-button" onClick={() => setRange({ ...range })}>Try again</button></div>}
    {report && <>
      <div className="reports-range">First signups: {range.label === "All Time" ? "All time" : `${formatDate(range.start)} - ${formatDate(range.end)}`}</div>
      <section className="reports-metrics" aria-label="Booking summary">
        <article><span>Booking percentage</span><strong>{report.percentage == null ? "No data" : `${report.percentage.toFixed(1)}%`}</strong><small>{report.booked_moves} booked / {report.total_moves} distinct moves</small></article>
        <article><span>Distinct customer moves</span><strong>{report.total_moves.toLocaleString()}</strong><small>Counted by first signup</small></article>
        <article><span>Booked moves</span><strong>{report.booked_moves.toLocaleString()}</strong><small>Within selected companies and reps</small></article>
        <article><span>Duplicate leads combined</span><strong>{report.duplicates_removed.toLocaleString()}</strong><small>{report.lead_count.toLocaleString()} leads in these moves</small></article>
      </section>
      {report.review_count > 0 && <details className="reports-warning"><summary>{report.review_count} moves in this range need data review - view leads and missing details</summary>
        {report.moves.filter(move => move.issues.length > 0).map(move => <div key={move.id} style={{ marginTop: 14 }}><strong>{move.customer}</strong>
          {move.leads.filter(lead => lead.issues.length > 0).map(lead => <div className="reports-lead" key={lead.id}><Link to={`/leads/${lead.id}`} target="_blank" rel="noopener noreferrer">{move.customer} - {lead.company || "Open lead"}</Link><ul>{lead.issues.map(issue => <li key={issue}>{issue}</li>)}</ul></div>)}
        </div>)}
      </details>}
      {report.undated_moves > 0 && <p className="reports-warning">{report.undated_moves} moves across all dates have no usable SmartMoving signup time and are excluded.</p>}
      <section className="reports-results"><div className="reports-toolbar"><h2>Customer moves</h2><input aria-label="Search customer moves" placeholder="Search customer, company or location" value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} /><label><input type="checkbox" checked={reviewOnly} onChange={event => { setReviewOnly(event.target.checked); setPage(0); }} /> Needs review only</label></div>
        <div className="reports-table"><table><thead><tr>{["Customer / matching leads", "First signup", "Move date", "Pickup", "Delivery", "Result"].map(title => <th key={title}>{title}</th>)}</tr></thead><tbody>
          {filtered.slice(page * 50, (page + 1) * 50).map(move => <tr key={move.id}><td><Link to={`/leads/${move.id}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0176d3", fontWeight: 600 }}>{move.customer}</Link><details><summary>{move.leads.length} lead{move.leads.length === 1 ? "" : "s"}{move.issues.length ? " - Needs review" : ""}</summary>{move.leads.map(lead => <div className="reports-lead" key={lead.id}><Link to={`/leads/${lead.id}`} target="_blank" rel="noopener noreferrer">{lead.company || "Open lead"}</Link><span>{lead.status}</span><small>SmartMoving signup: {lead.created_time || "Missing"}<br/>CRM created: {lead.created_at || "Missing"}</small>{lead.issues.map(issue => <p className="reports-issue" key={issue}>{issue}</p>)}</div>)}</details></td><td>{formatDate(move.first_signup)}</td><td>{formatDate(move.move_date)}</td><td>{move.pickup || "Not available"}</td><td>{move.delivery || "Not available"}</td><td><span className={`reports-badge ${move.booked ? "booked" : ""}`}>{move.booked ? "Booked" : "Not booked"}</span></td></tr>)}
          {!filtered.length && <tr><td colSpan={6} className="reports-empty">No customer moves match this range and these filters.</td></tr>}
        </tbody></table></div>
        <footer><span>{filtered.length.toLocaleString()} moves{filtered.length > 0 ? ` - Page ${page + 1} of ${Math.ceil(filtered.length / 50)}` : ""}</span><button className="slds-button" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button className="slds-button" disabled={(page + 1) * 50 >= filtered.length} onClick={() => setPage(page + 1)}>Next</button></footer>
      </section>
    </>}
  </main>;
}
