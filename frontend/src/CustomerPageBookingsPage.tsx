import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import "./ReportsPage.css";

type Row = { lead_id: string; name: string; signed_at: string; estimate_total: number; payments: number; card_fees: number; third_party: number; total_payment: number; crm_fees: number };
type Report = { items: Row[]; totals: Omit<Row, "lead_id" | "name" | "signed_at">; card_fee_percent: number; crm_fee_percent: number };
const money = (value: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);

// Every lead signed on the customer page: its estimate, its payments after card fees and third-party payout, and
// Hallin's (the CRM company's) share of them.
export default function CustomerPageBookingsPage() {
  const { token } = useAuth();
  const [report, setReport] = useState<Report>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetch(`${API_BASE}/api/stats/customer-page-bookings`, { headers: authHeaders(token), signal: controller.signal })
      .then(async (response) => {
        const data = await response.json().catch(() => null);
        if (!response.ok || !data) throw new Error(typeof data?.detail === "string" ? data.detail : "Could not load the report");
        setReport(data as Report);
      })
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not load the report"); });
    return () => controller.abort();
  }, [token, attempt]);
  const breakdown = (row: Pick<Row, "payments" | "card_fees" | "third_party">) =>
    `${money(row.payments)} paid - ${money(row.card_fees)} card fees (${report?.card_fee_percent}%) - ${money(row.third_party)} third-party payout`;
  return <main className="reports-page">
    <header><div className="reports-eyebrow">Reports</div><h1>Customer Page Bookings</h1>
      <p>Jobs signed through the customer page. Total payment is the payments less {report?.card_fee_percent ?? 3.5}% credit card fees and the third-party payout; CRM fees are Hallin's {report?.crm_fee_percent ?? 15}% of it.</p></header>
    {error && <div className="reports-error" role="alert">{error}<button className="slds-button" onClick={() => setAttempt((value) => value + 1)}>Try again</button></div>}
    {!report && !error && <p role="status">Loading...</p>}
    {report && <section className="reports-results">
      <div className="reports-table"><table>
        <thead><tr>{["Name", "Estimate total", "Total payment", "CRM fees (Hallin)"].map((title) => <th key={title}>{title}</th>)}</tr></thead>
        <tbody>
          {report.items.map((row) => <tr key={row.lead_id}>
            <td><Link to={`/leads/${row.lead_id}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0176d3", fontWeight: 600 }}>{row.name || "Open lead"}</Link></td>
            <td>{money(row.estimate_total)}</td>
            <td title={breakdown(row)}>{money(row.total_payment)}</td>
            <td>{money(row.crm_fees)}</td>
          </tr>)}
          {!report.items.length && <tr><td colSpan={4} className="reports-empty">No jobs have been signed through the customer page yet.</td></tr>}
        </tbody>
        {report.items.length > 0 && <tfoot><tr style={{ fontWeight: 700, background: "#f5f7fa", color: "#032d60" }}>
          <td>Total ({report.items.length})</td>
          <td>{money(report.totals.estimate_total)}</td>
          <td title={breakdown(report.totals)}>{money(report.totals.total_payment)}</td>
          <td>{money(report.totals.crm_fees)}</td>
        </tr></tfoot>}
      </table></div>
    </section>}
  </main>;
}
