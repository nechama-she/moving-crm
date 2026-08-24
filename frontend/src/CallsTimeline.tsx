import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders } from "./AuthContext";

type CallRow = { call_id: string; conversation_id: string; lead_id: string; client: string; client_identifier: string; company: string; rep: string; direction: "inbound" | "outbound"; answered: boolean; reason: string; timestamp: number };

function time(value: number) { return new Date(value * 1000).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }); }
function duration(seconds: number) { if (seconds < 60) return `${Math.max(1, Math.round(seconds))} sec`; if (seconds < 3600) return `${Math.round(seconds / 60)} min`; return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`; }

export default function CallsTimeline({ token, search }: { token: string; search: string }) {
  const [calls, setCalls] = useState<CallRow[]>([]); const [cursor, setCursor] = useState(""); const [hasMore, setHasMore] = useState(true); const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  const load = useCallback(async (next = "") => {
    if (loading || (!hasMore && next)) return; setLoading(true); setError("");
    try {
      const params = new URLSearchParams({ limit: "50" }); if (next) params.set("cursor", next);
      const response = await fetch(`${API_BASE}/api/chats/calls?${params}`, { headers: authHeaders(token) }); if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setCalls((current) => { const merged = new Map(current.map((call) => [call.call_id, call])); for (const call of data.items || []) merged.set(call.call_id, call); return [...merged.values()]; });
      setCursor(data.next_cursor || ""); setHasMore(Boolean(data.has_more));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load calls"); } finally { setLoading(false); }
  }, [hasMore, loading, token]);
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const groups = useMemo(() => {
    const grouped = new Map<string, CallRow[]>(); for (const call of calls) grouped.set(call.conversation_id, [...(grouped.get(call.conversation_id) || []), call]);
    const query = search.trim().toLowerCase();
    return [...grouped.entries()].map(([id, rows]) => ({ id, rows: rows.sort((a, b) => a.timestamp - b.timestamp) })).filter(({ rows }) => !query || [rows[0]?.client, rows[0]?.rep, rows[0]?.company, rows[0]?.client_identifier].some((value) => String(value || "").toLowerCase().includes(query))).sort((a, b) => b.rows[b.rows.length - 1].timestamp - a.rows[a.rows.length - 1].timestamp);
  }, [calls, search]);
  return <div style={{ display: "grid", gap: 14 }}>
    {groups.map(({ id, rows }) => { const latest = rows[rows.length - 1]; return <section key={id} style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 9, overflow: "hidden" }}>
      <header style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", padding: "13px 16px", background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}><div>{latest.lead_id ? <Link to={`/leads/${latest.lead_id}`} state={{ backTo: "/chats", backLabel: "← Back to Communications" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{latest.client}</Link> : <strong style={{ color: "#032d60" }}>{latest.client}</strong>}<span style={{ color: "#64748b", marginLeft: 10 }}>{latest.company}</span></div><span style={{ color: "#475569", fontSize: 13 }}>{latest.rep} · {rows.length} call{rows.length === 1 ? "" : "s"}</span></header>
      <div style={{ padding: "10px 18px 14px" }}>{rows.map((call, index) => { const callback = call.direction === "inbound" && !call.answered ? rows.slice(index + 1).find((candidate) => candidate.direction === "outbound") : undefined; return <div key={call.call_id} style={{ position: "relative", display: "grid", gridTemplateColumns: "22px minmax(150px,1fr) auto", gap: 10, padding: "8px 0" }}>{index < rows.length - 1 ? <span style={{ position: "absolute", left: 8, top: 25, bottom: -9, width: 2, background: "#d8dde6" }} /> : null}<span style={{ width: 18, height: 18, borderRadius: "50%", background: call.answered ? "#2e844a" : call.direction === "inbound" ? "#ba0517" : "#0b5cab", border: "3px solid #fff", boxShadow: "0 0 0 1px #cbd5e1", zIndex: 1 }} /><div><strong>{call.direction === "inbound" ? "Inbound call" : "Outbound callback"}</strong><div style={{ color: "#64748b", fontSize: 12 }}>{call.answered ? "Answered" : "Not answered"}{call.reason ? ` · ${call.reason}` : ""}</div>{call.direction === "inbound" && !call.answered ? <div style={{ color: callback ? "#2e844a" : "#ba0517", fontSize: 12, fontWeight: 700 }}>{callback ? `Called back in ${duration(callback.timestamp - call.timestamp)}` : "No callback yet"}</div> : null}</div><time style={{ color: "#64748b", fontSize: 12, whiteSpace: "nowrap" }}>{time(call.timestamp)}</time></div>; })}</div>
    </section>; })}
    {!loading && groups.length === 0 ? <div style={{ padding: 32, textAlign: "center", color: "#64748b", background: "#fff", border: "1px solid #d8dde6", borderRadius: 8 }}>No calls found.</div> : null}
    {error ? <p style={{ color: "#ba0517" }}>Could not load calls: {error}</p> : null}
    {hasMore ? <button type="button" disabled={loading} onClick={() => void load(cursor)} style={{ justifySelf: "center", border: "1px solid #0b5cab", background: "#fff", color: "#0b5cab", borderRadius: 5, padding: "8px 18px", fontWeight: 700 }}>{loading ? "Loading…" : "Load more calls"}</button> : null}
  </div>;
}
