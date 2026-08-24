import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import { RealtimeEvent, useRealtimeUpdates } from "./useRealtimeUpdates";

type MessageTab = "unanswered" | "ended";
type MessageRow = { channel: string; message_id: string; lead_id: string; client: string; message: string; rep: string; company: string; occurred_at: string };
type MissedCallRow = { call_id: string; lead_id: string; client_identifier: string; company_identifier: string; client: string; rep: string; company: string; missed_count: number; first_missed_at: string; latest_missed_at: string };

export default function UnansweredMessagesPage() {
  const { token } = useAuth();
  const [tab, setTab] = useState<MessageTab>("unanswered");
  const [items, setItems] = useState<MessageRow[]>([]);
  const [counts, setCounts] = useState({ unanswered: 0, ended: 0 });
  const [missedCalls, setMissedCalls] = useState<MissedCallRow[]>([]);
  const [missedCallCount, setMissedCallCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const processedEvents = useRef(new Set<string>());
  const loadingRef = useRef(true);
  const pendingEvents = useRef<RealtimeEvent[]>([]);

  const load = useCallback(async () => {
    loadingRef.current = true;
    setLoading(true);
    setError("");
    try {
      const [messageResponse, callsResponse] = await Promise.all([
        fetch(`${API_BASE}/api/unanswered-messages?ended=${tab === "ended"}&limit=100`, { headers: authHeaders(token) }),
        fetch(`${API_BASE}/api/unanswered-messages/missed-calls?limit=100`, { headers: authHeaders(token) }),
      ]);
      if (!messageResponse.ok) throw new Error(`Messages HTTP ${messageResponse.status}`);
      if (!callsResponse.ok) throw new Error(`Missed calls HTTP ${callsResponse.status}`);
      const [messageData, callsData] = await Promise.all([messageResponse.json(), callsResponse.json()]);
      setItems(messageData.items || []);
      setCounts(messageData.counts || { unanswered: 0, ended: 0 });
      setMissedCalls(callsData.items || []);
      setMissedCallCount(Number(callsData.count || 0));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load messages");
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, [tab, token]);

  useEffect(() => { void load(); }, [load]);

  const applyRealtimeEvent = useCallback((event: RealtimeEvent) => {
    if (event.type !== "message_state_changed") return;
    if (loadingRef.current) {
      pendingEvents.current.push(event);
      return;
    }
    const eventId = String(event.event_id || "");
    if (!eventId || processedEvents.current.has(eventId)) return;
    processedEvents.current.add(eventId);
    if (processedEvents.current.size > 500) {
      const oldest = processedEvents.current.values().next().value;
      if (oldest) processedEvents.current.delete(oldest);
    }

    const delta = (event.count_delta || {}) as { unanswered?: number; ended?: number };
    setCounts((current) => ({
      unanswered: Math.max(0, current.unanswered + Number(delta.unanswered || 0)),
      ended: Math.max(0, current.ended + Number(delta.ended || 0)),
    }));

    const removed = new Set((event.message_ids || event.removed_message_ids || []) as string[]);
    const row = event.row as MessageRow | undefined;
    setItems((current) => {
      let next = current.filter((item) => !removed.has(item.message_id));
      if (row) next = next.filter((item) => item.channel !== row.channel || item.message_id !== row.message_id);
      const belongsHere = row && ((tab === "unanswered" && (event.action === "upsert" || event.action === "reopened")) || (tab === "ended" && event.action === "ended"));
      if (belongsHere && row) next = [row, ...next].sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at)).slice(0, 100);
      return next;
    });
  }, [tab]);

  const applyMissedCallEvent = useCallback((event: RealtimeEvent) => {
    if (event.type !== "missed_call_state_changed") return;
    if (loadingRef.current) { pendingEvents.current.push(event); return; }
    const eventId = String(event.event_id || "");
    if (!eventId || processedEvents.current.has(eventId)) return;
    processedEvents.current.add(eventId);
    setMissedCallCount((current) => Math.max(0, current + Number(event.count_delta || 0)));
    const removed = new Set((event.call_ids || []) as string[]);
    const row = event.row as MissedCallRow | undefined;
    setMissedCalls((current) => {
      let next = current.filter((item) => !removed.has(item.call_id));
      if (row) next = next.filter((item) => item.client_identifier !== row.client_identifier || item.company_identifier !== row.company_identifier);
      if (row && event.action === "upsert") next = [row, ...next].sort((a, b) => Date.parse(b.latest_missed_at) - Date.parse(a.latest_missed_at)).slice(0, 100);
      return next;
    });
  }, []);

  useRealtimeUpdates(token, (event) => {
    if (event.type === "sales_work_queue_batch") {
      ((event.events || []) as RealtimeEvent[]).forEach((item) => {
        applyRealtimeEvent(item);
        applyMissedCallEvent(item);
      });
      return;
    }
    applyRealtimeEvent(event);
    applyMissedCallEvent(event);
  });

  useEffect(() => {
    if (loading || pendingEvents.current.length === 0) return;
    const queued = pendingEvents.current.splice(0);
    queued.forEach((event) => {
      applyRealtimeEvent(event);
      applyMissedCallEvent(event);
    });
  }, [loading, applyRealtimeEvent, applyMissedCallEvent]);

  const setEnded = async (row: MessageRow, ended: boolean) => {
    const response = await fetch(`${API_BASE}/api/unanswered-messages/end`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ channel: row.channel, message_id: row.message_id, ended }),
    });
    if (!response.ok) { setError(`HTTP ${response.status}`); return; }
    const result = await response.json();
    if (result.event) applyRealtimeEvent(result.event as RealtimeEvent);
  };

  const headers = ["Client", "Platform", "Message", "Rep", "Company", "Message Time", "Action"];
  const cell = { padding: "13px 16px", borderBottom: "1px solid #e2e8f0", color: "#334155" } as const;

  return (
    <main style={{ padding: 24, width: "100%", maxWidth: 1280, margin: "0 auto", boxSizing: "border-box" }}>
      <h1 style={{ margin: 0, color: "#032d60", fontSize: 24 }}>Sales Work Queue</h1>
      <p style={{ margin: "6px 0 20px", color: "#64748b" }}>Sales items that need attention.</p>
      {error ? <p style={{ color: "#b91c1c" }}>{error}</p> : null}
      <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
        <div style={{ padding: "16px 18px 0" }}>
          <h2 style={{ margin: 0, color: "#032d60", fontSize: 18 }}>Unanswered Messages ({counts.unanswered})</h2>
          <div style={{ display: "flex", gap: 8, borderBottom: "1px solid #d8dde6", marginTop: 8 }}>
            {([ ["unanswered", "Unanswered Messages", counts.unanswered], ["ended", "Ended Chats", counts.ended] ] as const).map(([key, label, count]) => (
              <button key={key} type="button" onClick={() => setTab(key)} style={{ border: 0, borderBottom: tab === key ? "3px solid #0b5cab" : "3px solid transparent", background: "transparent", color: tab === key ? "#032d60" : "#475569", padding: "10px 14px", fontWeight: tab === key ? 700 : 500, cursor: "pointer" }}>{label} ({count})</button>
            ))}
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", minWidth: 900, borderCollapse: "collapse", tableLayout: "fixed" }}>
          <thead><tr style={{ background: "#f8fafc", borderBottom: "1px solid #d8dde6" }}>{headers.map((header) => <th key={header} style={{ padding: "13px 16px", color: "#475569", fontSize: 12, textAlign: "left", textTransform: "uppercase" }}>{header}</th>)}</tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={7} style={{ padding: 32, textAlign: "center" }}>Loading messages…</td></tr> : null}
            {!loading && items.length === 0 ? <tr><td colSpan={7} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>{tab === "unanswered" ? "No unanswered messages." : "No ended chats."}</td></tr> : null}
            {!loading && items.map((row) => <tr key={`${row.channel}:${row.message_id}`}>
              <td style={cell}>{row.lead_id ? <Link to={`/leads/${row.lead_id}`} state={{ backTo: "/sales-work-queue", backLabel: "← Back to Sales Work Queue" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</Link> : row.channel === "messenger" ? <a href={`https://www.facebook.com/latest/${encodeURIComponent(row.client)}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</a> : <strong>{row.client}</strong>}</td>
              <td style={cell}>{row.channel === "sms" ? "SMS" : row.channel === "instagram" ? "Instagram" : "Messenger"}</td>
              <td style={{ ...cell, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.message}>{row.message || "No preview"}</td>
              <td style={cell}>{row.rep}</td><td style={cell}>{row.company || "—"}</td><td style={cell}>{new Date(row.occurred_at).toLocaleString()}</td>
              <td style={cell}><label><input type="checkbox" checked={tab === "ended"} onChange={() => void setEnded(row, tab === "unanswered")} /> {tab === "unanswered" ? "Ended" : "Reopen"}</label></td>
            </tr>)}
          </tbody>
        </table>
        </div>
      </section>

      <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden", marginTop: 18 }}>
        <div style={{ padding: "16px 18px" }}>
          <h2 style={{ margin: 0, color: "#032d60", fontSize: 18 }}>Missed Calls ({missedCallCount})</h2>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", minWidth: 760, borderCollapse: "collapse", tableLayout: "fixed" }}>
            <thead><tr style={{ background: "#f8fafc", borderTop: "1px solid #d8dde6", borderBottom: "1px solid #d8dde6" }}>
              {['Client', 'Rep', 'Company', 'Missed Calls', 'First Missed', 'Latest Missed'].map((header) => <th key={header} style={{ padding: "13px 16px", color: "#475569", fontSize: 12, textAlign: "left", textTransform: "uppercase" }}>{header}</th>)}
            </tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={6} style={{ padding: 32, textAlign: "center" }}>Loading missed calls…</td></tr> : null}
              {!loading && missedCalls.length === 0 ? <tr><td colSpan={6} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>No missed calls.</td></tr> : null}
              {!loading && missedCalls.map((row) => <tr key={`${row.client_identifier}:${row.company_identifier}`}>
                <td style={cell}>{row.lead_id ? <Link to={`/leads/${row.lead_id}`} state={{ backTo: "/sales-work-queue", backLabel: "← Back to Sales Work Queue" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</Link> : <strong>{row.client}</strong>}</td>
                <td style={cell}>{row.rep}</td>
                <td style={cell}>{row.company || row.company_identifier}</td>
                <td style={cell}><strong>{row.missed_count}</strong></td>
                <td style={cell}>{new Date(row.first_missed_at).toLocaleString()}</td>
                <td style={cell}>{new Date(row.latest_missed_at).toLocaleString()}</td>
              </tr>)}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
