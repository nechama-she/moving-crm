import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import { useRealtimeUpdates } from "./useRealtimeUpdates";

type ChatRow = {
  conversation_id: string;
  lead_id: string;
  client: string;
  rep: string;
  platform: "sms" | "messenger" | "instagram";
  message: string;
  timestamp: number;
  direction: string;
};

const PLATFORM_LABELS: Record<string, string> = {
  sms: "SMS",
  messenger: "Messenger",
  instagram: "Instagram",
};

function formatMessageTime(timestamp: number): string {
  const milliseconds = timestamp < 1e12 ? timestamp * 1000 : timestamp;
  return new Date(milliseconds).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function ChatsPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<ChatRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [source, setSource] = useState<"meta" | "sms">("sms");
  const [cursor, setCursor] = useState("");
  const [hasMore, setHasMore] = useState(true);
  const loadingRef = useRef(false);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const activeSourceRef = useRef<"meta" | "sms">("meta");
  const realtimeTimerRef = useRef(0);

  const loadChats = useCallback((nextCursor = "") => {
    if (loadingRef.current || (!hasMore && nextCursor)) return;
    loadingRef.current = true;
    setLoading(true);
    const requestedSource = source;
    const params = new URLSearchParams({ limit: "20", source: requestedSource });
    if (nextCursor) params.set("cursor", nextCursor);
    fetch(`${API_BASE}/api/chats?${params.toString()}`, { headers: authHeaders(token) })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        if (activeSourceRef.current !== requestedSource) return;
        setItems((current) => {
          const merged = new Map(current.map((item) => [item.conversation_id || `${item.lead_id}-${item.platform}`, item]));
          for (const item of data.items || []) {
            const key = item.conversation_id || `${item.lead_id}-${item.platform}`;
            const previous = merged.get(key);
            if (!previous || item.timestamp > previous.timestamp) merged.set(key, item);
          }
          return [...merged.values()].sort((a, b) => b.timestamp - a.timestamp);
        });
        setCursor(data.next_cursor || "");
        setHasMore(Boolean(data.has_more));
      })
      .catch((reason) => {
        if (activeSourceRef.current !== requestedSource) return;
        setError(reason instanceof Error ? reason.message : "Could not load chats");
        setHasMore(false);
      })
      .finally(() => {
        if (activeSourceRef.current !== requestedSource) return;
        loadingRef.current = false;
        setLoading(false);
      });
  }, [hasMore, source, token]);

  useRealtimeUpdates(token, (event) => {
    if ((source === "sms") !== (event.channel === "sms")) return;
    window.clearTimeout(realtimeTimerRef.current);
    realtimeTimerRef.current = window.setTimeout(() => loadChats(""), 250);
  });

  useEffect(() => {
    activeSourceRef.current = source;
    loadingRef.current = false;
    setItems([]);
    setCursor("");
    setHasMore(true);
    setError("");
    loadChats();
  }, [source]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !hasMore) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && cursor && !loadingRef.current) loadChats(cursor);
    }, { rootMargin: "300px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [cursor, hasMore, loadChats]);

  const visibleItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((item) =>
      item.client.toLowerCase().includes(query)
      || item.rep.toLowerCase().includes(query)
      || item.message.toLowerCase().includes(query)
      || item.platform.includes(query)
    );
  }, [items, search]);

  return (
    <main style={{ padding: 24, width: "100%", maxWidth: 1200, margin: "0 auto", boxSizing: "border-box" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "end", gap: 16, marginBottom: 18, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0, color: "#032d60", fontSize: 24 }}>All Chats</h1>
          <p style={{ margin: "5px 0 0", color: "#64748b" }}>Latest client conversations across every platform.</p>
        </div>
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search chats"
          style={{ width: 280, maxWidth: "100%", padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: 7, fontSize: 14 }}
        />
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, borderBottom: "1px solid #d8dde6" }}>
        {([{"value": "meta", "label": "Messenger / Instagram"}, {"value": "sms", "label": "SMS"}] as const).map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setSource(tab.value)}
            style={{
              padding: "10px 16px",
              border: "none",
              borderBottom: source === tab.value ? "3px solid #0b5cab" : "3px solid transparent",
              background: "transparent",
              color: source === tab.value ? "#032d60" : "#64748b",
              fontWeight: source === tab.value ? 700 : 500,
              cursor: "pointer",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading && items.length === 0 ? <p style={{ color: "#64748b" }}>Loading chats…</p> : null}
      {error ? <p style={{ color: "#ba0517" }}>Could not load more chats: {error}</p> : null}
      {(items.length > 0 || (!loading && !error)) ? (
        <div style={{ border: "1px solid #d8dde6", borderRadius: 8, overflow: "hidden", background: "#fff" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
            <thead style={{ background: "#f3f6f9", color: "#475569", textAlign: "left" }}>
              <tr>
                <th style={{ padding: "12px 16px", width: "25%" }}>Client</th>
                <th style={{ padding: "12px 16px", width: "18%" }}>Rep</th>
                <th style={{ padding: "12px 16px", width: "16%" }}>Platform</th>
                <th style={{ padding: "12px 16px" }}>Message</th>
                <th style={{ padding: "12px 16px", width: 180 }}>Last messaged</th>
              </tr>
            </thead>
            <tbody>
              {visibleItems.map((item) => (
                <tr key={item.conversation_id || `${item.lead_id}-${item.platform}`} style={{ borderTop: "1px solid #e5e7eb" }}>
                  <td style={{ padding: "14px 16px", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {item.lead_id ? <Link
                      to={`/leads/${item.lead_id}`}
                      state={{ backTo: "/chats", backLabel: "← Back to All Chats" }}
                      style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}
                    >
                      {item.client}
                    </Link> : item.platform === "messenger" ? (
                      <a
                        href={`https://www.facebook.com/latest/${encodeURIComponent(item.client)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}
                      >
                        {item.client}
                      </a>
                    ) : <span style={{ color: "#334155", fontWeight: 700 }}>{item.client}</span>}
                  </td>
                  <td style={{ padding: "14px 16px", color: item.rep ? "#334155" : "#94a3b8" }}>{item.rep || "Unassigned"}</td>
                  <td style={{ padding: "14px 16px" }}>{PLATFORM_LABELS[item.platform] || item.platform}</td>
                  <td style={{ padding: "14px 16px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#334155" }} title={item.message}>
                    {item.message || "—"}
                  </td>
                  <td style={{ padding: "14px 16px", color: "#64748b", fontSize: 13 }}>{formatMessageTime(item.timestamp)}</td>
                </tr>
              ))}
              {visibleItems.length === 0 ? (
                <tr><td colSpan={5} style={{ padding: 32, textAlign: "center", color: "#64748b" }}>No chats found.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
      <div ref={sentinelRef} style={{ minHeight: 24, padding: 12, textAlign: "center", color: "#64748b" }}>
        {loading && items.length > 0 ? "Loading more chats…" : null}
      </div>
    </main>
  );
}
