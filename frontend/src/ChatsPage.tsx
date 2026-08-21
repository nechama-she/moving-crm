import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type ChatRow = {
  lead_id: string;
  client: string;
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

  useEffect(() => {
    fetch(`${API_BASE}/api/chats`, { headers: authHeaders(token) })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((data) => setItems(data.items || []))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load chats"))
      .finally(() => setLoading(false));
  }, [token]);

  const visibleItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((item) =>
      item.client.toLowerCase().includes(query)
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

      {loading ? <p style={{ color: "#64748b" }}>Loading chats…</p> : null}
      {error ? <p style={{ color: "#ba0517" }}>{error}</p> : null}
      {!loading && !error ? (
        <div style={{ border: "1px solid #d8dde6", borderRadius: 8, overflow: "hidden", background: "#fff" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
            <thead style={{ background: "#f3f6f9", color: "#475569", textAlign: "left" }}>
              <tr>
                <th style={{ padding: "12px 16px", width: "25%" }}>Client</th>
                <th style={{ padding: "12px 16px", width: "16%" }}>Platform</th>
                <th style={{ padding: "12px 16px" }}>Message</th>
                <th style={{ padding: "12px 16px", width: 180 }}>Last messaged</th>
              </tr>
            </thead>
            <tbody>
              {visibleItems.map((item) => (
                <tr key={`${item.lead_id}-${item.platform}`} style={{ borderTop: "1px solid #e5e7eb" }}>
                  <td style={{ padding: "14px 16px", overflow: "hidden", textOverflow: "ellipsis" }}>
                    <Link
                      to={`/leads/${item.lead_id}`}
                      state={{ backTo: "/chats", backLabel: "← Back to All Chats" }}
                      style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}
                    >
                      {item.client}
                    </Link>
                  </td>
                  <td style={{ padding: "14px 16px" }}>{PLATFORM_LABELS[item.platform] || item.platform}</td>
                  <td style={{ padding: "14px 16px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#334155" }} title={item.message}>
                    {item.message || "—"}
                  </td>
                  <td style={{ padding: "14px 16px", color: "#64748b", fontSize: 13 }}>{formatMessageTime(item.timestamp)}</td>
                </tr>
              ))}
              {visibleItems.length === 0 ? (
                <tr><td colSpan={4} style={{ padding: 32, textAlign: "center", color: "#64748b" }}>No chats found.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </main>
  );
}
