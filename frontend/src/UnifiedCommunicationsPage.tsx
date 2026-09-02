import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import MessageAttachments, { attachmentSummary, MessageAttachment } from "./MessageAttachments";
import ConnectCommunicationLeadModal, { CommunicationTarget } from "./ConnectCommunicationLeadModal";

type Contact = { key: string; lead_id: string; client: string; rep: string; company: string; timestamp: number; last_preview: string; sources: Array<Record<string, unknown>> };
type TimelineItem = { id: string; kind: "message" | "call"; channel: string; direction: "inbound" | "outbound"; timestamp: number; text: string; attachments?: MessageAttachment[]; senderLabel?: string; answered?: boolean; reason?: string };
const stamp = (value: unknown) => { const n = Number(value || 0); return n >= 1e12 ? n / 1000 : n; };
const digits = (value: unknown) => { const normalized = String(value || "").replace(/\D/g, ""); return normalized.length >= 10 ? normalized.slice(-10) : normalized; };
const displayPhone = (value: unknown) => { const valueDigits = digits(value); return valueDigits.length === 10 ? `(${valueDigits.slice(0, 3)}) ${valueDigits.slice(3, 6)}-${valueDigits.slice(6)}` : String(value || ""); };
const when = (value: number) => new Date(value * 1000).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
const elapsed = (seconds: number) => seconds < 60 ? `${Math.max(1, Math.round(seconds))} sec` : seconds < 3600 ? `${Math.round(seconds / 60)} min` : `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
const automatedSender = (item: Record<string, unknown>) => {
  const value = String(item.sales_name || item.role || "").trim().toLowerCase();
  return ["ai", "assistant", "bot"].includes(value) ? "AI" : "";
};
const messagePreview = (source: Record<string, unknown>, platform: string) => {
  const channel = platform === "sms" ? "SMS" : platform === "instagram" ? "Instagram" : "Messenger";
  const sender = String(source.sender_label || "");
  return `${channel} · ${sender ? `${sender}: ` : ""}${String(source.message || attachmentSummary(source.attachments as MessageAttachment[]) || "No preview")}`;
};
const companyAndRep = (item: Contact) => {
  const values = [item.company, item.rep].filter((value) => value && value !== "Unassigned");
  return [...new Set(values)].join(" · ");
};
const destinationLabel = (item: Contact) => {
  for (const source of item.sources) {
    const name = String(source.destination_name || "").trim();
    const phone = String(source.destination_phone || (source.source_type === "sms" ? source.company_phone_identifier : source.source_type === "calls" ? source.company_identifier : "") || "").trim();
    if (name || phone) return [name, phone ? displayPhone(phone) : ""].filter(Boolean).join(" · ");
  }
  return "Unknown destination";
};
const destinationDirection = (item: Contact) => {
  const latest = [...item.sources].sort((left, right) => stamp(right.timestamp) - stamp(left.timestamp))[0];
  const direction = String(latest?.direction || "").toLowerCase();
  return ["inbound", "received", "user"].includes(direction) ? "inbound" : "outbound";
};
const contactCompanies = (item: Contact) => [...new Set([
  item.company,
  ...item.sources.filter((source) => source.destination_type === "company").map((source) => String(source.destination_name || "")),
].filter(Boolean))];
const contactReps = (item: Contact) => [...new Set([
  item.rep,
  ...item.sources.filter((source) => source.destination_type === "rep").map((source) => String(source.destination_name || "")),
].filter((value) => value && value !== "Unassigned"))];

const associationTarget = (item: Contact): CommunicationTarget | null => {
  for (const source of item.sources) {
    const channel = String(source.source_type || "");
    const clientIdentifier = String(source.client_identifier || source.message_partition_key || "");
    const companyIdentifier = channel === "sms"
      ? String(source.company_phone_identifier || "")
      : String(source.company_identifier || "");
    if (channel && clientIdentifier && companyIdentifier) return { channel, clientIdentifier, companyIdentifier };
  }
  return null;
};

const CommunicationsContacts = memo(function CommunicationsContacts({ contacts, selected, loading, loadingMore, hasMore, repFilter, companyFilter, platformFilter, onSelect, onLoadMore, onConnect }: {
  contacts: Contact[];
  selected: string;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  repFilter: string;
  companyFilter: string;
  platformFilter: string;
  onSelect: (key: string) => void;
  onLoadMore: () => void;
  onConnect: (target: CommunicationTarget) => void;
}) {
  const [search, setSearch] = useState("");
  const shown = useMemo(() => {
    const query = search.trim().toLowerCase();
    const queryDigits = digits(query);
    return contacts.filter((item) => {
      const searchable = [item.key, item.client, item.company, item.rep, ...item.sources.flatMap((source) => [source.client_identifier, source.message_partition_key, source.company_identifier, source.company_phone_identifier, source.destination_phone, source.destination_name])]
        .map((value) => String(value || "").toLowerCase());
      if (query && !searchable.some((value) => value.includes(query) || (queryDigits.length >= 3 && digits(value).includes(queryDigits)))) return false;
      if (repFilter && !contactReps(item).includes(repFilter)) return false;
      if (companyFilter && !contactCompanies(item).includes(companyFilter)) return false;
      if (platformFilter && !item.sources.some((source) => String(source.source_type || "") === platformFilter)) return false;
      return true;
    });
  }, [contacts, search, repFilter, companyFilter, platformFilter]);
  const filtersActive = Boolean(search.trim() || repFilter || companyFilter || platformFilter);
  useEffect(() => {
    if (!filtersActive || loading || loadingMore || shown.length >= 20 || !hasMore) return;
    onLoadMore();
  }, [filtersActive, hasMore, loading, loadingMore, onLoadMore, shown.length]);

  return <aside className="communications-contacts" style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 9, overflow: "hidden" }}>
    <div style={{ padding: 12, borderBottom: "1px solid #d8dde6" }}>
      <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search clients or numbers" style={{ width: "100%", padding: "9px 10px", border: "1px solid #cbd5e1", borderRadius: 6, boxSizing: "border-box" }} />
    </div>
    <div onScroll={(event) => { const element = event.currentTarget; if (element.scrollHeight - element.scrollTop - element.clientHeight < 240) onLoadMore(); }} style={{ maxHeight: "calc(100vh - 190px)", overflowY: "auto" }}>
      {loading ? <p style={{ padding: 14 }}>Loading…</p> : shown.map((item) => <button key={item.key} type="button" onClick={() => onSelect(item.key)} onContextMenu={!item.lead_id ? (event) => { const target = associationTarget(item); if (target) { event.preventDefault(); onConnect(target); } } : undefined} title={!item.lead_id ? "Right-click to connect this communication to a lead" : undefined} style={{ display: "block", width: "100%", padding: "12px 14px", textAlign: "left", border: 0, borderBottom: "1px solid #e2e8f0", background: selected === item.key ? "#eef6ff" : "#fff", cursor: "pointer" }}><strong style={{ display: "block", color: "#032d60" }}>{item.client}</strong><span style={{ display: "block", color: "#475569", fontSize: 12 }}>{destinationDirection(item) === "outbound" ? "From" : "To"}: {destinationLabel(item)} · {when(item.timestamp)}</span>{companyAndRep(item) ? <span style={{ display: "block", color: "#64748b", fontSize: 12 }}>Assigned: {companyAndRep(item)}</span> : null}<span title={item.last_preview} style={{ display: "block", marginTop: 4, color: "#475569", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.last_preview}</span></button>)}
      {loadingMore ? <div style={{ padding: 12, textAlign: "center", color: "#64748b", fontSize: 12 }}>Loading more…</div> : null}
    </div>
  </aside>;
});

export default function UnifiedCommunicationsPage() {
  const { token } = useAuth(); const [contacts, setContacts] = useState<Contact[]>([]); const [selected, setSelected] = useState(""); const [timeline, setTimeline] = useState<TimelineItem[]>([]); const [loading, setLoading] = useState(true); const [historyLoading, setHistoryLoading] = useState(false); const [error, setError] = useState("");
  const [repFilter, setRepFilter] = useState(""); const [companyFilter, setCompanyFilter] = useState(""); const [platformFilter, setPlatformFilter] = useState("");
  const [directoryCompanies, setDirectoryCompanies] = useState<string[]>([]); const [directoryReps, setDirectoryReps] = useState<string[]>([]);
  const [cursors, setCursors] = useState({ sms: "", meta: "", calls: "" }); const [more, setMore] = useState({ sms: true, meta: true, calls: true }); const [loadingMore, setLoadingMore] = useState(false);
  const [connectTarget, setConnectTarget] = useState<CommunicationTarget | null>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const loadingMoreRef = useRef(false);
  useEffect(() => { (async () => { setLoading(true); try {
    const urls = ["/api/chats?source=sms&limit=20", "/api/chats?source=meta&limit=20", "/api/chats/calls?limit=50"];
    const responses = await Promise.all(urls.map((url) => fetch(`${API_BASE}${url}`, { headers: authHeaders(token) })));
    if (responses.some((response) => !response.ok)) throw new Error("Could not load communications");
    const [sms, meta, calls] = await Promise.all(responses.map((response) => response.json()));
    const map = new Map<string, Contact>();
    for (const source of [...(sms.items || []), ...(meta.items || []), ...(calls.items || [])]) {
      const leadId = String(source.lead_id || ""); const platform = String(source.platform || (source.call_id ? "calls" : ""));
      const clientId = String(source.client_identifier || source.message_partition_key || source.client || "");
      const key = platform === "calls"
        ? `phone:${digits(source.client_identifier)}:${digits(source.company_identifier)}`
        : platform === "sms"
          ? `phone:${digits(source.message_partition_key)}:${digits(source.company_phone_identifier)}`
          : `meta:${platform}:${String(source.message_partition_key || "")}:${String(source.company_identifier || "")}`;
      const value = map.get(key) || { key, lead_id: leadId, client: String(source.client || clientId), rep: String(source.rep || ""), company: String(source.company || ""), timestamp: 0, last_preview: "", sources: [] };
      value.sources.push({ ...source, source_type: platform });
      const sourceTimestamp = stamp(source.timestamp);
      if (sourceTimestamp >= value.timestamp) {
        value.timestamp = sourceTimestamp;
        value.last_preview = platform === "calls"
          ? `${String(source.direction || "").toLowerCase() === "inbound" ? "Inbound" : "Outbound"} call · ${source.answered ? "Answered" : "Not answered"}`
          : messagePreview(source, platform);
      }
      map.set(key, value);
    }
    const next = [...map.values()].sort((a, b) => b.timestamp - a.timestamp); setContacts(next); setSelected((current) => current || next[0]?.key || "");
    setCursors({ sms: sms.next_cursor || "", meta: meta.next_cursor || "", calls: calls.next_cursor || "" }); setMore({ sms: Boolean(sms.has_more), meta: Boolean(meta.has_more), calls: Boolean(calls.has_more) });
  } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load communications"); } finally { setLoading(false); } })(); }, [token]);

  useEffect(() => {
    Promise.allSettled([
      fetch(`${API_BASE}/api/companies/mine`, { headers: authHeaders(token) }).then((response) => response.ok ? response.json() : []),
      fetch(`${API_BASE}/api/users/mine-reps`, { headers: authHeaders(token) }).then((response) => response.ok ? response.json() : []),
    ]).then(([companiesResult, repsResult]) => {
      if (companiesResult.status === "fulfilled" && Array.isArray(companiesResult.value)) setDirectoryCompanies(companiesResult.value.map((item) => String(item.name || "")).filter(Boolean));
      if (repsResult.status === "fulfilled" && Array.isArray(repsResult.value)) setDirectoryReps(repsResult.value.map((item) => String(item.name || "")).filter(Boolean));
    });
  }, [token]);

  const loadMore = useCallback(async () => {
    if (loadingMoreRef.current || !Object.values(more).some(Boolean)) return;
    loadingMoreRef.current = true; setLoadingMore(true);
    try {
      const allowedSources = platformFilter === "calls" ? ["calls"] : platformFilter === "sms" ? ["sms"] : ["messenger", "instagram"].includes(platformFilter) ? ["meta"] : ["sms", "meta", "calls"];
      const sources = (["sms", "meta", "calls"] as const).filter((source) => allowedSources.includes(source) && more[source]);
      if (!sources.length) return;
      const responses = await Promise.all(sources.map((source) => { const base = source === "calls" ? "/api/chats/calls?limit=50" : `/api/chats?source=${source}&limit=20`; return fetch(`${API_BASE}${base}&cursor=${encodeURIComponent(cursors[source])}`, { headers: authHeaders(token) }); }));
      if (responses.some((response) => !response.ok)) throw new Error("Could not load more communications");
      const pages = await Promise.all(responses.map((response) => response.json()));
      const incoming = pages.flatMap((page) => page.items || []);
      setContacts((current) => {
        const map = new Map(current.map((item) => [item.key, { ...item, sources: [...item.sources] }]));
        for (const source of incoming) {
          const leadId = String(source.lead_id || ""); const platform = String(source.platform || (source.call_id ? "calls" : "")); const clientId = String(source.client_identifier || source.message_partition_key || source.client || "");
          const key = platform === "calls" ? `phone:${digits(source.client_identifier)}:${digits(source.company_identifier)}` : platform === "sms" ? `phone:${digits(source.message_partition_key)}:${digits(source.company_phone_identifier)}` : `meta:${platform}:${String(source.message_partition_key || "")}:${String(source.company_identifier || "")}`;
          const value = map.get(key) || { key, lead_id: leadId, client: String(source.client || clientId), rep: String(source.rep || ""), company: String(source.company || ""), timestamp: 0, last_preview: "", sources: [] };
          const sourceKey = `${platform}:${String(source.message_partition_key || source.client_identifier || "")}:${String(source.company_identifier || source.company_phone_identifier || "")}`;
          const sourceExists = value.sources.some((existing) => `${String(existing.source_type || "")}:${String(existing.message_partition_key || existing.client_identifier || "")}:${String(existing.company_identifier || existing.company_phone_identifier || "")}` === sourceKey);
          if (!sourceExists) value.sources.push({ ...source, source_type: platform }); const sourceTimestamp = stamp(source.timestamp);
          if (sourceTimestamp >= value.timestamp) { value.timestamp = sourceTimestamp; value.last_preview = platform === "calls" ? `${String(source.direction || "").toLowerCase() === "inbound" ? "Inbound" : "Outbound"} call · ${source.answered ? "Answered" : "Not answered"}` : messagePreview(source, platform); }
          map.set(key, value);
        }
        return [...map.values()].sort((a, b) => b.timestamp - a.timestamp);
      });
      setCursors((current) => { const next = { ...current }; sources.forEach((source, index) => { next[source] = pages[index].next_cursor || ""; }); return next; });
      setMore((current) => { const next = { ...current }; sources.forEach((source, index) => { next[source] = Boolean(pages[index].has_more); }); return next; });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load more communications"); } finally { loadingMoreRef.current = false; setLoadingMore(false); }
  }, [cursors, more, platformFilter, token]);

  const contact = contacts.find((item) => item.key === selected);
  const loadHistory = useCallback(async (current: Contact) => { setHistoryLoading(true); setError(""); try {
    const requestUrls = new Set<string>();
    for (const source of current.sources) {
      const type = String(source.source_type || ""); const partition = String(source.message_partition_key || "");
      if (type === "sms") {
        requestUrls.add(`/api/sms/${encodeURIComponent(partition)}?aircall_number_id=${encodeURIComponent(String(source.company_identifier || ""))}`);
        if (source.company_phone_identifier) requestUrls.add(`/api/chats/calls/history?phone=${encodeURIComponent(partition)}&company_number=${encodeURIComponent(String(source.company_phone_identifier))}`);
      } else if (type === "messenger" || type === "instagram") {
        requestUrls.add(`/api/meta/${type}/${encodeURIComponent(partition)}`);
      } else if (type === "calls") {
        const clientPhone = String(source.client_identifier || "");
        requestUrls.add(`/api/chats/calls/history?phone=${encodeURIComponent(clientPhone)}&company_number=${encodeURIComponent(String(source.company_identifier || ""))}`);
        const numberId = String(source.destination_aircall_number_id || "");
        if (numberId) requestUrls.add(`/api/sms/${encodeURIComponent(clientPhone)}?aircall_number_id=${encodeURIComponent(numberId)}`);
      }
    }
    const requests = [...requestUrls].map((url) => fetch(`${API_BASE}${url}`, { headers: authHeaders(token) }));
    const responses = await Promise.all(requests); const failedRequests = responses.filter((response) => !response.ok).length; const bodies = await Promise.all(responses.map((response) => response.ok ? response.json() : Promise.resolve({})));
    const result: TimelineItem[] = [];
    bodies.forEach((body) => {
      for (const item of body.messages || []) { const platform = String(item.platform || (item.phone_number ? "sms" : "messenger")); const inbound = platform === "sms" ? ["received", "inbound"].includes(String(item.direction || "").toLowerCase()) : ["user", "client", "customer"].includes(String(item.role || "").toLowerCase()); result.push({ id: `m:${item.message_id}`, kind: "message", channel: platform, direction: inbound ? "inbound" : "outbound", timestamp: stamp(item.timestamp), text: String(item.text || ""), attachments: item.attachments || [], senderLabel: automatedSender(item) }); }
      for (const item of body.calls || []) { result.push({ id: `c:${item.message_id}`, kind: "call", channel: "call", direction: String(item.direction).toLowerCase() === "inbound" ? "inbound" : "outbound", timestamp: stamp(item.timestamp), text: "", answered: Boolean(item.answered), reason: String(item.reason || "") }); }
    });
    setTimeline([...new Map(result.map((item) => [item.id, item])).values()].sort((a, b) => a.timestamp - b.timestamp));
    if (failedRequests) setError(`${failedRequests} communication source${failedRequests === 1 ? "" : "s"} could not be loaded. The timeline may be incomplete.`);
  } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load communication history"); } finally { setHistoryLoading(false); } }, [token]);
  useEffect(() => { if (contact) void loadHistory(contact); else setTimeline([]); }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (historyLoading) return;
    const frame = requestAnimationFrame(() => {
      const list = timelineRef.current;
      if (list) list.scrollTop = list.scrollHeight;
    });
    return () => cancelAnimationFrame(frame);
  }, [selected, historyLoading, timeline.length]);

  const filterOptions = useMemo(() => ({
    reps: [...new Set(["Unassigned", ...directoryReps, ...contacts.flatMap(contactReps)])].sort(),
    companies: [...new Set([...directoryCompanies, ...contacts.flatMap(contactCompanies)])].sort(),
    platforms: ["calls", "instagram", "messenger", "sms"],
  }), [contacts, directoryCompanies, directoryReps]);
  function callbackFor(index: number) { const item = timeline[index]; if (item.kind !== "call" || item.direction !== "inbound" || item.answered) return undefined; return timeline.slice(index + 1).find((next) => next.kind === "call" && next.direction === "outbound"); }
  function missedBefore(index: number) { const item = timeline[index]; if (item.kind !== "call" || item.direction !== "outbound") return undefined; const prior = timeline.slice(0, index).filter((candidate) => candidate.kind === "call" && candidate.direction === "inbound" && !candidate.answered); return [...prior].reverse().find((missed) => !timeline.some((candidate) => candidate.kind === "call" && candidate.direction === "outbound" && candidate.timestamp > missed.timestamp && candidate.timestamp < item.timestamp)); }

  return <main style={{ padding: 20, width: "100%", maxWidth: 1400, margin: "0 auto", boxSizing: "border-box" }}><div style={{ marginBottom: 14 }}><h1 style={{ margin: 0, color: "#032d60", fontSize: 24 }}>Communications</h1><p style={{ margin: "5px 0 0", color: "#64748b" }}>Messages and calls in one client timeline.</p></div>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
      <select aria-label="Filter communications by rep" value={repFilter} onChange={(event) => setRepFilter(event.target.value)} style={filterSelect}><option value="">All reps</option>{filterOptions.reps.map((value) => <option key={value} value={value}>{value}</option>)}</select>
      <select aria-label="Filter communications by company" value={companyFilter} onChange={(event) => setCompanyFilter(event.target.value)} style={filterSelect}><option value="">All companies</option>{filterOptions.companies.map((value) => <option key={value} value={value}>{value}</option>)}</select>
      <select aria-label="Filter communications by platform" value={platformFilter} onChange={(event) => setPlatformFilter(event.target.value)} style={filterSelect}><option value="">All platforms</option>{filterOptions.platforms.map((value) => <option key={value} value={value}>{value === "calls" ? "Calls" : value === "sms" ? "SMS" : value.charAt(0).toUpperCase() + value.slice(1)}</option>)}</select>
    </div>
    {error ? <p style={{ color: "#ba0517" }}>{error}</p> : null}<div className="communications-workspace">
      <section className="communications-timeline" style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 9, minHeight: 560, overflow: "hidden" }}>
        <header style={{ padding: "12px 18px", borderBottom: "1px solid #d8dde6", background: "#f8fafc" }}>{contact ? <>{contact.lead_id ? <Link to={`/leads/${contact.lead_id}`} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{contact.client}</Link> : <strong>{contact.client}</strong>}<div style={{ color: "#475569", marginTop: 4, fontSize: 12 }}><strong>{destinationDirection(contact) === "outbound" ? "Sent from:" : "Received by:"}</strong> {destinationLabel(contact)}</div>{companyAndRep(contact) ? <div style={{ color: "#64748b", marginTop: 2, fontSize: 12 }}><strong>Lead assigned to:</strong> {companyAndRep(contact)}</div> : null}</> : "Select a client"}</header>
        <div ref={timelineRef} style={{ padding: 18, maxHeight: "calc(100vh - 230px)", overflowY: "auto" }}>{historyLoading ? <p>Loading communication…</p> : timeline.map((item, index) => { const callback = callbackFor(index); const missed = missedBefore(index); return <div key={item.id} style={{ display: "flex", justifyContent: item.direction === "outbound" ? "flex-end" : "flex-start", margin: "9px 0" }}><article style={{ maxWidth: "72%", padding: "10px 13px", borderRadius: 14, background: item.direction === "outbound" ? "#e3f2fd" : "#f3f4f6", color: "#1e293b" }}>{item.kind === "message" ? <>{item.senderLabel ? <strong style={{ display: "block", marginBottom: 5, color: "#5c2d91", fontSize: 12 }}>{item.senderLabel}</strong> : null}{item.text ? <div style={{ whiteSpace: "pre-wrap" }}>{item.text}</div> : null}<MessageAttachments attachments={item.attachments} /></> : <><strong>{item.direction === "inbound" ? "Inbound call" : "Outbound call"}</strong><div style={{ fontSize: 12, color: "#64748b" }}>{item.answered ? "Answered" : "Not answered"}{item.reason ? ` · ${item.reason}` : ""}</div>{callback ? <div style={{ color: "#2e844a", fontSize: 12, fontWeight: 700 }}>Called back in {elapsed(callback.timestamp - item.timestamp)}</div> : item.direction === "inbound" && !item.answered ? <div style={{ color: "#ba0517", fontSize: 12, fontWeight: 700 }}>No callback yet</div> : null}{missed ? <div style={{ color: "#2e844a", fontSize: 12, fontWeight: 700 }}>Callback after {elapsed(item.timestamp - missed.timestamp)}</div> : null}</>}<footer style={{ marginTop: 5, color: "#64748b", fontSize: 11 }}>{item.channel.toUpperCase()} · {when(item.timestamp)}</footer></article></div>; })}{!historyLoading && contact && timeline.length === 0 ? <p style={{ textAlign: "center", color: "#64748b" }}>No communication history found.</p> : null}</div>
      </section>
      <CommunicationsContacts contacts={contacts} selected={selected} loading={loading} loadingMore={loadingMore} hasMore={platformFilter === "calls" ? more.calls : platformFilter === "sms" ? more.sms : ["messenger", "instagram"].includes(platformFilter) ? more.meta : Object.values(more).some(Boolean)} repFilter={repFilter} companyFilter={companyFilter} platformFilter={platformFilter} onSelect={setSelected} onLoadMore={loadMore} onConnect={setConnectTarget} />
    </div>
    {connectTarget ? <ConnectCommunicationLeadModal target={connectTarget} token={token} onClose={() => setConnectTarget(null)} onConnected={(lead) => { setContacts((current) => current.map((item) => item.key === selected ? { ...item, lead_id: lead.id, client: lead.name, company: lead.company, rep: lead.rep || "" } : item)); setConnectTarget(null); }} /> : null}
  </main>;
}

const filterSelect: React.CSSProperties = { minWidth: 180, padding: "9px 32px 9px 10px", border: "1px solid #cbd5e1", borderRadius: 6, background: "#fff", color: "#334155" };
