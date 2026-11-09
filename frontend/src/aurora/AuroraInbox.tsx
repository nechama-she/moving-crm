import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "../apiConfig";
import { authHeaders, useAuth } from "../AuthContext";
import type { Lead } from "../leadUtils";
import MessageAttachments, { attachmentSummary, MessageAttachment } from "../MessageAttachments";
import ConnectCommunicationLeadModal, { CommunicationTarget } from "../ConnectCommunicationLeadModal";
import Icon, { IconName } from "./Icon";
import { initials } from "./initials";

// Same data sources and grouping as the classic Communications page (UnifiedCommunicationsPage), new layout.
type Source = Record<string, unknown>;
type Contact = { key: string; lead_id: string; client: string; rep: string; company: string; timestamp: number; last_preview: string; channel: string; sources: Source[] };
type TimelineItem = { id: string; kind: "message" | "call"; channel: string; direction: "inbound" | "outbound"; timestamp: number; text: string; attachments?: MessageAttachment[]; senderLabel?: string; answered?: boolean; reason?: string };
type Cursors = { sms: string; meta: string; calls: string };

// The Gorilla Haulers website chat bot (BoxBot). Read-only here: never waiting, never connected by hand;
// it links to its lead by itself through lead_id once the visitor sends the request.
const WEBSITE_BOT = "website_gorillah_bot";
const stamp = (v: unknown) => { const n = Number(v || 0); return n >= 1e12 ? n / 1000 : n; };
const digits = (v: unknown) => { const d = String(v || "").replace(/\D/g, ""); return d.length >= 10 ? d.slice(-10) : d; };
const phone = (v: unknown) => { const d = digits(v); return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : String(v || ""); };
const timeLabel = (s: number) => {
  const d = new Date(s * 1000); const today = new Date();
  return d.toDateString() === today.toDateString() ? d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};
const fullTime = (s: number) => new Date(s * 1000).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const dayLabel = (s: number) => new Date(s * 1000).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
const elapsed = (sec: number) => sec < 60 ? `${Math.max(1, Math.round(sec))} sec` : sec < 3600 ? `${Math.round(sec / 60)} min` : `${Math.floor(sec / 3600)}h ${Math.round((sec % 3600) / 60)}m`;
const automated = (item: Source) => ["ai", "assistant", "bot"].includes(String(item.sales_name || item.role || "").trim().toLowerCase()) ? "AI" : "";
const PALETTE = [["#E4E6FF", "#3D3FE0"], ["#FFE3D3", "#8A3A12"], ["#DDF3E8", "#0F6B47"], ["#FFF0CC", "#7A4C00"], ["#F1EBFF", "#5B34C7"], ["#E3F3FF", "#0B5C8F"]];
const tint = (s: string) => PALETTE[[...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % PALETTE.length];
const CHANNEL: Record<string, { label: string; icon: IconName; color: string }> = {
  sms: { label: "SMS", icon: "message", color: "#4B4DF7" },
  calls: { label: "Call", icon: "phone", color: "#0E9F8A" },
  messenger: { label: "Messenger", icon: "message", color: "#1877F2" },
  instagram: { label: "Instagram", icon: "message", color: "#C13584" },
  [WEBSITE_BOT]: { label: "Website bot", icon: "spark", color: "#0F766E" },
};

function preview(source: Source, platform: string) {
  if (platform === "calls") return `${String(source.direction || "").toLowerCase() === "inbound" ? "Inbound" : "Outbound"} call · ${source.answered ? "answered" : "not answered"}`;
  const sender = String(source.sender_label || "");
  return `${sender ? `${sender}: ` : ""}${String(source.message || attachmentSummary(source.attachments as MessageAttachment[]) || "No preview")}`;
}
function keyFor(source: Source, platform: string) {
  return platform === "calls" ? `phone:${digits(source.client_identifier)}:${digits(source.company_identifier)}`
    : platform === "sms" ? `phone:${digits(source.message_partition_key)}:${digits(source.company_phone_identifier)}`
    : `meta:${platform}:${String(source.message_partition_key || "")}:${String(source.company_identifier || "")}`;
}
function merge(map: Map<string, Contact>, items: Source[]) {
  for (const source of items) {
    const platform = String(source.platform || (source.call_id ? "calls" : ""));
    const key = keyFor(source, platform);
    const clientId = String(source.client_identifier || source.message_partition_key || source.client || "");
    const value = map.get(key) || { key, lead_id: String(source.lead_id || ""), client: String(source.client || clientId), rep: String(source.rep || ""), company: String(source.company || ""), timestamp: 0, last_preview: "", channel: platform, sources: [] };
    const sk = `${platform}:${String(source.message_partition_key || source.client_identifier || "")}:${String(source.company_identifier || source.company_phone_identifier || "")}`;
    if (!value.sources.some(e => `${String(e.source_type || "")}:${String(e.message_partition_key || e.client_identifier || "")}:${String(e.company_identifier || e.company_phone_identifier || "")}` === sk)) value.sources.push({ ...source, source_type: platform });
    const t = stamp(source.timestamp);
    if (t >= value.timestamp) { value.timestamp = t; value.last_preview = preview(source, platform); value.channel = platform; }
    map.set(key, value);
  }
}
function destination(item: Contact) {
  for (const s of item.sources) {
    const name = String(s.destination_name || "").trim();
    const num = String(s.destination_phone || (s.source_type === "sms" ? s.company_phone_identifier : s.source_type === "calls" ? s.company_identifier : "") || "").trim();
    if (name || num) return [name, num ? phone(num) : ""].filter(Boolean).join(" · ");
  }
  return "Unknown destination";
}
function inboundLatest(item: Contact) {
  const latest = [...item.sources].sort((a, b) => stamp(b.timestamp) - stamp(a.timestamp))[0];
  if (latest?.source_type === WEBSITE_BOT) return false;
  return ["inbound", "received", "user"].includes(String(latest?.direction || "").toLowerCase());
}
function associationTarget(item: Contact): CommunicationTarget | null {
  for (const s of item.sources) {
    const channel = String(s.source_type || "");
    if (channel === WEBSITE_BOT) continue;
    const clientIdentifier = String(s.client_identifier || s.message_partition_key || "");
    const companyIdentifier = channel === "sms" ? String(s.company_phone_identifier || "") : String(s.company_identifier || "");
    if (channel && clientIdentifier && companyIdentifier) return { channel, clientIdentifier, companyIdentifier };
  }
  return null;
}
const reps = (c: Contact) => [...new Set([c.rep, ...c.sources.filter(s => s.destination_type === "rep").map(s => String(s.destination_name || ""))].filter(v => v && v !== "Unassigned"))];
const companies = (c: Contact) => [...new Set([c.company, ...c.sources.filter(s => s.destination_type === "company").map(s => String(s.destination_name || ""))].filter(Boolean))];

export default function AuroraInbox() {
  const { token } = useAuth();
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [selected, setSelected] = useState("");
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState("");
  const [repFilter, setRepFilter] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [onlyWaiting, setOnlyWaiting] = useState(false);
  const [cursors, setCursors] = useState<Cursors>({ sms: "", meta: "", calls: "" });
  const [more, setMore] = useState({ sms: true, meta: true, calls: true });
  const [loadingMore, setLoadingMore] = useState(false);
  const [connectTarget, setConnectTarget] = useState<CommunicationTarget | null>(null);
  const [directory, setDirectory] = useState<{ reps: string[]; companies: string[] }>({ reps: [], companies: [] });
  const timelineRef = useRef<HTMLDivElement>(null);
  const loadingMoreRef = useRef(false);

  useEffect(() => { (async () => {
    setLoading(true);
    try {
      const urls = ["/api/chats?source=sms&limit=20", "/api/chats?source=meta&limit=20", "/api/chats/calls?limit=50"];
      const responses = await Promise.all(urls.map(u => fetch(`${API_BASE}${u}`, { headers: authHeaders(token) })));
      if (responses.some(r => !r.ok)) throw new Error("Could not load communications");
      const [sms, meta, calls] = await Promise.all(responses.map(r => r.json()));
      const map = new Map<string, Contact>();
      merge(map, [...(sms.items || []), ...(meta.items || []), ...(calls.items || [])]);
      const next = [...map.values()].sort((a, b) => b.timestamp - a.timestamp);
      setContacts(next); setSelected(cur => cur || next[0]?.key || "");
      setCursors({ sms: sms.next_cursor || "", meta: meta.next_cursor || "", calls: calls.next_cursor || "" });
      setMore({ sms: Boolean(sms.has_more), meta: Boolean(meta.has_more), calls: Boolean(calls.has_more) });
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load communications"); } finally { setLoading(false); }
  })(); }, [token]);

  useEffect(() => {
    Promise.allSettled([
      fetch(`${API_BASE}/api/companies/mine`, { headers: authHeaders(token) }).then(r => (r.ok ? r.json() : [])),
      fetch(`${API_BASE}/api/users/mine-reps`, { headers: authHeaders(token) }).then(r => (r.ok ? r.json() : [])),
    ]).then(([c, r]) => setDirectory({
      companies: c.status === "fulfilled" && Array.isArray(c.value) ? c.value.map((i: { name?: string }) => String(i.name || "")).filter(Boolean) : [],
      reps: r.status === "fulfilled" && Array.isArray(r.value) ? r.value.map((i: { name?: string }) => String(i.name || "")).filter(Boolean) : [],
    }));
  }, [token]);

  const loadMore = useCallback(async () => {
    if (loadingMoreRef.current || !Object.values(more).some(Boolean)) return;
    loadingMoreRef.current = true; setLoadingMore(true);
    try {
      const allowed = channel === "calls" ? ["calls"] : channel === "sms" ? ["sms"] : ["messenger", "instagram", WEBSITE_BOT].includes(channel) ? ["meta"] : ["sms", "meta", "calls"];
      const sources = (["sms", "meta", "calls"] as const).filter(s => allowed.includes(s) && more[s]);
      if (!sources.length) return;
      const responses = await Promise.all(sources.map(s => fetch(`${API_BASE}${s === "calls" ? "/api/chats/calls?limit=50" : `/api/chats?source=${s}&limit=20`}&cursor=${encodeURIComponent(cursors[s])}`, { headers: authHeaders(token) })));
      if (responses.some(r => !r.ok)) throw new Error("Could not load more communications");
      const pages = await Promise.all(responses.map(r => r.json()));
      setContacts(cur => { const map = new Map(cur.map(i => [i.key, { ...i, sources: [...i.sources] }])); merge(map, pages.flatMap(p => p.items || [])); return [...map.values()].sort((a, b) => b.timestamp - a.timestamp); });
      setCursors(cur => { const n = { ...cur }; sources.forEach((s, i) => { n[s] = pages[i].next_cursor || ""; }); return n; });
      setMore(cur => { const n = { ...cur }; sources.forEach((s, i) => { n[s] = Boolean(pages[i].has_more); }); return n; });
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load more communications"); } finally { loadingMoreRef.current = false; setLoadingMore(false); }
  }, [cursors, more, channel, token]);

  const contact = contacts.find(c => c.key === selected);

  const loadHistory = useCallback(async (current: Contact) => {
    setHistoryLoading(true); setError("");
    try {
      const urls = new Set<string>();
      for (const s of current.sources) {
        const type = String(s.source_type || ""); const partition = String(s.message_partition_key || "");
        if (type === "sms") {
          urls.add(`/api/sms/${encodeURIComponent(partition)}?aircall_number_id=${encodeURIComponent(String(s.company_identifier || ""))}`);
          if (s.company_phone_identifier) urls.add(`/api/chats/calls/history?phone=${encodeURIComponent(partition)}&company_number=${encodeURIComponent(String(s.company_phone_identifier))}`);
        } else if (type === "messenger" || type === "instagram") {
          urls.add(`/api/meta/${type}/${encodeURIComponent(partition)}`);
        } else if (type === WEBSITE_BOT) {
          urls.add(`/api/chats/${WEBSITE_BOT}/${encodeURIComponent(partition)}`);
        } else if (type === "calls") {
          const client = String(s.client_identifier || "");
          urls.add(`/api/chats/calls/history?phone=${encodeURIComponent(client)}&company_number=${encodeURIComponent(String(s.company_identifier || ""))}`);
          const numberId = String(s.destination_aircall_number_id || "");
          if (numberId) urls.add(`/api/sms/${encodeURIComponent(client)}?aircall_number_id=${encodeURIComponent(numberId)}`);
        }
      }
      const responses = await Promise.all([...urls].map(u => fetch(`${API_BASE}${u}`, { headers: authHeaders(token) })));
      const failed = responses.filter(r => !r.ok).length;
      const bodies = await Promise.all(responses.map(r => (r.ok ? r.json() : Promise.resolve({}))));
      const result: TimelineItem[] = [];
      bodies.forEach(body => {
        for (const item of body.messages || []) {
          const platform = String(item.platform || (item.phone_number ? "sms" : "messenger"));
          const inbound = platform === "sms" ? ["received", "inbound"].includes(String(item.direction || "").toLowerCase()) : ["user", "client", "customer"].includes(String(item.role || "").toLowerCase());
          result.push({ id: `m:${item.message_id}`, kind: "message", channel: platform, direction: inbound ? "inbound" : "outbound", timestamp: stamp(item.timestamp), text: String(item.text || ""), attachments: item.attachments || [], senderLabel: automated(item) });
        }
        for (const item of body.calls || []) result.push({ id: `c:${item.message_id}`, kind: "call", channel: "call", direction: String(item.direction).toLowerCase() === "inbound" ? "inbound" : "outbound", timestamp: stamp(item.timestamp), text: "", answered: Boolean(item.answered), reason: String(item.reason || "") });
      });
      setTimeline([...new Map(result.map(i => [i.id, i])).values()].sort((a, b) => a.timestamp - b.timestamp));
      if (failed) setError(`${failed} communication source${failed === 1 ? "" : "s"} could not be loaded. The timeline may be incomplete.`);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load communication history"); } finally { setHistoryLoading(false); }
  }, [token]);

  useEffect(() => { if (contact) void loadHistory(contact); else setTimeline([]); }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (historyLoading) return;
    const f = requestAnimationFrame(() => { const el = timelineRef.current; if (el) el.scrollTop = el.scrollHeight; });
    return () => cancelAnimationFrame(f);
  }, [selected, historyLoading, timeline.length]);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase(); const qd = digits(q);
    return contacts.filter(item => {
      const hay = [item.key, item.client, item.company, item.rep, ...item.sources.flatMap(s => [s.client_identifier, s.message_partition_key, s.company_identifier, s.company_phone_identifier, s.destination_phone, s.destination_name])].map(v => String(v || "").toLowerCase());
      if (q && !hay.some(v => v.includes(q) || (qd.length >= 3 && digits(v).includes(qd)))) return false;
      if (channel && !item.sources.some(s => String(s.source_type || "") === channel)) return false;
      if (repFilter && !reps(item).includes(repFilter)) return false;
      if (companyFilter && !companies(item).includes(companyFilter)) return false;
      if (onlyWaiting && !inboundLatest(item)) return false;
      return true;
    });
  }, [contacts, search, channel, repFilter, companyFilter, onlyWaiting]);

  const filtersActive = Boolean(search.trim() || channel || repFilter || companyFilter || onlyWaiting);
  useEffect(() => { if (filtersActive && !loading && !loadingMore && shown.length < 20 && Object.values(more).some(Boolean)) void loadMore(); }, [filtersActive, loading, loadingMore, shown.length, more, loadMore]);

  const repOptions = useMemo(() => [...new Set(["Unassigned", ...directory.reps, ...contacts.flatMap(reps)])].sort(), [contacts, directory.reps]);
  const companyOptions = useMemo(() => [...new Set([...directory.companies, ...contacts.flatMap(companies)])].sort(), [contacts, directory.companies]);
  const waitingCount = useMemo(() => contacts.filter(inboundLatest).length, [contacts]);

  function callbackAfter(i: number) { const it = timeline[i]; if (it.kind !== "call" || it.direction !== "inbound" || it.answered) return undefined; return timeline.slice(i + 1).find(n => n.kind === "call" && n.direction === "outbound"); }

  return (
    <div className="aur-inbox">
      <section className="aur-inbox-list" aria-label="Conversations">
        <div className="aur-inbox-list-head">
          <div className="aur-inbox-title"><h1>Inbox</h1>{waitingCount > 0 && <span className="aur-pill tone-danger">{waitingCount} waiting</span>}</div>
          <label className="aur-searchbox">
            <Icon name="search" size={16} />
            <input type="search" aria-label="Search conversations" placeholder="Search people or numbers" value={search} onChange={e => setSearch(e.target.value)} />
          </label>
          <div className="aur-chips" role="group" aria-label="Channel">
            {[["", "All"], ["sms", "SMS"], ["calls", "Calls"], ["messenger", "Messenger"], ["instagram", "Instagram"], [WEBSITE_BOT, "Website bot"]].map(([v, l]) => (
              <button key={v} type="button" className={`aur-chip${channel === v ? " is-active" : ""}`} aria-pressed={channel === v} onClick={() => setChannel(v)}>{l}</button>
            ))}
            <button type="button" className={`aur-chip${onlyWaiting ? " is-active" : ""}`} aria-pressed={onlyWaiting} onClick={() => setOnlyWaiting(w => !w)}>Waiting</button>
          </div>
          <div className="aur-inbox-selects">
            <select className="aur-select" aria-label="Filter by rep" value={repFilter} onChange={e => setRepFilter(e.target.value)}><option value="">All reps</option>{repOptions.map(v => <option key={v} value={v}>{v}</option>)}</select>
            <select className="aur-select" aria-label="Filter by company" value={companyFilter} onChange={e => setCompanyFilter(e.target.value)}><option value="">All companies</option>{companyOptions.map(v => <option key={v} value={v}>{v}</option>)}</select>
          </div>
        </div>
        <ul className="aur-inbox-items" onScroll={e => { const el = e.currentTarget; if (el.scrollHeight - el.scrollTop - el.clientHeight < 240) void loadMore(); }}>
          {loading ? <li className="aur-empty">{"Loading conversations…"}</li> : !shown.length ? <li className="aur-empty">No conversations match.</li> : shown.map(item => {
            const [bg, fg] = tint(item.client);
            const ch = CHANNEL[item.channel] || CHANNEL.sms;
            const waiting = inboundLatest(item);
            return (
              <li key={item.key}>
                <button type="button" className={`aur-convo${item.key === selected ? " is-selected" : ""}`} onClick={() => setSelected(item.key)}
                  onContextMenu={!item.lead_id ? e => { const t = associationTarget(item); if (t) { e.preventDefault(); setConnectTarget(t); } } : undefined}
                  title={!item.lead_id && associationTarget(item) ? "Right-click to connect this conversation to a lead" : undefined}>
                  <span className="aur-convo-avatar">
                    <span className="aur-avatar is-square" style={{ background: bg, color: fg }}>{/^[\d(+]/.test(item.client) ? "#" : initials(item.client)}</span>
                    <span className="aur-convo-channel" style={{ background: ch.color }}><Icon name={ch.icon} size={10} strokeWidth={2.6} /></span>
                  </span>
                  <span className="aur-convo-body">
                    <span className="aur-convo-top"><strong className={waiting ? "is-unread" : undefined}>{item.client}</strong><small>{timeLabel(item.timestamp)}</small></span>
                    <span className="aur-convo-preview">{item.last_preview}</span>
                    <span className="aur-convo-meta">{waiting && <span className="aur-pill tone-danger">Waiting</span>}<small>{[item.company, item.rep].filter(v => v && v !== "Unassigned").join(" · ") || "Unassigned"}</small></span>
                  </span>
                </button>
              </li>
            );
          })}
          {loadingMore && <li className="aur-empty is-small">{"Loading more…"}</li>}
        </ul>
      </section>

      <section className="aur-thread" aria-label={contact ? `Conversation with ${contact.client}` : "Conversation"}>
        <header className="aur-thread-head">
          {contact ? <>
            <span className="aur-avatar is-square" style={{ background: tint(contact.client)[0], color: tint(contact.client)[1] }}>{initials(contact.client)}</span>
            <div className="aur-thread-title">
              {contact.lead_id ? <Link to={`/leads/${contact.lead_id}`}>{contact.client}</Link> : <strong>{contact.client}</strong>}
              <small className="aur-muted">{inboundLatest(contact) ? "Received by" : "Sent from"} {destination(contact)}</small>
            </div>
            {!contact.lead_id && associationTarget(contact) && <button type="button" className="aur-btn" onClick={() => setConnectTarget(associationTarget(contact))}>Connect to lead</button>}
            {contact.lead_id && <Link className="aur-btn" to={`/leads/${contact.lead_id}`}><Icon name="external" size={15} />Open lead</Link>}
          </> : <strong>Select a conversation</strong>}
        </header>
        {error && <div className="aur-alert" role="alert">{error}</div>}
        <div className="aur-thread-body" ref={timelineRef}>
          {historyLoading ? <p className="aur-empty">{"Loading conversation…"}</p> : timeline.map((item, i) => {
            const newDay = i === 0 || new Date(timeline[i - 1].timestamp * 1000).toDateString() !== new Date(item.timestamp * 1000).toDateString();
            const callback = callbackAfter(i);
            return (
              <div key={item.id} className="aur-thread-row">
                {newDay && <div className="aur-day">{dayLabel(item.timestamp)}</div>}
                {item.kind === "message" ? (
                  <div className={`aur-bubble-wrap is-${item.direction}`}>
                    <div className={`aur-bubble is-${item.direction}`}>
                      {item.senderLabel && <strong className="aur-bubble-sender">{item.senderLabel}</strong>}
                      {item.text && <div className="aur-bubble-text">{item.text}</div>}
                      <MessageAttachments attachments={item.attachments} />
                    </div>
                    <small>{(CHANNEL[item.channel]?.label || item.channel.toUpperCase())} {"·"} {fullTime(item.timestamp)}</small>
                  </div>
                ) : (
                  <div className={`aur-call is-${item.direction}${!item.answered && item.direction === "inbound" ? " is-missed" : ""}`}>
                    <span className="aur-call-icon"><Icon name="phone" size={14} /></span>
                    <div>
                      <strong>{item.direction === "inbound" ? "Inbound call" : "Outbound call"} {"·"} {item.answered ? "answered" : "not answered"}</strong>
                      <small className="aur-muted">{fullTime(item.timestamp)}{item.reason ? ` · ${item.reason}` : ""}</small>
                      {callback ? <small className="aur-good">Called back after {elapsed(callback.timestamp - item.timestamp)}</small> : item.direction === "inbound" && !item.answered ? <small className="aur-bad">No callback yet</small> : null}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {!historyLoading && contact && !timeline.length && <p className="aur-empty">No communication history found.</p>}
        </div>
        <div className="aur-thread-foot aur-muted">{contact?.channel === WEBSITE_BOT ? "Website chat with the Gorilla Haulers bot. Read-only." : "Reply from the lead page or SmartMoving. Sending from the Inbox is a planned next step."}</div>
      </section>

      <LeadContext contact={contact} />

      {connectTarget && <ConnectCommunicationLeadModal target={connectTarget} token={token} onClose={() => setConnectTarget(null)}
        onConnected={lead => { setContacts(cur => cur.map(i => (i.key === selected ? { ...i, lead_id: lead.id, client: lead.name, company: lead.company, rep: lead.rep || "" } : i))); setConnectTarget(null); }} />}
    </div>
  );
}

function LeadContext({ contact }: { contact?: Contact }) {
  const { token } = useAuth();
  const [lead, setLead] = useState<Lead | null>(null);
  const [summary, setSummary] = useState("");
  const leadId = contact?.lead_id || "";
  useEffect(() => {
    setLead(null); setSummary("");
    if (!leadId) return;
    const c = new AbortController();
    fetch(`${API_BASE}/api/leads/${encodeURIComponent(leadId)}`, { headers: authHeaders(token), signal: c.signal }).then(r => (r.ok ? r.json() : null)).then(d => d && !Array.isArray(d) && setLead(d)).catch(() => {});
    fetch(`${API_BASE}/api/leads/${encodeURIComponent(leadId)}/ai-summary`, { headers: authHeaders(token), signal: c.signal }).then(r => (r.ok ? r.json() : null)).then(d => d?.summary && setSummary(String(d.summary))).catch(() => {});
    return () => c.abort();
  }, [leadId, token]);

  if (!contact) return <aside className="aur-context" aria-label="Lead details" />;
  const total = Number((lead?.estimatedTotal as { finalTotal?: number } | null)?.finalTotal || 0);
  return (
    <aside className="aur-context" aria-label="Lead details">
      {!leadId ? (
        <div className="aur-context-empty"><strong>Not linked to a lead</strong><span className="aur-muted">{contact.channel === WEBSITE_BOT ? "Website visitor, no lead yet. The conversation links to the lead by itself once the visitor sends the request." : "Use Connect to lead to attach this conversation to a customer."}</span></div>
      ) : (
        <>
          <div className="aur-context-head"><span className="aur-eyebrow">Lead</span>{lead && <span className={`aur-stage stage-${String(lead.status || "new").toLowerCase()}`}>{String(lead.status || "new")}</span>}</div>
          {summary && <div className="aur-ai-card">
            <span className="aur-ai-label"><Icon name="spark" size={14} />Smart summary</span>
            <span>{summary}</span>
          </div>}
          {lead && <dl className="aur-facts">
            <div><dt>Pickup</dt><dd>{String(lead.pickup_zip || "—")}</dd></div>
            <div><dt>Delivery</dt><dd>{String(lead.delivery_zip || "—")}</dd></div>
            <div><dt>Move date</dt><dd>{String(lead["when_is_the_move?"] || "—")}</dd></div>
            <div><dt>Size</dt><dd>{String(lead.move_size || "—")}</dd></div>
            <div><dt>Quote</dt><dd className="aur-strong">{total ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(total) : "—"}</dd></div>
            <div><dt>Owner</dt><dd>{String(lead.assigned_to_name || "Unassigned")}</dd></div>
          </dl>}
          <Link className="aur-btn is-primary" to={`/leads/${leadId}`}>Open full lead</Link>
        </>
      )}
    </aside>
  );
}
