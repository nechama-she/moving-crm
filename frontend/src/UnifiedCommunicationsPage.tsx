import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Contact = { key: string; lead_id: string; client: string; rep: string; company: string; timestamp: number; last_preview: string; sources: Array<Record<string, unknown>> };
type TimelineItem = { id: string; kind: "message" | "call"; channel: string; direction: "inbound" | "outbound"; timestamp: number; text: string; answered?: boolean; reason?: string };
const stamp = (value: unknown) => { const n = Number(value || 0); return n >= 1e12 ? n / 1000 : n; };
const digits = (value: unknown) => { const normalized = String(value || "").replace(/\D/g, ""); return normalized.length >= 10 ? normalized.slice(-10) : normalized; };
const when = (value: number) => new Date(value * 1000).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
const elapsed = (seconds: number) => seconds < 60 ? `${Math.max(1, Math.round(seconds))} sec` : seconds < 3600 ? `${Math.round(seconds / 60)} min` : `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
const companyAndRep = (item: Contact) => {
  const values = [item.company, item.rep].filter((value) => value && value !== "Unassigned");
  return [...new Set(values)].join(" · ") || "Unassigned";
};

export default function UnifiedCommunicationsPage() {
  const { token } = useAuth(); const [contacts, setContacts] = useState<Contact[]>([]); const [selected, setSelected] = useState(""); const [timeline, setTimeline] = useState<TimelineItem[]>([]); const [search, setSearch] = useState(""); const [loading, setLoading] = useState(true); const [historyLoading, setHistoryLoading] = useState(false); const [error, setError] = useState("");
  const [cursors, setCursors] = useState({ sms: "", meta: "", calls: "" }); const [more, setMore] = useState({ sms: true, meta: true, calls: true }); const [loadingMore, setLoadingMore] = useState(false);
  useEffect(() => { (async () => { setLoading(true); try {
    const urls = ["/api/chats?source=sms&limit=20", "/api/chats?source=meta&limit=20", "/api/chats/calls?limit=50"];
    const responses = await Promise.all(urls.map((url) => fetch(`${API_BASE}${url}`, { headers: authHeaders(token) })));
    if (responses.some((response) => !response.ok)) throw new Error("Could not load communications");
    const [sms, meta, calls] = await Promise.all(responses.map((response) => response.json()));
    const map = new Map<string, Contact>();
    for (const source of [...(sms.items || []), ...(meta.items || []), ...(calls.items || [])]) {
      const leadId = String(source.lead_id || ""); const platform = String(source.platform || (source.call_id ? "calls" : ""));
      const clientId = String(source.client_identifier || source.message_partition_key || source.client || "");
      const companyId = String(source.company || source.company_identifier || "");
      const key = platform === "calls"
        ? `phone:${digits(source.client_identifier)}:${digits(source.company_identifier)}`
        : platform === "sms"
          ? `phone:${digits(source.message_partition_key)}:${digits(source.company_phone_identifier)}`
          : `meta:${platform}:${String(source.message_partition_key || "")}:${String(source.company_identifier || "")}`;
      const value = map.get(key) || { key, lead_id: leadId, client: String(source.client || clientId), rep: String(source.rep || "Unassigned"), company: String(source.company || companyId), timestamp: 0, last_preview: "", sources: [] };
      value.sources.push({ ...source, source_type: platform });
      const sourceTimestamp = stamp(source.timestamp);
      if (sourceTimestamp >= value.timestamp) {
        value.timestamp = sourceTimestamp;
        value.last_preview = platform === "calls"
          ? `${String(source.direction || "").toLowerCase() === "inbound" ? "Inbound" : "Outbound"} call · ${source.answered ? "Answered" : "Not answered"}`
          : `${platform === "sms" ? "SMS" : platform === "instagram" ? "Instagram" : "Messenger"} · ${String(source.message || "No preview")}`;
      }
      map.set(key, value);
    }
    const next = [...map.values()].sort((a, b) => b.timestamp - a.timestamp); setContacts(next); setSelected((current) => current || next[0]?.key || "");
    setCursors({ sms: sms.next_cursor || "", meta: meta.next_cursor || "", calls: calls.next_cursor || "" }); setMore({ sms: Boolean(sms.has_more), meta: Boolean(meta.has_more), calls: Boolean(calls.has_more) });
  } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load communications"); } finally { setLoading(false); } })(); }, [token]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !Object.values(more).some(Boolean)) return; setLoadingMore(true);
    try {
      const sources = (["sms", "meta", "calls"] as const).filter((source) => more[source]);
      const responses = await Promise.all(sources.map((source) => { const base = source === "calls" ? "/api/chats/calls?limit=50" : `/api/chats?source=${source}&limit=20`; return fetch(`${API_BASE}${base}&cursor=${encodeURIComponent(cursors[source])}`, { headers: authHeaders(token) }); }));
      if (responses.some((response) => !response.ok)) throw new Error("Could not load more communications");
      const pages = await Promise.all(responses.map((response) => response.json()));
      const incoming = pages.flatMap((page) => page.items || []);
      setContacts((current) => {
        const map = new Map(current.map((item) => [item.key, { ...item, sources: [...item.sources] }]));
        for (const source of incoming) {
          const leadId = String(source.lead_id || ""); const platform = String(source.platform || (source.call_id ? "calls" : "")); const clientId = String(source.client_identifier || source.message_partition_key || source.client || ""); const companyId = String(source.company || source.company_identifier || "");
          const key = platform === "calls" ? `phone:${digits(source.client_identifier)}:${digits(source.company_identifier)}` : platform === "sms" ? `phone:${digits(source.message_partition_key)}:${digits(source.company_phone_identifier)}` : `meta:${platform}:${String(source.message_partition_key || "")}:${String(source.company_identifier || "")}`;
          const value = map.get(key) || { key, lead_id: leadId, client: String(source.client || clientId), rep: String(source.rep || "Unassigned"), company: String(source.company || companyId), timestamp: 0, last_preview: "", sources: [] };
          const sourceKey = `${platform}:${String(source.message_partition_key || source.client_identifier || "")}:${String(source.company_identifier || source.company_phone_identifier || "")}`;
          const sourceExists = value.sources.some((existing) => `${String(existing.source_type || "")}:${String(existing.message_partition_key || existing.client_identifier || "")}:${String(existing.company_identifier || existing.company_phone_identifier || "")}` === sourceKey);
          if (!sourceExists) value.sources.push({ ...source, source_type: platform }); const sourceTimestamp = stamp(source.timestamp);
          if (sourceTimestamp >= value.timestamp) { value.timestamp = sourceTimestamp; value.last_preview = platform === "calls" ? `${String(source.direction || "").toLowerCase() === "inbound" ? "Inbound" : "Outbound"} call · ${source.answered ? "Answered" : "Not answered"}` : `${platform === "sms" ? "SMS" : platform === "instagram" ? "Instagram" : "Messenger"} · ${String(source.message || "No preview")}`; }
          map.set(key, value);
        }
        return [...map.values()].sort((a, b) => b.timestamp - a.timestamp);
      });
      setCursors((current) => { const next = { ...current }; sources.forEach((source, index) => { next[source] = pages[index].next_cursor || ""; }); return next; });
      setMore((current) => { const next = { ...current }; sources.forEach((source, index) => { next[source] = Boolean(pages[index].has_more); }); return next; });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load more communications"); } finally { setLoadingMore(false); }
  }, [cursors, loadingMore, more, token]);

  const contact = contacts.find((item) => item.key === selected);
  const loadHistory = useCallback(async (current: Contact) => { setHistoryLoading(true); setError(""); try {
    const requests: Promise<Response>[] = [];
    for (const source of current.sources) {
      const type = String(source.source_type || ""); const partition = String(source.message_partition_key || "");
      if (type === "sms") requests.push(fetch(`${API_BASE}/api/sms/${encodeURIComponent(partition)}?aircall_number_id=${encodeURIComponent(String(source.company_identifier || ""))}`, { headers: authHeaders(token) }));
      else if (type === "messenger" || type === "instagram") requests.push(fetch(`${API_BASE}/api/meta/${type}/${encodeURIComponent(partition)}`, { headers: authHeaders(token) }));
      else if (type === "calls") requests.push(fetch(`${API_BASE}/api/chats/calls/history?phone=${encodeURIComponent(String(source.client_identifier || ""))}&company_number=${encodeURIComponent(String(source.company_identifier || ""))}`, { headers: authHeaders(token) }));
    }
    const responses = await Promise.all(requests); const bodies = await Promise.all(responses.map((response) => response.ok ? response.json() : Promise.resolve({})));
    const result: TimelineItem[] = [];
    bodies.forEach((body) => {
      for (const item of body.messages || []) { const platform = String(item.platform || (item.phone_number ? "sms" : "messenger")); const inbound = platform === "sms" ? ["received", "inbound"].includes(String(item.direction || "").toLowerCase()) : ["user", "client", "customer"].includes(String(item.role || "").toLowerCase()); result.push({ id: `m:${item.message_id}`, kind: "message", channel: platform, direction: inbound ? "inbound" : "outbound", timestamp: stamp(item.timestamp), text: String(item.text || "") }); }
      for (const item of body.calls || []) { result.push({ id: `c:${item.message_id}`, kind: "call", channel: "call", direction: String(item.direction).toLowerCase() === "inbound" ? "inbound" : "outbound", timestamp: stamp(item.timestamp), text: "", answered: Boolean(item.answered), reason: String(item.reason || "") }); }
    });
    setTimeline([...new Map(result.map((item) => [item.id, item])).values()].sort((a, b) => a.timestamp - b.timestamp));
  } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load communication history"); } finally { setHistoryLoading(false); } }, [token]);
  useEffect(() => { if (contact) void loadHistory(contact); else setTimeline([]); }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(() => { const query = search.trim().toLowerCase(); return !query ? contacts : contacts.filter((item) => [item.client, item.company, item.rep].some((value) => value.toLowerCase().includes(query))); }, [contacts, search]);
  function callbackFor(index: number) { const item = timeline[index]; if (item.kind !== "call" || item.direction !== "inbound" || item.answered) return undefined; return timeline.slice(index + 1).find((next) => next.kind === "call" && next.direction === "outbound"); }
  function missedBefore(index: number) { const item = timeline[index]; if (item.kind !== "call" || item.direction !== "outbound") return undefined; const prior = timeline.slice(0, index).filter((candidate) => candidate.kind === "call" && candidate.direction === "inbound" && !candidate.answered); return [...prior].reverse().find((missed) => !timeline.some((candidate) => candidate.kind === "call" && candidate.direction === "outbound" && candidate.timestamp > missed.timestamp && candidate.timestamp < item.timestamp)); }

  return <main style={{ padding: 20, width: "100%", maxWidth: 1400, margin: "0 auto", boxSizing: "border-box" }}><div style={{ marginBottom: 14 }}><h1 style={{ margin: 0, color: "#032d60", fontSize: 24 }}>Communications</h1><p style={{ margin: "5px 0 0", color: "#64748b" }}>Messages and calls in one client timeline.</p></div>
    {error ? <p style={{ color: "#ba0517" }}>{error}</p> : null}<div className="communications-workspace">
      <section className="communications-timeline" style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 9, minHeight: 560, overflow: "hidden" }}>
        <header style={{ padding: "14px 18px", borderBottom: "1px solid #d8dde6", background: "#f8fafc" }}>{contact ? <>{contact.lead_id ? <Link to={`/leads/${contact.lead_id}`} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{contact.client}</Link> : <strong>{contact.client}</strong>}<span style={{ color: "#64748b", marginLeft: 10 }}>{contact.company} · {contact.rep}</span></> : "Select a client"}</header>
        <div style={{ padding: 18 }}>{historyLoading ? <p>Loading communication…</p> : timeline.map((item, index) => { const callback = callbackFor(index); const missed = missedBefore(index); return <div key={item.id} style={{ display: "flex", justifyContent: item.direction === "outbound" ? "flex-end" : "flex-start", margin: "9px 0" }}><article style={{ maxWidth: "72%", padding: "10px 13px", borderRadius: 14, background: item.direction === "outbound" ? "#e3f2fd" : "#f3f4f6", color: "#1e293b" }}>{item.kind === "message" ? <div style={{ whiteSpace: "pre-wrap" }}>{item.text || "No preview"}</div> : <><strong>{item.direction === "inbound" ? "Inbound call" : "Outbound call"}</strong><div style={{ fontSize: 12, color: "#64748b" }}>{item.answered ? "Answered" : "Not answered"}{item.reason ? ` · ${item.reason}` : ""}</div>{callback ? <div style={{ color: "#2e844a", fontSize: 12, fontWeight: 700 }}>Called back in {elapsed(callback.timestamp - item.timestamp)}</div> : item.direction === "inbound" && !item.answered ? <div style={{ color: "#ba0517", fontSize: 12, fontWeight: 700 }}>No callback yet</div> : null}{missed ? <div style={{ color: "#2e844a", fontSize: 12, fontWeight: 700 }}>Callback after {elapsed(item.timestamp - missed.timestamp)}</div> : null}</>}<footer style={{ marginTop: 5, color: "#64748b", fontSize: 11 }}>{item.channel.toUpperCase()} · {when(item.timestamp)}</footer></article></div>; })}{!historyLoading && contact && timeline.length === 0 ? <p style={{ textAlign: "center", color: "#64748b" }}>No communication history found.</p> : null}</div>
      </section>
      <aside className="communications-contacts" style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 9, overflow: "hidden" }}><div style={{ padding: 12, borderBottom: "1px solid #d8dde6" }}><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search clients or numbers" style={{ width: "100%", padding: "9px 10px", border: "1px solid #cbd5e1", borderRadius: 6, boxSizing: "border-box" }} /></div><div onScroll={(event) => { const element = event.currentTarget; if (element.scrollHeight - element.scrollTop - element.clientHeight < 240) void loadMore(); }} style={{ maxHeight: "calc(100vh - 190px)", overflowY: "auto" }}>{loading ? <p style={{ padding: 14 }}>Loading…</p> : shown.map((item) => <button key={item.key} type="button" onClick={() => setSelected(item.key)} style={{ display: "block", width: "100%", padding: "12px 14px", textAlign: "left", border: 0, borderBottom: "1px solid #e2e8f0", background: selected === item.key ? "#eef6ff" : "#fff", cursor: "pointer" }}><strong style={{ display: "block", color: "#032d60" }}>{item.client}</strong><span style={{ display: "block", color: "#64748b", fontSize: 12 }}>{companyAndRep(item)} · {when(item.timestamp)}</span><span title={item.last_preview} style={{ display: "block", marginTop: 4, color: "#475569", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.last_preview}</span></button>)}{loadingMore ? <div style={{ padding: 12, textAlign: "center", color: "#64748b", fontSize: 12 }}>Loading more…</div> : null}</div></aside>
    </div></main>;
}
