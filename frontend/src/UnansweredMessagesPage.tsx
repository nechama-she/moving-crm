import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import { RealtimeEvent, useRealtimeUpdates } from "./useRealtimeUpdates";
import MessageAttachments, { attachmentSummary, MessageAttachment } from "./MessageAttachments";

type MessageTab = "unanswered" | "ended";
type QueueTab = "messages" | "calls" | "leads" | "followups";
type LeadTab = "new" | "overdue";
type FollowupTab = "all" | "overdue";
type MessageRow = { channel: string; message_id: string; lead_id: string; client_identifier: string; client: string; client_number: string; message: string; attachments?: MessageAttachment[]; rep: string; company: string; destination_number: string; destination_name: string; occurred_at: string };
type MissedCallRow = { call_id: string; lead_id: string; client_identifier: string; company_identifier: string; client: string; rep: string; company: string; ring_number: string; ring_target: string; missed_count: number; first_missed_at: string; latest_missed_at: string };
type FirstContactLead = { lead_id: string; client: string; client_phone: string; rep: string; company: string; status: string; created_at: string; age_minutes: number };
type FollowupAttempt = { number?: number; kind: "call" | "message"; label: string; period: string; scheduled_start: string; scheduled_end: string; completed_at: string; status: "completed" | "on_time" | "delayed" | "overdue" | "open" | "upcoming" };
type FollowupLead = { lead_id: string; client: string; client_phone: string; rep: string; company: string; created_at: string; smartmoving_created_time: string; created_time_source: "smartmoving" | "crm"; completed_count: number; completed_message_count: number; overdue_count: number; overdue_message_count: number; attempts: FollowupAttempt[]; timeline: FollowupAttempt[] };
type NumberMenu = { number: string; x: number; y: number } | null;

const displayPhone = (value: string) => {
  const digits = String(value || "").replace(/\D/g, "");
  const local = digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
  return local.length === 10 ? `(${local.slice(0, 3)}) ${local.slice(3, 6)}-${local.slice(6)}` : value;
};

function IgnoreNumberTarget({ number, name, showUnknown = false, openMenu }: { number: string; name?: string; showUnknown?: boolean; openMenu: (number: string, x: number, y: number) => void }) {
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelHold = () => { if (holdTimer.current) clearTimeout(holdTimer.current); holdTimer.current = null; };
  return <div
    title="Right-click or press and hold for options"
    onContextMenu={(event) => { event.preventDefault(); cancelHold(); openMenu(number, event.clientX, event.clientY); }}
    onPointerDown={(event) => {
      if (event.pointerType !== "touch") return;
      const { clientX, clientY } = event;
      cancelHold();
      holdTimer.current = setTimeout(() => openMenu(number, clientX, clientY), 550);
    }}
    onPointerUp={cancelHold}
    onPointerCancel={cancelHold}
    onPointerMove={cancelHold}
    style={{ userSelect: "text", WebkitUserSelect: "text", touchAction: "manipulation", cursor: "pointer" }}
  >
    <strong>{displayPhone(number)}</strong>
    {name || showUnknown ? <div style={{ color: "#64748b", fontSize: 12, marginTop: 3 }}>{name || "Unknown number"}</div> : null}
  </div>;
}

export default function UnansweredMessagesPage() {
  const { token } = useAuth();
  const [queueTab, setQueueTab] = useState<QueueTab>("messages");
  const [tab, setTab] = useState<MessageTab>("unanswered");
  const [items, setItems] = useState<MessageRow[]>([]);
  const [messageCursor, setMessageCursor] = useState("");
  const [messageHasMore, setMessageHasMore] = useState(false);
  const [loadingMoreMessages, setLoadingMoreMessages] = useState(false);
  const [counts, setCounts] = useState({ unanswered: 0, ended: 0 });
  const [missedCalls, setMissedCalls] = useState<MissedCallRow[]>([]);
  const [missedCallCount, setMissedCallCount] = useState(0);
  const [leadTab, setLeadTab] = useState<LeadTab>("overdue");
  const [firstContactLeads, setFirstContactLeads] = useState<FirstContactLead[]>([]);
  const [firstContactCounts, setFirstContactCounts] = useState({ new: 0, overdue: 0 });
  const [firstContactHasMore, setFirstContactHasMore] = useState(false);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [followupTab, setFollowupTab] = useState<FollowupTab>("overdue");
  const [followupLeads, setFollowupLeads] = useState<FollowupLead[]>([]);
  const [followupCounts, setFollowupCounts] = useState({ all: 0, overdue: 0 });
  const [followupGlobalCounts, setFollowupGlobalCounts] = useState({ all: 0, overdue: 0 });
  const [followupFilterOptions, setFollowupFilterOptions] = useState({ reps: [] as string[], companies: [] as string[] });
  const [followupHasMore, setFollowupHasMore] = useState(false);
  const [loadingFollowups, setLoadingFollowups] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [numberMenu, setNumberMenu] = useState<NumberMenu>(null);
  const [repFilter, setRepFilter] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [platformFilter, setPlatformFilter] = useState("");
  const processedEvents = useRef(new Set<string>());
  const loadingRef = useRef(true);
  const pendingEvents = useRef<RealtimeEvent[]>([]);
  const messageLoadSentinel = useRef<HTMLDivElement | null>(null);
  const leadLoadSentinel = useRef<HTMLDivElement | null>(null);
  const followupLoadSentinel = useRef<HTMLDivElement | null>(null);
  const queueRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshFirstContact = useRef(false);
  const refreshFollowups = useRef(false);

  const load = useCallback(async () => {
    loadingRef.current = true;
    setLoading(true);
    setError("");
    try {
      const [messageResponse, callsResponse] = await Promise.all([
        fetch(`${API_BASE}/api/unanswered-messages?ended=${tab === "ended"}&limit=20`, { headers: authHeaders(token) }),
        fetch(`${API_BASE}/api/unanswered-messages/missed-calls?limit=100`, { headers: authHeaders(token) }),
      ]);
      if (!messageResponse.ok) throw new Error(`Messages HTTP ${messageResponse.status}`);
      if (!callsResponse.ok) throw new Error(`Missed calls HTTP ${callsResponse.status}`);
      const [messageData, callsData] = await Promise.all([messageResponse.json(), callsResponse.json()]);
      setItems(messageData.items || []);
      setMessageCursor(String(messageData.next_cursor || ""));
      setMessageHasMore(Boolean(messageData.has_more));
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

  const loadFirstContactLeads = useCallback(async (offset = 0, refresh = false) => {
    if (offset) setLoadingLeads(true);
    else setLoadingLeads(true);
    try {
      const response = await fetch(`${API_BASE}/api/unanswered-messages/first-contact-leads?category=${leadTab}&limit=50&offset=${offset}&refresh=${refresh}`, { headers: authHeaders(token) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Leads HTTP ${response.status}`);
      setFirstContactLeads((current) => offset ? [...current, ...(data.items || [])] : (data.items || []));
      setFirstContactCounts(data.counts || { new: 0, overdue: 0 });
      setFirstContactHasMore(Boolean(data.has_more));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load leads awaiting first contact");
    } finally {
      setLoadingLeads(false);
    }
  }, [leadTab, token]);

  useEffect(() => { void loadFirstContactLeads(0); }, [loadFirstContactLeads]);

  const loadFollowups = useCallback(async (offset = 0, refresh = false) => {
    setLoadingFollowups(true);
    try {
      const params = new URLSearchParams({ category: followupTab, limit: "50", offset: String(offset) });
      if (refresh) params.set("refresh", "true");
      if (repFilter) params.set("rep", repFilter);
      if (companyFilter) params.set("company", companyFilter);
      const response = await fetch(`${API_BASE}/api/unanswered-messages/followup-calls?${params.toString()}`, { headers: authHeaders(token) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Follow-ups HTTP ${response.status}`);
      setFollowupLeads((current) => offset ? [...current, ...(data.items || [])] : (data.items || []));
      setFollowupCounts(data.counts || { all: 0, overdue: 0 });
      setFollowupGlobalCounts(data.global_counts || data.counts || { all: 0, overdue: 0 });
      setFollowupFilterOptions(data.filter_options || { reps: [], companies: [] });
      setFollowupHasMore(Boolean(data.has_more));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load follow-up calls");
    } finally {
      setLoadingFollowups(false);
    }
  }, [followupTab, repFilter, companyFilter, token]);

  const scheduleQueueRefresh = useCallback((firstContact: boolean, followups: boolean) => {
    refreshFirstContact.current ||= firstContact;
    refreshFollowups.current ||= followups;
    if (queueRefreshTimer.current) clearTimeout(queueRefreshTimer.current);
    queueRefreshTimer.current = setTimeout(() => {
      queueRefreshTimer.current = null;
      const reloadFirstContact = refreshFirstContact.current;
      const reloadFollowups = refreshFollowups.current;
      refreshFirstContact.current = false;
      refreshFollowups.current = false;
      if (reloadFirstContact) void loadFirstContactLeads(0, true);
      if (reloadFollowups) void loadFollowups(0, true);
    }, 250);
  }, [loadFirstContactLeads, loadFollowups]);

  useEffect(() => () => {
    if (queueRefreshTimer.current) clearTimeout(queueRefreshTimer.current);
  }, []);

  useEffect(() => { void loadFollowups(0); }, [loadFollowups]);

  useEffect(() => {
    const target = followupLoadSentinel.current;
    if (!target || queueTab !== "followups" || !followupHasMore || loadingFollowups) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadFollowups(followupLeads.length);
    }, { rootMargin: "240px 0px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, [queueTab, followupHasMore, loadingFollowups, followupLeads.length, loadFollowups]);

  useEffect(() => {
    const target = leadLoadSentinel.current;
    if (!target || queueTab !== "leads" || !firstContactHasMore || loadingLeads) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadFirstContactLeads(firstContactLeads.length);
    }, { rootMargin: "240px 0px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, [queueTab, firstContactHasMore, loadingLeads, firstContactLeads.length, loadFirstContactLeads]);

  const loadMoreMessages = useCallback(async () => {
    if (loading || loadingMoreMessages || !messageHasMore || !messageCursor) return;
    setLoadingMoreMessages(true);
    try {
      const response = await fetch(`${API_BASE}/api/unanswered-messages?ended=${tab === "ended"}&limit=20&cursor=${encodeURIComponent(messageCursor)}`, { headers: authHeaders(token) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Messages HTTP ${response.status}`);
      const incoming = (data.items || []) as MessageRow[];
      setItems((current) => {
        const existing = new Set(current.map((item) => `${item.channel}:${item.message_id}`));
        return [...current, ...incoming.filter((item) => !existing.has(`${item.channel}:${item.message_id}`))];
      });
      setMessageCursor(String(data.next_cursor || ""));
      setMessageHasMore(Boolean(data.has_more));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load more messages");
    } finally {
      setLoadingMoreMessages(false);
    }
  }, [loading, loadingMoreMessages, messageHasMore, messageCursor, tab, token]);

  useEffect(() => {
    const target = messageLoadSentinel.current;
    if (!target || queueTab !== "messages") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadMoreMessages();
    }, { rootMargin: "240px 0px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, [queueTab, loadMoreMessages]);

  useEffect(() => {
    if (!numberMenu) return;
    const close = () => setNumberMenu(null);
    window.addEventListener("pointerdown", close);
    window.addEventListener("scroll", close, true);
    return () => { window.removeEventListener("pointerdown", close); window.removeEventListener("scroll", close, true); };
  }, [numberMenu]);

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
      if (belongsHere && row) next = [row, ...next].sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at));
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
        if (item.type === "call_activity_changed" || item.type === "missed_call_state_changed") scheduleQueueRefresh(true, true);
        if (item.type === "message_activity_changed" || item.type === "message_state_changed") scheduleQueueRefresh(false, true);
        if (item.type === "lead_activity_changed") scheduleQueueRefresh(true, true);
      });
      return;
    }
    applyRealtimeEvent(event);
    applyMissedCallEvent(event);
    if (event.type === "call_activity_changed" || event.type === "missed_call_state_changed") scheduleQueueRefresh(true, true);
    if (event.type === "message_activity_changed" || event.type === "message_state_changed") scheduleQueueRefresh(false, true);
    if (event.type === "lead_activity_changed") scheduleQueueRefresh(true, true);
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

  const ignoreMissedCall = async (row: MissedCallRow) => {
    setError("");
    const response = await fetch(`${API_BASE}/api/unanswered-messages/missed-calls`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ client_identifier: row.client_identifier, company_identifier: row.company_identifier }),
    });
    if (!response.ok) { setError(`HTTP ${response.status}`); return; }
    const result = await response.json();
    if (result.event) applyMissedCallEvent(result.event as RealtimeEvent);
  };

  const ignoreNumber = async (number: string) => {
    setError("");
    setNumberMenu(null);
    const response = await fetch(`${API_BASE}/api/unanswered-messages/ignored-call-numbers`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ number }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) { setError(result.detail || `HTTP ${response.status}`); return; }
    ((result.events || []) as RealtimeEvent[]).forEach((event) => {
      applyMissedCallEvent(event);
      applyRealtimeEvent(event);
    });
  };

  const headers = ["Client", "Platform", "Message", "Rep", "Company", "Sent To", "Message Time", "Action"];
  const cell = { padding: "13px 16px", borderBottom: "1px solid #e2e8f0", color: "#334155" } as const;
  const filterOptions = useMemo(() => {
    const rows = queueTab === "messages" ? items : queueTab === "calls" ? missedCalls : queueTab === "leads" ? firstContactLeads : followupLeads;
    return {
      reps: queueTab === "followups" ? followupFilterOptions.reps : [...new Set(rows.map((row) => row.rep).filter(Boolean))].sort(),
      companies: queueTab === "followups" ? followupFilterOptions.companies : [...new Set(rows.map((row) => row.company).filter(Boolean))].sort(),
      platforms: queueTab === "messages" ? [...new Set(items.map((row) => row.channel).filter(Boolean))].sort() : queueTab === "calls" ? ["calls"] : [],
    };
  }, [queueTab, items, missedCalls, firstContactLeads, followupLeads, followupFilterOptions]);
  const filteredItems = useMemo(() => items.filter((row) =>
    (!repFilter || row.rep === repFilter) &&
    (!companyFilter || row.company === companyFilter) &&
    (!platformFilter || row.channel === platformFilter)
  ), [items, repFilter, companyFilter, platformFilter]);
  const filteredMissedCalls = useMemo(() => missedCalls.filter((row) =>
    (!repFilter || row.rep === repFilter) &&
    (!companyFilter || row.company === companyFilter) &&
    (!platformFilter || platformFilter === "calls")
  ), [missedCalls, repFilter, companyFilter, platformFilter]);
  const filteredFirstContactLeads = useMemo(() => firstContactLeads.filter((row) =>
    (!repFilter || row.rep === repFilter) &&
    (!companyFilter || row.company === companyFilter)
  ), [firstContactLeads, repFilter, companyFilter]);
  const filteredFollowupLeads = useMemo(() => followupLeads.filter((row) =>
    (!repFilter || row.rep === repFilter) &&
    (!companyFilter || row.company === companyFilter)
  ), [followupLeads, repFilter, companyFilter]);

  useEffect(() => {
    setRepFilter("");
    setCompanyFilter("");
    setPlatformFilter("");
  }, [queueTab]);

  return (
    <main style={{ padding: 24, width: "100%", maxWidth: 1280, margin: "0 auto", boxSizing: "border-box" }}>
      <h1 style={{ margin: 0, color: "#032d60", fontSize: 24 }}>Sales Work Queue</h1>
      <p style={{ margin: "6px 0 20px", color: "#64748b" }}>Sales items that need attention.</p>
      {error ? <p style={{ color: "#b91c1c" }}>{error}</p> : null}
      {numberMenu ? <div onPointerDown={(event) => event.stopPropagation()} style={{ position: "fixed", zIndex: 1000, left: Math.min(numberMenu.x, window.innerWidth - 190), top: Math.min(numberMenu.y, window.innerHeight - 60), minWidth: 180, padding: 5, border: "1px solid #cbd5e1", borderRadius: 6, background: "#fff", boxShadow: "0 6px 18px rgba(15,23,42,.2)" }}>
        <button type="button" onClick={() => void ignoreNumber(numberMenu.number)} style={{ width: "100%", border: 0, borderRadius: 4, background: "transparent", color: "#b91c1c", padding: "9px 11px", textAlign: "left", fontWeight: 600, cursor: "pointer" }}>Ignore this number</button>
      </div> : null}

      <nav aria-label="Sales work queue categories" style={{ display: "flex", flexWrap: "nowrap", gap: 12, overflowX: "auto", paddingBottom: 12, marginBottom: 6 }}>
        <button type="button" onClick={() => setQueueTab("messages")} style={{ ...queueCard, ...(queueTab === "messages" ? activeQueueCard : {}) }}>
          <span style={queueCardLabel}>Unanswered Messages</span>
          <strong style={queueCardCount}>{counts.unanswered}</strong>
          <span style={queueCardDescription}>Client messages waiting for a response</span>
        </button>
        <button type="button" onClick={() => setQueueTab("calls")} style={{ ...queueCard, ...(queueTab === "calls" ? activeQueueCard : {}) }}>
          <span style={queueCardLabel}>Missed Calls</span>
          <strong style={queueCardCount}>{missedCallCount}</strong>
          <span style={queueCardDescription}>Missed calls without a later contact attempt</span>
        </button>
        <button type="button" onClick={() => setQueueTab("leads")} style={{ ...queueCard, ...(queueTab === "leads" ? activeQueueCard : {}) }}>
          <span style={queueCardLabel}>Leads Awaiting First Contact</span>
          <strong style={queueCardCount}>{firstContactCounts.new + firstContactCounts.overdue}</strong>
          <span style={queueCardDescription}>New leads with no call attempt</span>
        </button>
        <button type="button" onClick={() => setQueueTab("followups")} style={{ ...queueCard, ...(queueTab === "followups" ? activeQueueCard : {}) }}>
          <span style={queueCardLabel}>Priority 0 Follow-ups</span>
          <strong style={queueCardCount}>{followupGlobalCounts.overdue}</strong>
          <span style={queueCardDescription}>Six call periods and three required messages</span>
        </button>
      </nav>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
        <select aria-label="Filter work queue by rep" value={repFilter} onChange={(event) => setRepFilter(event.target.value)} style={filterSelect}><option value="">All reps</option>{filterOptions.reps.map((value) => <option key={value} value={value}>{value}</option>)}</select>
        <select aria-label="Filter work queue by company" value={companyFilter} onChange={(event) => setCompanyFilter(event.target.value)} style={filterSelect}><option value="">All companies</option>{filterOptions.companies.map((value) => <option key={value} value={value}>{value}</option>)}</select>
        {queueTab !== "leads" ? <select aria-label="Filter work queue by platform" value={platformFilter} onChange={(event) => setPlatformFilter(event.target.value)} style={filterSelect}><option value="">All platforms</option>{filterOptions.platforms.map((value) => <option key={value} value={value}>{value === "calls" ? "Calls" : value === "sms" ? "SMS" : value.charAt(0).toUpperCase() + value.slice(1)}</option>)}</select> : null}
      </div>

      {queueTab === "messages" ? <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
        <div style={{ padding: "16px 18px 0" }}>
          <h2 style={{ margin: 0, color: "#032d60", fontSize: 18 }}>Unanswered Messages ({counts.unanswered})</h2>
          <div style={{ display: "flex", gap: 8, borderBottom: "1px solid #d8dde6", marginTop: 8 }}>
            {([ ["unanswered", "Unanswered Messages", counts.unanswered], ["ended", "Ended Chats", counts.ended] ] as const).map(([key, label, count]) => (
              <button key={key} type="button" onClick={() => setTab(key)} style={{ border: 0, borderBottom: tab === key ? "3px solid #0b5cab" : "3px solid transparent", background: "transparent", color: tab === key ? "#032d60" : "#475569", padding: "10px 14px", fontWeight: tab === key ? 700 : 500, cursor: "pointer" }}>{label} ({count})</button>
            ))}
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", minWidth: 1050, borderCollapse: "collapse", tableLayout: "fixed" }}>
          <thead><tr style={{ background: "#f8fafc", borderBottom: "1px solid #d8dde6" }}>{headers.map((header) => <th key={header} style={{ padding: "13px 16px", color: "#475569", fontSize: 12, textAlign: "left", textTransform: "uppercase" }}>{header}</th>)}</tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={8} style={{ padding: 32, textAlign: "center" }}>Loading messages…</td></tr> : null}
            {!loading && filteredItems.length === 0 ? <tr><td colSpan={8} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>{items.length ? "No messages match these filters." : tab === "unanswered" ? "No unanswered messages." : "No ended chats."}</td></tr> : null}
            {!loading && filteredItems.map((row) => <tr key={`${row.channel}:${row.message_id}`}>
              <td style={cell}>
                {row.lead_id ? <Link to={`/leads/${row.lead_id}`} target="_blank" rel="noopener noreferrer" state={{ backTo: "/sales-work-queue", backLabel: "← Back to Sales Work Queue" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</Link> : row.channel === "messenger" || row.channel === "instagram" ? <a href={`https://www.facebook.com/latest/${encodeURIComponent(row.client)}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</a> : null}
                {row.channel === "sms" && row.client_number ? <div style={{ marginTop: row.lead_id ? 4 : 0 }}><IgnoreNumberTarget number={row.client_number} openMenu={(number, x, y) => setNumberMenu({ number, x, y })} /></div> : null}
              </td>
              <td style={cell}>{row.channel === "sms" ? "SMS" : <a href={`https://www.facebook.com/latest/${encodeURIComponent(row.client_identifier)}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.channel === "instagram" ? "Instagram" : "Messenger"}</a>}</td>
              <td style={cell} title={row.message}><div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.message || attachmentSummary(row.attachments) || "No preview"}</div><MessageAttachments attachments={row.attachments} compact /></td>
              <td style={cell}>{row.rep}</td><td style={cell}>{row.company || "—"}</td>
              <td style={cell}>{row.channel === "sms" ? <IgnoreNumberTarget number={row.destination_number} name={row.destination_name} showUnknown openMenu={(number, x, y) => setNumberMenu({ number, x, y })} /> : "—"}</td>
              <td style={cell}>{new Date(row.occurred_at).toLocaleString()}</td>
              <td style={cell}><label><input type="checkbox" checked={tab === "ended"} onChange={() => void setEnded(row, tab === "unanswered")} /> {tab === "unanswered" ? "Ended" : "Reopen"}</label></td>
            </tr>)}
          </tbody>
        </table>
        </div>
        <div ref={messageLoadSentinel} style={{ minHeight: 1, padding: loadingMoreMessages ? 14 : 0, color: "#64748b", textAlign: "center" }}>{loadingMoreMessages ? "Loading more messages…" : null}</div>
      </section> : null}

      {queueTab === "calls" ? <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
        <div style={{ padding: "16px 18px" }}>
          <h2 style={{ margin: 0, color: "#032d60", fontSize: 18 }}>Missed Calls ({missedCallCount})</h2>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", minWidth: 920, borderCollapse: "collapse", tableLayout: "fixed" }}>
            <thead><tr style={{ background: "#f8fafc", borderTop: "1px solid #d8dde6", borderBottom: "1px solid #d8dde6" }}>
              {['Client', 'Rep', 'Company', 'Rang On', 'Missed Calls', 'First Missed', 'Latest Missed', 'Action'].map((header) => <th key={header} style={{ padding: "13px 16px", color: "#475569", fontSize: 12, textAlign: "left", textTransform: "uppercase" }}>{header}</th>)}
            </tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={8} style={{ padding: 32, textAlign: "center" }}>Loading missed calls…</td></tr> : null}
              {!loading && filteredMissedCalls.length === 0 ? <tr><td colSpan={8} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>{missedCalls.length ? "No missed calls match these filters." : "No missed calls."}</td></tr> : null}
              {!loading && filteredMissedCalls.map((row) => <tr key={`${row.client_identifier}:${row.company_identifier}`}>
                <td style={cell}>{row.lead_id ? <Link to={`/leads/${row.lead_id}`} target="_blank" rel="noopener noreferrer" state={{ backTo: "/sales-work-queue", backLabel: "← Back to Sales Work Queue" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</Link> : null}<div style={{ marginTop: row.lead_id ? 4 : 0 }}><IgnoreNumberTarget number={row.client_identifier} openMenu={(number, x, y) => setNumberMenu({ number, x, y })} /></div></td>
                <td style={cell}>{row.rep}</td>
                <td style={cell}>{row.company}</td>
                <td style={cell}><IgnoreNumberTarget number={row.ring_number || row.company_identifier} name={row.ring_target} showUnknown openMenu={(number, x, y) => setNumberMenu({ number, x, y })} /></td>
                <td style={cell}><strong>{row.missed_count}</strong></td>
                <td style={cell}>{new Date(row.first_missed_at).toLocaleString()}</td>
                <td style={cell}>{new Date(row.latest_missed_at).toLocaleString()}</td>
                <td style={cell}><button type="button" onClick={() => void ignoreMissedCall(row)} style={{ border: "1px solid #c9c7c5", borderRadius: 4, background: "#fff", color: "#475569", padding: "6px 11px", fontWeight: 600, cursor: "pointer" }}>Ignore</button></td>
              </tr>)}
            </tbody>
          </table>
        </div>
      </section> : null}

      {queueTab === "leads" ? <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
        <div style={{ padding: "16px 18px 0" }}>
          <h2 style={{ margin: 0, color: "#032d60", fontSize: 18 }}>Leads Awaiting First Contact ({firstContactCounts.new + firstContactCounts.overdue})</h2>
          <div style={{ display: "flex", gap: 8, borderBottom: "1px solid #d8dde6", marginTop: 8 }}>
            {([ ["new", "New Leads", firstContactCounts.new], ["overdue", "Overdue", firstContactCounts.overdue] ] as const).map(([key, label, count]) => (
              <button key={key} type="button" onClick={() => setLeadTab(key)} style={{ border: 0, borderBottom: leadTab === key ? "3px solid #0b5cab" : "3px solid transparent", background: "transparent", color: leadTab === key ? "#032d60" : "#475569", padding: "10px 14px", fontWeight: leadTab === key ? 700 : 500, cursor: "pointer" }}>{label} ({count})</button>
            ))}
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", minWidth: 760, borderCollapse: "collapse", tableLayout: "fixed" }}>
            <thead><tr style={{ background: "#f8fafc", borderBottom: "1px solid #d8dde6" }}>
              {['Client', 'Rep', 'Company', 'Status', 'Created', 'Waiting'].map((header) => <th key={header} style={{ padding: "13px 16px", color: "#475569", fontSize: 12, textAlign: "left", textTransform: "uppercase" }}>{header}</th>)}
            </tr></thead>
            <tbody>
              {loadingLeads && firstContactLeads.length === 0 ? <tr><td colSpan={6} style={{ padding: 32, textAlign: "center" }}>Loading leads…</td></tr> : null}
              {!loadingLeads && filteredFirstContactLeads.length === 0 ? <tr><td colSpan={6} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>{firstContactLeads.length ? "No leads match these filters." : "No leads awaiting first contact."}</td></tr> : null}
              {filteredFirstContactLeads.map((row) => <tr key={row.lead_id}>
                <td style={cell}><Link to={`/leads/${row.lead_id}`} target="_blank" rel="noopener noreferrer" state={{ backTo: "/sales-work-queue", backLabel: "← Back to Sales Work Queue" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</Link>{row.client_phone ? <div style={{ color: "#64748b", fontSize: 12, marginTop: 3 }}>{displayPhone(row.client_phone)}</div> : null}</td>
                <td style={cell}>{row.rep || "—"}</td>
                <td style={cell}>{row.company || "—"}</td>
                <td style={cell}>{row.status}</td>
                <td style={cell}>{new Date(row.created_at).toLocaleString()}</td>
                <td style={cell}><strong style={{ color: leadTab === "overdue" ? "#b91c1c" : "#0b5cab" }}>{row.age_minutes < 60 ? `${row.age_minutes}m` : row.age_minutes < 1440 ? `${Math.floor(row.age_minutes / 60)}h ${row.age_minutes % 60}m` : `${Math.floor(row.age_minutes / 1440)}d ${Math.floor((row.age_minutes % 1440) / 60)}h`}</strong></td>
              </tr>)}
            </tbody>
          </table>
        </div>
        <div ref={leadLoadSentinel} style={{ minHeight: 1, padding: loadingLeads && firstContactLeads.length ? 14 : 0, color: "#64748b", textAlign: "center" }}>{loadingLeads && firstContactLeads.length ? "Loading more leads…" : null}</div>
      </section> : null}

      {queueTab === "followups" ? <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
        <div style={{ padding: "16px 18px 0" }}>
          <h2 style={{ margin: 0, color: "#032d60", fontSize: 18 }}>Priority 0 Follow-ups</h2>
          <div style={{ display: "flex", gap: 8, borderBottom: "1px solid #d8dde6", marginTop: 8 }}>
            {([ ["all", "All Leads", followupCounts.all], ["overdue", "Overdue Items", followupCounts.overdue] ] as const).map(([key, label, count]) => (
              <button key={key} type="button" onClick={() => setFollowupTab(key)} style={{ border: 0, borderBottom: followupTab === key ? "3px solid #0b5cab" : "3px solid transparent", background: "transparent", color: followupTab === key ? "#032d60" : "#475569", padding: "10px 14px", fontWeight: followupTab === key ? 700 : 500, cursor: "pointer" }}>{label} ({count})</button>
            ))}
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", minWidth: 1050, borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "#f8fafc", borderBottom: "1px solid #d8dde6" }}>
              {['Client', 'Rep', 'Company', 'Created', 'Progress', 'Required Follow-ups'].map((header) => <th key={header} style={{ padding: "13px 16px", color: "#475569", fontSize: 12, textAlign: "left", textTransform: "uppercase" }}>{header}</th>)}
            </tr></thead>
            <tbody>
              {loadingFollowups && followupLeads.length === 0 ? <tr><td colSpan={6} style={{ padding: 32, textAlign: "center" }}>Loading follow-ups…</td></tr> : null}
              {!loadingFollowups && filteredFollowupLeads.length === 0 ? <tr><td colSpan={6} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>{followupLeads.length ? "No leads match these filters." : followupTab === "overdue" ? "No overdue follow-ups." : "No priority 0 leads to show."}</td></tr> : null}
              {filteredFollowupLeads.map((row) => <tr key={row.lead_id}>
                <td style={cell}><Link to={`/leads/${row.lead_id}`} target="_blank" rel="noopener noreferrer" state={{ backTo: "/sales-work-queue", backLabel: "← Back to Sales Work Queue" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</Link>{row.client_phone ? <div style={{ color: "#64748b", fontSize: 12, marginTop: 3 }}>{displayPhone(row.client_phone)}</div> : null}</td>
                <td style={cell}>{row.rep || "—"}</td>
                <td style={cell}>{row.company || "—"}</td>
                <td style={cell}>{new Date(row.created_at).toLocaleString()}{row.created_time_source === "crm" ? <div style={{ color: "#64748b", fontSize: 11, marginTop: 3 }}>CRM time (SmartMoving time unavailable)</div> : null}</td>
                <td style={cell}><strong>Calls {row.completed_count}/6</strong><div style={{ marginTop: 3 }}>Messages {row.completed_message_count || 0}/3</div>{row.overdue_count + (row.overdue_message_count || 0) ? <div style={{ color: "#b91c1c", fontSize: 12, marginTop: 3 }}>{row.overdue_count + (row.overdue_message_count || 0)} overdue</div> : null}</td>
                <td style={{ ...cell, minWidth: 520 }}><div style={{ display: "grid", gap: 6 }}>{row.timeline.map((attempt, activityIndex) => {
                  const color = attempt.status === "overdue" ? "#b91c1c" : attempt.status === "delayed" ? "#b45309" : attempt.status === "on_time" || attempt.status === "completed" ? "#2e844a" : "#64748b";
                  const label = attempt.status === "on_time" || attempt.status === "completed" ? "Completed" : attempt.status === "delayed" ? "Delayed" : attempt.status === "overdue" ? "Overdue" : attempt.status === "open" ? "Open" : "Upcoming";
                  return <div key={`${attempt.kind}-${attempt.number || attempt.label}-${activityIndex}`} style={{ display: "grid", gridTemplateColumns: "26px 150px 1fr", gap: 8, alignItems: "baseline", fontSize: 12 }}><strong>{attempt.kind === "call" ? `${attempt.number}.` : ""}</strong><span>{attempt.label}</span><span style={{ color }}><strong>{label}</strong>{attempt.completed_at ? ` · ${new Date(attempt.completed_at).toLocaleString()}` : ` · due by ${new Date(attempt.scheduled_end).toLocaleString()}`}</span></div>;
                })}</div></td>
              </tr>)}
            </tbody>
          </table>
        </div>
        <div ref={followupLoadSentinel} style={{ minHeight: 1, padding: loadingFollowups && followupLeads.length ? 14 : 0, color: "#64748b", textAlign: "center" }}>{loadingFollowups && followupLeads.length ? "Loading more leads…" : null}</div>
      </section> : null}
    </main>
  );
}

const queueCard: React.CSSProperties = {
  position: "relative",
  display: "grid",
  gridTemplateColumns: "1fr auto",
  gridTemplateRows: "auto auto",
  gap: "7px 14px",
  flex: "1 0 260px",
  maxWidth: 360,
  minHeight: 106,
  padding: "16px 18px",
  textAlign: "left",
  background: "#fff",
  border: "1px solid #d8dde6",
  borderRadius: 10,
  color: "#032d60",
  cursor: "pointer",
  boxSizing: "border-box",
};
const activeQueueCard: React.CSSProperties = { border: "2px solid #0b5cab", padding: "15px 17px", background: "#eef6ff" };
const queueCardLabel: React.CSSProperties = { fontSize: 16, fontWeight: 700, alignSelf: "center" };
const queueCardCount: React.CSSProperties = { fontSize: 28, lineHeight: 1, color: "#0b5cab" };
const queueCardDescription: React.CSSProperties = { gridColumn: "1 / -1", fontSize: 13, lineHeight: 1.35, color: "#64748b" };
const filterSelect: React.CSSProperties = { minWidth: 180, padding: "9px 32px 9px 10px", border: "1px solid #cbd5e1", borderRadius: 6, background: "#fff", color: "#334155" };
