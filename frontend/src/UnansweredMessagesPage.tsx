import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type MessageTab = "unanswered" | "ended";
type MessageRow = { channel: string; message_id: string; lead_id: string; client: string; message: string; rep: string; company: string; occurred_at: string };

export default function UnansweredMessagesPage() {
  const { token } = useAuth();
  const [tab, setTab] = useState<MessageTab>("unanswered");
  const [items, setItems] = useState<MessageRow[]>([]);
  const [counts, setCounts] = useState({ unanswered: 0, ended: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/unanswered-messages?ended=${tab === "ended"}&limit=100`, { headers: authHeaders(token) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setItems(data.items || []);
      setCounts(data.counts || { unanswered: 0, ended: 0 });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load messages");
    } finally {
      setLoading(false);
    }
  }, [tab, token]);

  useEffect(() => { void load(); }, [load]);

  const setEnded = async (row: MessageRow, ended: boolean) => {
    const response = await fetch(`${API_BASE}/api/unanswered-messages/end`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ channel: row.channel, message_id: row.message_id, ended }),
    });
    if (!response.ok) { setError(`HTTP ${response.status}`); return; }
    setItems((current) => current.filter((item) => item.channel !== row.channel || item.message_id !== row.message_id));
    setCounts((current) => ({ unanswered: current.unanswered + (ended ? -1 : 1), ended: current.ended + (ended ? 1 : -1) }));
  };

  const headers = ["Client", "Platform", "Message", "Rep", "Company", "Message Time", "Action"];
  const cell = { padding: "13px 16px", borderBottom: "1px solid #e2e8f0", color: "#334155" } as const;

  return (
    <main style={{ padding: 24, width: "100%", maxWidth: 1280, margin: "0 auto", boxSizing: "border-box" }}>
      <h1 style={{ margin: 0, color: "#032d60", fontSize: 24 }}>Unanswered Messages</h1>
      <p style={{ margin: "6px 0 20px", color: "#64748b" }}>Monitor client messages waiting for a response.</p>
      <div style={{ display: "flex", gap: 8, borderBottom: "1px solid #d8dde6", marginBottom: 16 }}>
        {([ ["unanswered", "Unanswered Messages", counts.unanswered], ["ended", "Ended Chats", counts.ended] ] as const).map(([key, label, count]) => (
          <button key={key} type="button" onClick={() => setTab(key)} style={{ border: 0, borderBottom: tab === key ? "3px solid #0b5cab" : "3px solid transparent", background: "transparent", color: tab === key ? "#032d60" : "#475569", padding: "11px 16px", fontWeight: tab === key ? 700 : 500, cursor: "pointer" }}>{label} ({count})</button>
        ))}
      </div>
      {error ? <p style={{ color: "#b91c1c" }}>{error}</p> : null}
      <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
          <thead><tr style={{ background: "#f8fafc", borderBottom: "1px solid #d8dde6" }}>{headers.map((header) => <th key={header} style={{ padding: "13px 16px", color: "#475569", fontSize: 12, textAlign: "left", textTransform: "uppercase" }}>{header}</th>)}</tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={7} style={{ padding: 32, textAlign: "center" }}>Loading messages…</td></tr> : null}
            {!loading && items.length === 0 ? <tr><td colSpan={7} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>{tab === "unanswered" ? "No unanswered messages." : "No ended chats."}</td></tr> : null}
            {!loading && items.map((row) => <tr key={`${row.channel}:${row.message_id}`}>
              <td style={cell}>{row.lead_id ? <Link to={`/leads/${row.lead_id}`} state={{ backTo: "/unanswered-messages", backLabel: "← Back to Unanswered Messages" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</Link> : row.channel === "messenger" ? <a href={`https://www.facebook.com/latest/${encodeURIComponent(row.client)}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</a> : <strong>{row.client}</strong>}</td>
              <td style={cell}>{row.channel === "sms" ? "SMS" : row.channel === "instagram" ? "Instagram" : "Messenger"}</td>
              <td style={{ ...cell, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.message}>{row.message || "No preview"}</td>
              <td style={cell}>{row.rep}</td><td style={cell}>{row.company || "—"}</td><td style={cell}>{new Date(row.occurred_at).toLocaleString()}</td>
              <td style={cell}><label><input type="checkbox" checked={tab === "ended"} onChange={() => void setEnded(row, tab === "unanswered")} /> {tab === "unanswered" ? "Ended" : "Reopen"}</label></td>
            </tr>)}
          </tbody>
        </table>
      </section>
    </main>
  );
}
