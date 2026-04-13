import { useEffect, useState, useRef } from "react";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";

interface Message {
  user_id?: string;
  timestamp: number;
  message_id: string;
  text: string;
  role?: string;
  platform?: string;
  page_id?: string;
  // SMS fields
  direction?: string;
  sales_name?: string;
  phone_number?: string;
  company_name?: string;
  number_id?: string;
}

interface Props {
  userId: string;
  userName: string;
  phoneNumber: string;
  inboxUrl: string;
  aircallNumberId: string;
  companyName: string;
}

const TABS = [
  { key: "messenger", label: "Messenger" },
  { key: "instagram", label: "Instagram" },
  { key: "email", label: "Email" },
  { key: "messages", label: "Messages" },
  { key: "calls", label: "Calls" },
] as const;

export default function ChatMessages({ userId, userName, phoneNumber, inboxUrl, aircallNumberId, companyName }: Props) {
  const { token } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [smsMessages, setSmsMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<string>("");
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const tabPickedRef = useRef(false);

  useEffect(() => {
    const fetches: Promise<void>[] = [];

    if (userId) {
      fetches.push(
        fetch(`${API_BASE}/api/meta/messenger/${encodeURIComponent(userId)}`, { headers: authHeaders(token) })
          .then((res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
          })
          .then((data) => setMessages((prev) => [...prev, ...(data.messages || [])]))
      );
      fetches.push(
        fetch(`${API_BASE}/api/meta/instagram/${encodeURIComponent(userId)}`, { headers: authHeaders(token) })
          .then((res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
          })
          .then((data) => setMessages((prev) => [...prev, ...(data.messages || [])]))
      );
    }

    if (phoneNumber) {
      fetches.push(
        fetch(`${API_BASE}/api/sms/${encodeURIComponent(phoneNumber)}`, { headers: authHeaders(token) })
          .then((res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
          })
          .then((data) => setSmsMessages(data.messages || []))
      );
    }

    if (fetches.length === 0) {
      setLoading(false);
      return;
    }

    Promise.all(fetches)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [userId, phoneNumber]);

  // Combine conversation messages + SMS (tagged with platform)
  const allMessages: Message[] = [
    ...messages,
    ...smsMessages.map((m) => ({
      ...m,
      platform: "messages",
      role: m.direction === "received" ? "user" : "agent",
    })),
  ];

  // Auto-select first tab with data (only once)
  useEffect(() => {
    if (tabPickedRef.current) return;
    if (allMessages.length > 0) {
      const platforms = new Set(allMessages.map((m) => m.platform?.toLowerCase()));
      const firstWithData = TABS.find((t) => platforms.has(t.key));
      if (firstWithData) {
        setActiveTab(firstWithData.key);
        tabPickedRef.current = true;
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, smsMessages]);

  const filtered = activeTab === "messages"
    ? allMessages.filter((m) => m.platform === "messages")
    : allMessages.filter((m) => (m.platform?.toLowerCase() || "") === activeTab);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [filtered]);

  if (loading)
    return <p style={{ padding: 16, color: "#888" }}>Loading messages…</p>;
  if (error)
    return <p style={{ padding: 16, color: "red" }}>Error: {error}</p>;

  // Count per platform for badge
  const counts: Record<string, number> = {};
  for (const m of allMessages) {
    const p = m.platform?.toLowerCase() || "";
    counts[p] = (counts[p] || 0) + 1;
  }

  // Determine if reply is possible on the active tab
  const canReply =
    (activeTab === "messenger" && !!userId) ||
    (activeTab === "messages" && !!phoneNumber && !!aircallNumberId);

  // Extract page_id from the first messenger message (needed for Messenger replies)
  const messengerPageId = messages.find((m) => m.page_id)?.page_id || "";

  const handleSendReply = async () => {
    if (!replyText.trim() || sending) return;
    setSending(true);
    try {
      const body: Record<string, string> = { message: replyText.trim() };
      if (activeTab === "messages") {
        body.aircall_number_id = aircallNumberId;
      } else {
        body.page_id = messengerPageId;
      }
      const endpoint = activeTab === "messages"
        ? `${API_BASE}/api/sms/${encodeURIComponent(phoneNumber)}`
        : `${API_BASE}/api/meta/messenger/${encodeURIComponent(userId)}`;
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      // Add the sent message to the local list immediately
      const now = Date.now() / 1000;
      if (activeTab === "messages") {
        setSmsMessages((prev) => [...prev, {
          message_id: `local-${now}`,
          timestamp: now,
          text: replyText.trim(),
          direction: "sent",
          company_name: companyName,
        }]);
      } else {
        setMessages((prev) => [...prev, {
          message_id: `local-${now}`,
          timestamp: now,
          text: replyText.trim(),
          role: "agent",
          platform: "messenger",
          page_id: messengerPageId,
        }]);
      }
      setReplyText("");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Send failed";
      alert(`Failed to send: ${message}`);
    } finally {
      setSending(false);
    }
  };

  return (
    <div>
      {/* Tabs */}
      <div style={{ display: "flex", gap: 0, borderBottom: "2px solid #e0e0e0", marginBottom: 0 }}>
        {TABS.map((tab) => {
          const count = counts[tab.key] || 0;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                padding: "10px 20px",
                border: "none",
                borderBottom: isActive ? "2px solid #1976d2" : "2px solid transparent",
                marginBottom: -2,
                background: "none",
                cursor: "pointer",
                fontSize: 14,
                fontWeight: isActive ? 600 : 400,
                color: isActive ? "#1976d2" : "#666",
              }}
            >
              {tab.label}
              {count > 0 && (
                <span
                  style={{
                    marginLeft: 6,
                    fontSize: 11,
                    background: isActive ? "#1976d2" : "#ccc",
                    color: "#fff",
                    borderRadius: 10,
                    padding: "1px 7px",
                  }}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* External link bar — sticky above messages */}
      {activeTab === "messenger" && inboxUrl && (
        <div style={{ padding: "8px 12px", background: "#e3f2fd", border: "1px solid #e0e0e0", borderTop: "none", fontSize: 13 }}>
          <a href={inboxUrl} target="_blank" rel="noopener noreferrer" style={{ color: "#1976d2", fontWeight: 600 }}>
            Open in Facebook Inbox →
          </a>
        </div>
      )}

      {/* Messages */}
      <div
        style={{
          maxHeight: 500,
          overflowY: "auto",
          border: "1px solid #e0e0e0",
          borderTop: "none",
          borderRadius: "0 0 8px 8px",
          padding: 16,
          background: "#f9f9f9",
        }}
      >
        {filtered.length === 0 ? (
          <p style={{ color: "#888", textAlign: "center", padding: 24 }}>
            No {TABS.find((t) => t.key === activeTab)?.label} messages.
          </p>
        ) : (
          filtered.map((msg, i) => {
            const isClient = msg.role === "user" || msg.direction === "received";
            const senderName = isClient
              ? userName
              : msg.sales_name || (msg.role ? msg.role.charAt(0).toUpperCase() + msg.role.slice(1) : "Agent");
            // If timestamp < 1e12, it's in seconds — convert to ms
            const tsMs = msg.timestamp < 1e12 ? msg.timestamp * 1000 : msg.timestamp;
            const ts = new Date(tsMs).toLocaleString("en-US", {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            });

            return (
              <div
                key={msg.message_id || i}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: isClient ? "flex-start" : "flex-end",
                  marginBottom: 12,
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: "#888",
                    marginBottom: 2,
                    paddingLeft: isClient ? 8 : 0,
                    paddingRight: isClient ? 0 : 8,
                  }}
                >
                  {senderName} · {ts}
                </div>
                <div
                  style={{
                    maxWidth: "75%",
                    padding: "10px 14px",
                    borderRadius: 12,
                    background: isClient ? "#e3f2fd" : "#e8f5e9",
                    border: isClient ? "1px solid #bbdefb" : "1px solid #c8e6c9",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    fontSize: 14,
                    lineHeight: 1.5,
                  }}
                >
                  {msg.text}
                </div>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>

      {/* Reply input */}
      {canReply && (
        <div style={{ display: "flex", gap: 8, padding: "12px 0", borderTop: "1px solid #e0e0e0" }}>
          <input
            type="text"
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSendReply(); } }}
            placeholder={`Reply via ${activeTab === "messages" ? "SMS" : "Messenger"}…`}
            disabled={sending}
            style={{
              flex: 1,
              padding: "10px 14px",
              borderRadius: 8,
              border: "1px solid #ccc",
              fontSize: 14,
              outline: "none",
            }}
          />
          <button
            onClick={handleSendReply}
            disabled={sending || !replyText.trim()}
            style={{
              padding: "10px 20px",
              borderRadius: 8,
              border: "none",
              background: sending || !replyText.trim() ? "#ccc" : "#1976d2",
              color: "#fff",
              fontSize: 14,
              fontWeight: 600,
              cursor: sending || !replyText.trim() ? "default" : "pointer",
            }}
          >
            {sending ? "Sending…" : "Send"}
          </button>
        </div>
      )}
    </div>
  );
}
