import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Category = "new" | "no_first_contact" | "unanswered" | "missed_calls";
type Counts = Record<Category, number>;
type ActivityLead = {
  lead_id: string;
  client: string;
  rep: string;
  company: string;
  created_at: string;
  age_minutes: number;
  status: string;
  platform: string;
  message: string;
};

const CARDS: Array<{ key: Category; title: string; description: string; color: string; tint: string }> = [
  { key: "new", title: "New Leads", description: "Received within the last 30 minutes", color: "#0b5cab", tint: "#eef6ff" },
  { key: "no_first_contact", title: "No First Contact", description: "Older than 30 minutes with no recorded call", color: "#c2410c", tint: "#fff7ed" },
  { key: "unanswered", title: "Unanswered Messages", description: "Client messages waiting for a response", color: "#a16207", tint: "#fefce8" },
  { key: "missed_calls", title: "Missed Calls", description: "Missed calls without a callback", color: "#b91c1c", tint: "#fef2f2" },
];

function waitingTime(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours < 24) return `${hours}h ${remainder}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

export default function RepActivityPage() {
  const { token } = useAuth();
  const [category, setCategory] = useState<Category>("new");
  const [counts, setCounts] = useState<Counts>({ new: 0, no_first_contact: 0, unanswered: 0, missed_calls: 0 });
  const [items, setItems] = useState<ActivityLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [hasMore, setHasMore] = useState(false);

  const load = useCallback(async (offset = 0) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ category, limit: "50", offset: String(offset) });
      const response = await fetch(`${API_BASE}/api/rep-activity?${params}`, { headers: authHeaders(token) });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      const data = await response.json();
      setCounts(data.counts);
      setItems((current) => offset === 0 ? data.items : [...current, ...data.items]);
      setHasMore(Boolean(data.has_more));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load rep activity");
    } finally {
      setLoading(false);
    }
  }, [category, token]);

  useEffect(() => { void load(0); }, [load]);

  const selectedCard = CARDS.find((card) => card.key === category)!;

  return (
    <main style={{ padding: 24, width: "100%", maxWidth: 1280, margin: "0 auto", boxSizing: "border-box" }}>
      <h1 style={{ margin: 0, color: "#032d60", fontSize: 24 }}>Rep Activity</h1>
      <p style={{ margin: "6px 0 20px", color: "#64748b" }}>Leads requiring attention based on response activity.</p>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14, marginBottom: 24 }}>
        {CARDS.map((card) => {
          const selected = category === card.key;
          return (
            <button
              key={card.key}
              type="button"
              onClick={() => setCategory(card.key)}
              style={{ textAlign: "left", padding: 18, borderRadius: 10, border: selected ? `2px solid ${card.color}` : "1px solid #d8dde6", background: card.tint, cursor: "pointer", minHeight: 130 }}
            >
              <div style={{ display: "flex", alignItems: "start", justifyContent: "space-between", gap: 12 }}>
                <strong style={{ color: card.color, fontSize: 16 }}>{card.title}</strong>
                <span style={{ color: card.color, fontSize: 30, lineHeight: 1, fontWeight: 800 }}>{counts[card.key]}</span>
              </div>
              <div style={{ marginTop: 16, color: "#475569", fontSize: 13, lineHeight: 1.4 }}>{card.description}</div>
            </button>
          );
        })}
      </section>

      <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
        <div style={{ padding: "14px 18px", background: selectedCard.tint, borderBottom: "1px solid #d8dde6" }}>
          <strong style={{ color: selectedCard.color }}>{selectedCard.title}</strong>
        </div>
        {error ? <p style={{ padding: 18, color: "#b91c1c" }}>{error}</p> : null}
        {!loading && !error && items.length === 0 ? <p style={{ padding: 24, color: "#64748b" }}>No leads in this list.</p> : null}
        {items.map((lead) => (
          <div key={lead.lead_id} style={{ display: "grid", gridTemplateColumns: category === "unanswered" ? "minmax(160px, 1.2fr) 100px minmax(220px, 1.8fr) minmax(130px, 1fr) minmax(140px, 1fr) 90px" : "minmax(180px, 1.4fr) minmax(140px, 1fr) minmax(150px, 1fr) 120px 100px", gap: 16, alignItems: "center", padding: "14px 18px", borderTop: "1px solid #e5e7eb" }}>
            <Link to={`/leads/${lead.lead_id}`} state={{ backTo: "/rep-activity", backLabel: "← Back to Rep Activity" }} style={{ color: "#0b5cab", fontWeight: 700, textDecoration: "none" }}>{lead.client}</Link>
            {category === "unanswered" ? <span style={{ color: "#475569", textTransform: "capitalize" }}>{lead.platform || "Unknown"}</span> : null}
            {category === "unanswered" ? <span title={lead.message} style={{ color: "#334155", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lead.message || "No preview"}</span> : null}
            <span>{lead.rep || "Unassigned"}</span>
            <span style={{ color: "#475569" }}>{lead.company}</span>
            {category !== "unanswered" ? <span style={{ color: "#475569" }}>{lead.status}</span> : null}
            <strong style={{ color: category === "new" ? "#0b5cab" : "#c2410c" }}>{waitingTime(lead.age_minutes)}</strong>
          </div>
        ))}
        {loading ? <p style={{ padding: 18, color: "#64748b" }}>Loading…</p> : null}
        {!loading && hasMore ? <button type="button" onClick={() => void load(items.length)} style={{ margin: 16, padding: "9px 16px", border: "1px solid #0b5cab", borderRadius: 6, background: "#fff", color: "#0b5cab", cursor: "pointer", fontWeight: 700 }}>Load more</button> : null}
      </section>
    </main>
  );
}
