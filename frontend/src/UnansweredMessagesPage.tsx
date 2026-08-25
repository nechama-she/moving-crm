import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import { RealtimeEvent, useRealtimeUpdates } from "./useRealtimeUpdates";

type MessageTab = "unanswered" | "ended";
type QueueTab = "messages" | "calls";
type MessageRow = { channel: string; message_id: string; lead_id: string; client: string; client_number: string; message: string; rep: string; company: string; destination_number: string; destination_name: string; occurred_at: string };
type MissedCallRow = { call_id: string; lead_id: string; client_identifier: string; company_identifier: string; client: string; rep: string; company: string; ring_number: string; ring_target: string; missed_count: number; first_missed_at: string; latest_missed_at: string };
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [numberMenu, setNumberMenu] = useState<NumberMenu>(null);
  const processedEvents = useRef(new Set<string>());
  const loadingRef = useRef(true);
  const pendingEvents = useRef<RealtimeEvent[]>([]);
  const messageLoadSentinel = useRef<HTMLDivElement | null>(null);

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
      </nav>

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
            {!loading && items.length === 0 ? <tr><td colSpan={8} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>{tab === "unanswered" ? "No unanswered messages." : "No ended chats."}</td></tr> : null}
            {!loading && items.map((row) => <tr key={`${row.channel}:${row.message_id}`}>
              <td style={cell}>
                {row.lead_id ? <Link to={`/leads/${row.lead_id}`} state={{ backTo: "/sales-work-queue", backLabel: "← Back to Sales Work Queue" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</Link> : row.channel === "messenger" || row.channel === "instagram" ? <a href={`https://www.facebook.com/latest/${encodeURIComponent(row.client)}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</a> : null}
                {row.channel === "sms" && row.client_number ? <div style={{ marginTop: row.lead_id ? 4 : 0 }}><IgnoreNumberTarget number={row.client_number} openMenu={(number, x, y) => setNumberMenu({ number, x, y })} /></div> : null}
              </td>
              <td style={cell}>{row.channel === "sms" ? "SMS" : row.channel === "instagram" ? "Instagram" : "Messenger"}</td>
              <td style={{ ...cell, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.message}>{row.message || "No preview"}</td>
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
              {!loading && missedCalls.length === 0 ? <tr><td colSpan={8} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>No missed calls.</td></tr> : null}
              {!loading && missedCalls.map((row) => <tr key={`${row.client_identifier}:${row.company_identifier}`}>
                <td style={cell}>{row.lead_id ? <Link to={`/leads/${row.lead_id}`} state={{ backTo: "/sales-work-queue", backLabel: "← Back to Sales Work Queue" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{row.client}</Link> : null}<div style={{ marginTop: row.lead_id ? 4 : 0 }}><IgnoreNumberTarget number={row.client_identifier} openMenu={(number, x, y) => setNumberMenu({ number, x, y })} /></div></td>
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
