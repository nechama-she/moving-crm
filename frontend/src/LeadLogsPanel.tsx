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
  request: unknown;
  response: unknown;
  request_payload: unknown;
  external_response: unknown;
  response_status: number | null;
  error: string;
  sql: unknown[];
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

type BackgroundRequest = {
  request?: {
    method?: string;
    url?: string;
    headers?: Record<string, unknown>;
    payload?: unknown;
  } | null;
  response?: {
    status_code?: number | null;
    body?: unknown;
  } | null;
};

function backgroundRequests(value: unknown): BackgroundRequest[] {
  const found: BackgroundRequest[] = [];
  const visit = (node: unknown) => {
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (!node || typeof node !== "object") return;
    const record = node as Record<string, unknown>;
    if (Array.isArray(record.logs)) {
      found.push(...(record.logs as BackgroundRequest[]));
    }
    Object.entries(record).forEach(([key, child]) => {
      if (key !== "logs") visit(child);
    });
  };
  visit(value);
  return found;
}

function withoutLogs(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withoutLogs);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => key !== "logs")
      .map(([key, child]) => [key, withoutLogs(child)]),
  );
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
          const requestValue = item.request ?? item.request_payload;
          const responseValue = item.response ?? item.external_response;
          const nestedRequests = backgroundRequests(requestValue);
          const payloadValue = withoutLogs(requestValue);
          return (
            <article key={item.id} style={logCard}>
              <div style={timestampRow}>
                <span style={metaLabel}>Timestamp</span>
                <time>{formatDate(item.created_at)}</time>
              </div>
              <div style={logHeader}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <code style={methodBadge}>{item.method}</code>
                  <strong style={{ color: "#032d60" }}>{item.endpoint}</strong>
                  {item.response_status !== null ? (
                    <span style={failed ? failedStatus : successStatus}>{item.response_status}</span>
                  ) : null}
                </div>
              </div>

              <div style={metaGrid}>
                <div><span style={metaLabel}>Source</span>{item.source || "API"}</div>
                <div><span style={metaLabel}>Updated by</span>{item.actor_name || item.actor_user_id || "System/API"}</div>
              </div>

              {item.error ? <div style={errorBox}>{item.error}</div> : null}

              <details open style={details}>
                <summary style={summary}>Background requests ({nestedRequests.length})</summary>
                {nestedRequests.length === 0 ? (
                  <p style={emptyNested}>No background requests supplied</p>
                ) : (
                  <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                    {nestedRequests.map((entry, index) => (
                      <details key={index} style={nestedCard}>
                        <summary style={{ ...nestedHeader, cursor: "pointer", listStylePosition: "inside" }}>
                          <code style={methodBadge}>{entry.request?.method || "REQUEST"}</code>
                          <strong>{entry.request?.url || "URL not supplied"}</strong>
                          {entry.response?.status_code !== null && entry.response?.status_code !== undefined ? (
                            <span style={(entry.response.status_code || 0) >= 400 ? failedStatus : successStatus}>
                              {entry.response.status_code}
                            </span>
                          ) : null}
                        </summary>
                        <div style={nestedColumns}>
                          <div>
                            <div style={sectionLabel}>Request</div>
                            <pre style={jsonBlock}>{pretty(entry.request) || "{}"}</pre>
                          </div>
                          <div>
                            <div style={sectionLabel}>Response</div>
                            <pre style={jsonBlock}>{pretty(entry.response) || "{}"}</pre>
                          </div>
                        </div>
                      </details>
                    ))}
                  </div>
                )}
              </details>

              <details open style={details}>
                <summary style={summary}>Payload</summary>
                <pre style={jsonBlock}>{pretty(payloadValue) || "{}"}</pre>
              </details>

              <details open style={details}>
                <summary style={summary}>Response</summary>
                <pre style={jsonBlock}>{pretty(responseValue) || "No response recorded"}</pre>
              </details>

              <details open style={details}>
                <summary style={summary}>SQL ({item.sql?.length || 0})</summary>
                <pre style={jsonBlock}>{pretty(item.sql) || "No SQL writes recorded"}</pre>
              </details>
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
const timestampRow: React.CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "baseline",
  color: "#3e3e3c",
  fontSize: 12,
  marginBottom: 8,
};
const badge: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  borderRadius: 999,
  padding: "2px 8px",
  fontSize: 11,
  fontWeight: 700,
};
const methodBadge: React.CSSProperties = { ...badge, color: "#3e3e3c", background: "#f3f2f2" };
const successStatus: React.CSSProperties = { ...badge, color: "#2e844a", background: "#e3fcef" };
const failedStatus: React.CSSProperties = { ...badge, color: "#ba0517", background: "#fef1ee" };
const metaGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(260px, 2fr) minmax(160px, 1fr)",
  gap: 12,
  marginBottom: 10,
  fontSize: 12,
};
const metaLabel: React.CSSProperties = { display: "block", color: "#706e6b", marginBottom: 3 };
const details: React.CSSProperties = { borderTop: "1px solid #ecebea", paddingTop: 8, marginTop: 8 };
const summary: React.CSSProperties = { color: "#032d60", fontWeight: 700, fontSize: 12, cursor: "pointer" };
const nestedCard: React.CSSProperties = {
  border: "1px solid #dddbda",
  borderRadius: 4,
  padding: 10,
  background: "#fafaf9",
};
const nestedHeader: React.CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  flexWrap: "wrap",
  color: "#032d60",
};
const nestedColumns: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 8,
  marginTop: 8,
};
const sectionLabel: React.CSSProperties = { color: "#3e3e3c", fontWeight: 700, fontSize: 12 };
const emptyNested: React.CSSProperties = { color: "#706e6b", fontSize: 12, margin: "8px 0 0" };
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
