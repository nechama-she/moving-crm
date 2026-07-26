import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type PendingDuplication = {
  schedule_name: string;
  lead_id: string;
  lead_name: string;
  smartmoving_id: string;
  source_company_name: string;
  target_company_name: string;
  target_referral_source: string;
  fire_at: string;
  created_at: string;
};

async function responseError(response: Response): Promise<string> {
  const body = await response.json().catch(() => null);
  return body?.detail || `Request failed (${response.status})`;
}

function formatDate(value: string): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function PendingDuplicationsPage() {
  const { token, user } = useAuth();
  const [items, setItems] = useState<PendingDuplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/lead-duplications/pending`, {
        headers: authHeaders(token),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const data = await response.json();
      setItems(data.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load pending duplications");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function deleteSchedule(item: PendingDuplication) {
    const label = item.lead_name || item.lead_id || item.schedule_name;
    if (!window.confirm(`Cancel the pending duplication for ${label}?`)) return;

    setDeleting(item.schedule_name);
    setError("");
    try {
      const response = await fetch(
        `${API_BASE}/api/lead-duplications/pending/${encodeURIComponent(item.schedule_name)}`,
        { method: "DELETE", headers: authHeaders(token) },
      );
      if (!response.ok) throw new Error(await responseError(response));
      setItems((current) => current.filter((row) => row.schedule_name !== item.schedule_name));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete pending duplication");
    } finally {
      setDeleting("");
    }
  }

  if (user?.role !== "admin") {
    return <div style={page}><p style={errorBox}>Admin access is required.</p></div>;
  }

  return (
    <div style={page}>
      <div style={headerRow}>
        <div>
          <h1 style={title}>Pending Lead Duplications</h1>
          <p style={subtitle}>Leads waiting for their scheduled copy to another company.</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading} style={secondaryButton}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error ? <div style={errorBox}>{error}</div> : null}

      <section style={card}>
        <div style={cardHeader}>
          <strong>{items.length} pending</strong>
          <span style={{ color: "#706e6b", fontSize: 12 }}>Schedules disappear automatically after they run.</span>
        </div>

        {loading && items.length === 0 ? (
          <p style={emptyState}>Loading pending duplications…</p>
        ) : items.length === 0 ? (
          <p style={emptyState}>No leads are waiting for duplication.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={table}>
              <thead>
                <tr>
                  <th style={th}>Lead</th>
                  <th style={th}>SmartMoving ID</th>
                  <th style={th}>From</th>
                  <th style={th}>Duplicate to</th>
                  <th style={th}>Referral source</th>
                  <th style={th}>Scheduled for</th>
                  <th style={{ ...th, textAlign: "right" }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.schedule_name}>
                    <td style={td}>
                      {item.lead_id ? (
                        <Link to={`/leads/${item.lead_id}`} style={leadLink}>
                          {item.lead_name || item.lead_id}
                        </Link>
                      ) : "Unknown lead"}
                      {item.lead_id ? (
                        <div style={idText}>
                          <Link to={`/leads/${item.lead_id}`} style={idLink}>
                            {item.lead_id}
                          </Link>
                        </div>
                      ) : null}
                    </td>
                    <td style={td}>
                      {item.smartmoving_id ? (
                        <a
                          href={`https://app.smartmoving.com/opportunities/${encodeURIComponent(item.smartmoving_id)}`}
                          target="_blank"
                          rel="noreferrer"
                          style={leadLink}
                        >
                          {item.smartmoving_id}
                        </a>
                      ) : "—"}
                    </td>
                    <td style={td}>{item.source_company_name || "—"}</td>
                    <td style={td}><strong>{item.target_company_name || "—"}</strong></td>
                    <td style={td}>{item.target_referral_source || "—"}</td>
                    <td style={td}>{formatDate(item.fire_at)}</td>
                    <td style={{ ...td, textAlign: "right" }}>
                      <button
                        type="button"
                        onClick={() => void deleteSchedule(item)}
                        disabled={deleting === item.schedule_name}
                        style={dangerButton}
                      >
                        {deleting === item.schedule_name ? "Deleting…" : "Delete"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

const page: React.CSSProperties = {
  padding: "20px 24px",
  overflow: "auto",
  height: "calc(100vh - 52px)",
  boxSizing: "border-box",
};

const headerRow: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 16,
  marginBottom: 16,
};

const title: React.CSSProperties = { margin: "0 0 4px", fontSize: 20, color: "#032d60" };
const subtitle: React.CSSProperties = { margin: 0, color: "#706e6b", fontSize: 13 };
const card: React.CSSProperties = { border: "1px solid #dddbda", borderRadius: 4, background: "#fff" };
const cardHeader: React.CSSProperties = {
  padding: "12px 14px",
  borderBottom: "1px solid #dddbda",
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
};
const table: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const th: React.CSSProperties = {
  padding: "10px 12px",
  textAlign: "left",
  color: "#3e3e3c",
  background: "#f3f3f3",
  borderBottom: "1px solid #dddbda",
  whiteSpace: "nowrap",
};
const td: React.CSSProperties = { padding: "12px", borderBottom: "1px solid #ecebea", color: "#181818" };
const leadLink: React.CSSProperties = { color: "#0176d3", fontWeight: 700, textDecoration: "none" };
const idText: React.CSSProperties = { marginTop: 3, color: "#706e6b", fontSize: 11 };
const idLink: React.CSSProperties = { color: "#706e6b", textDecoration: "underline" };
const emptyState: React.CSSProperties = { margin: 0, padding: 28, textAlign: "center", color: "#706e6b" };
const errorBox: React.CSSProperties = {
  marginBottom: 12,
  padding: 10,
  border: "1px solid #ea001e",
  borderRadius: 4,
  background: "#fef1ee",
  color: "#ba0517",
};
const secondaryButton: React.CSSProperties = {
  padding: "7px 12px",
  border: "1px solid #0176d3",
  borderRadius: 4,
  background: "#fff",
  color: "#0176d3",
  fontWeight: 600,
  cursor: "pointer",
};
const dangerButton: React.CSSProperties = {
  padding: "6px 10px",
  border: "1px solid #ba0517",
  borderRadius: 4,
  background: "#fff",
  color: "#ba0517",
  fontWeight: 600,
  cursor: "pointer",
};
