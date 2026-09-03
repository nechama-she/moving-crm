import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type QuoteLead = { lead_id: string; client: string; company: string; rep: string; created_at: string; volume: number | null; smartmoving_id: string };
type QuoteRep = { rep_id: string; rep: string; quotes: number; sized_quotes: number; average_cuft: number | null; leads: QuoteLead[] };
type QuoteDay = { date: string; quotes: number; sized_quotes: number; average_cuft: number | null; reps: QuoteRep[] };

const formatCuft = (value: number | null) => value == null ? "—" : `${Math.round(value).toLocaleString()} cu ft`;
const cell: React.CSSProperties = { padding: "13px 16px", borderBottom: "1px solid #e2e8f0", color: "#334155", textAlign: "left" };

export default function StatsPage() {
  const { token } = useAuth();
  const [days, setDays] = useState<QuoteDay[]>([]);
  const [selectedDay, setSelectedDay] = useState<QuoteDay | null>(null);
  const [selectedRep, setSelectedRep] = useState<QuoteRep | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/stats/priority-one-quote-size`, { headers: authHeaders(token) })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        setDays(Array.isArray(data.days) ? data.days : []);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load quote statistics"))
      .finally(() => setLoading(false));
  }, [token]);

  const chooseDay = (day: QuoteDay) => { setSelectedDay(day); setSelectedRep(null); };
  return <main style={{ padding: 24, width: "100%", maxWidth: 1280, margin: "0 auto", boxSizing: "border-box" }}>
    <h1 style={{ margin: 0, color: "#032d60", fontSize: 24 }}>Stats</h1>
    <p style={{ margin: "6px 0 20px", color: "#64748b" }}>Priority 1 quote size by lead-created day.</p>
    {error ? <p style={{ color: "#b91c1c" }}>{error}</p> : null}
    <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
      <div style={{ padding: "16px 18px", borderBottom: "1px solid #d8dde6" }}><h2 style={{ margin: 0, color: "#032d60", fontSize: 18 }}>Average Quote Size</h2></div>
      <div style={{ overflowX: "auto" }}><table style={{ width: "100%", minWidth: 650, borderCollapse: "collapse" }}>
        <thead><tr style={{ background: "#f8fafc" }}>{["Created Day", "Priority 1 Quotes", "With Cu Ft", "Average Cu Ft"].map((header) => <th key={header} style={cell}>{header}</th>)}</tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={4} style={{ ...cell, textAlign: "center" }}>Loading statistics…</td></tr> : null}
          {!loading && days.length === 0 ? <tr><td colSpan={4} style={{ ...cell, textAlign: "center", color: "#64748b" }}>No Priority 1 quotes found.</td></tr> : null}
          {days.map((day) => <tr key={day.date} onClick={() => chooseDay(day)} style={{ cursor: "pointer", background: selectedDay?.date === day.date ? "#eef6ff" : "#fff" }}>
            <td style={{ ...cell, color: "#0b5cab", fontWeight: 700 }}>{new Date(`${day.date}T12:00:00`).toLocaleDateString()}</td><td style={cell}>{day.quotes}</td><td style={cell}>{day.sized_quotes}</td><td style={{ ...cell, fontWeight: 700 }}>{formatCuft(day.average_cuft)}</td>
          </tr>)}
        </tbody>
      </table></div>
    </section>

    {selectedDay ? <section style={{ marginTop: 18, background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
      <div style={{ padding: "16px 18px", borderBottom: "1px solid #d8dde6" }}><h2 style={{ margin: 0, color: "#032d60", fontSize: 18 }}>By Rep · {new Date(`${selectedDay.date}T12:00:00`).toLocaleDateString()}</h2></div>
      <div style={{ overflowX: "auto" }}><table style={{ width: "100%", minWidth: 650, borderCollapse: "collapse" }}><thead><tr style={{ background: "#f8fafc" }}>{["Rep", "Priority 1 Quotes", "With Cu Ft", "Average Cu Ft"].map((header) => <th key={header} style={cell}>{header}</th>)}</tr></thead><tbody>
        {selectedDay.reps.map((rep) => <tr key={rep.rep_id} onClick={() => setSelectedRep(rep)} style={{ cursor: "pointer", background: selectedRep?.rep_id === rep.rep_id ? "#eef6ff" : "#fff" }}><td style={{ ...cell, color: "#0b5cab", fontWeight: 700 }}>{rep.rep}</td><td style={cell}>{rep.quotes}</td><td style={cell}>{rep.sized_quotes}</td><td style={{ ...cell, fontWeight: 700 }}>{formatCuft(rep.average_cuft)}</td></tr>)}
      </tbody></table></div>
    </section> : null}

    {selectedRep ? <section style={{ marginTop: 18, background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
      <div style={{ padding: "16px 18px", borderBottom: "1px solid #d8dde6" }}><h2 style={{ margin: 0, color: "#032d60", fontSize: 18 }}>{selectedRep.rep} · Quote List</h2></div>
      <div style={{ overflowX: "auto" }}><table style={{ width: "100%", minWidth: 820, borderCollapse: "collapse" }}><thead><tr style={{ background: "#f8fafc" }}>{["Client", "Company", "Created", "Cu Ft"].map((header) => <th key={header} style={cell}>{header}</th>)}</tr></thead><tbody>
        {selectedRep.leads.map((lead) => <tr key={lead.lead_id}><td style={cell}><Link to={`/leads/${lead.lead_id}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{lead.client}</Link></td><td style={cell}>{lead.company || "—"}</td><td style={cell}>{new Date(lead.created_at).toLocaleString()}</td><td style={cell}>{formatCuft(lead.volume)}</td></tr>)}
      </tbody></table></div>
    </section> : null}
  </main>;
}
