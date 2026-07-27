import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders } from "./AuthContext";

type LeadUpdateLog = {
  id: string;
  lead_id: string;
  actor_user_id: string;
  actor_name: string;
  source: string;
  method: string;
  endpoint: string;
  event_type: string;
  request_payload: unknown;
  external_response: unknown;
  response_status: number | null;
  error: string;
  created_at: string;
};

function pretty(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function LeadLogsPanel({ leadId, token }: { leadId: string; token: string | null }) {
  const [items, setItems] = useState<LeadUpdateLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/leads/${leadId}/logs?limit=500`, {
        headers: authHeaders(token),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
      setItems(body?.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load lead logs");
    } finally {
      setLoading(false);
    }
  }, [leadId, token]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <div style={toolbar}>
        <span>{items.length} update log{items.length === 1 ? "" : "s"}</span>
        <button type="button" onClick={() => void load()} disabled={loading} style={refreshButton}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error ? <div style={errorBox}>{error}</div> : null}
      {loading && items.length === 0 ? <p style={empty}>Loading logs…</p> : null}
      {!loading && items.length === 0 ? (
        <p style={empty}>No updates have been logged for this lead yet.</p>
      ) : null}

      <div style={{ display: "grid", gap: 10 }}>
        {items.map((item) => {
          const failed = item.response_status !== null && item.response_status >= 400;
          return (
            <article key={item.id} style={logCard}>
              <div style={logHeader}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={item.source === "smartmoving" ? smartmovingBadge : apiBadge}>
                    {item.source === "smartmoving" ? "SmartMoving" : "API"}
                  </span>
                  <strong style={{ color: "#032d60" }}>{item.event_type.replace(/_/g, " ")}</strong>
                  <code style={methodBadge}>{item.method}</code>
                  {item.response_status !== null ? (
                    <span style={failed ? failedStatus : successStatus}>{item.response_status}</span>
                  ) : null}
                </div>
                <time style={timeText}>{formatDate(item.created_at)}</time>
              </div>

              <div style={metaGrid}>
                <div><span style={metaLabel}>Endpoint</span><code style={endpointText}>{item.endpoint}</code></div>
                <div><span style={metaLabel}>Updated by</span>{item.actor_name || item.actor_user_id || "System/API"}</div>
              </div>

              {item.error ? <div style={errorBox}>{item.error}</div> : null}

              <details open style={details}>
                <summary style={summary}>Request payload</summary>
                <pre style={jsonBlock}>{pretty(item.request_payload) || "{}"}</pre>
              </details>

              {item.external_response !== null && item.external_response !== undefined ? (
                <details style={details}>
                  <summary style={summary}>Full SmartMoving response</summary>
                  <pre style={jsonBlock}>{pretty(item.external_response)}</pre>
                </details>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}

const toolbar: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: 12,
  color: "#3e3e3c",
  fontSize: 13,
  fontWeight: 600,
};
const refreshButton: React.CSSProperties = {
  border: "1px solid #0176d3",
  background: "#fff",
  color: "#0176d3",
  borderRadius: 4,
  padding: "6px 10px",
  fontWeight: 600,
  cursor: "pointer",
};
const logCard: React.CSSProperties = {
  border: "1px solid #dddbda",
  borderRadius: 4,
  padding: 12,
  background: "#fff",
};
const logHeader: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 12,
  marginBottom: 10,
};
const badge: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  borderRadius: 999,
  padding: "2px 8px",
  fontSize: 11,
  fontWeight: 700,
};
const apiBadge: React.CSSProperties = { ...badge, color: "#014486", background: "#eaf5fe" };
const smartmovingBadge: React.CSSProperties = { ...badge, color: "#056764", background: "#def9f3" };
const methodBadge: React.CSSProperties = { ...badge, color: "#3e3e3c", background: "#f3f2f2" };
const successStatus: React.CSSProperties = { ...badge, color: "#2e844a", background: "#e3fcef" };
const failedStatus: React.CSSProperties = { ...badge, color: "#ba0517", background: "#fef1ee" };
const timeText: React.CSSProperties = { color: "#706e6b", fontSize: 12, whiteSpace: "nowrap" };
const metaGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(260px, 2fr) minmax(160px, 1fr)",
  gap: 12,
  marginBottom: 10,
  fontSize: 12,
};
const metaLabel: React.CSSProperties = { display: "block", color: "#706e6b", marginBottom: 3 };
const endpointText: React.CSSProperties = { color: "#181818", wordBreak: "break-all" };
const details: React.CSSProperties = { borderTop: "1px solid #ecebea", paddingTop: 8, marginTop: 8 };
const summary: React.CSSProperties = { color: "#032d60", fontWeight: 700, fontSize: 12, cursor: "pointer" };
const jsonBlock: React.CSSProperties = {
  margin: "8px 0 0",
  padding: 10,
  maxHeight: 420,
  overflow: "auto",
  borderRadius: 4,
  background: "#181818",
  color: "#f3f3f3",
  fontSize: 11,
  lineHeight: 1.45,
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
};
const errorBox: React.CSSProperties = {
  marginBottom: 10,
  border: "1px solid #ea001e",
  borderRadius: 4,
  padding: 8,
  color: "#ba0517",
  background: "#fef1ee",
  fontSize: 12,
};
const empty: React.CSSProperties = { color: "#706e6b", fontSize: 13, textAlign: "center", padding: 20 };
