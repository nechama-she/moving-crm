import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";

type OutreachType = "due" | "day_2" | "new_lead";

interface OutreachEvent {
  id: number;
  lead_id: string;
  lead_name: string;
  lead_url: string;
  smartmoving_id: string;
  note_id: string;
  outreach_type: string;
  job_id: string;
  qualified: boolean;
  qualification_reason: string;
  message: string;
  messenger: boolean;
  aircall: boolean;
  dry_run: boolean;
  created_at: string;
}

const tabs: Array<{ value: OutreachType; label: string }> = [
  { value: "due", label: "Due" },
  { value: "day_2", label: "Day 2" },
  { value: "new_lead", label: "New Leads" },
];

function yesNo(value: boolean): string {
  return value ? "Yes" : "No";
}

function formatType(value: string): string {
  if (value === "day_2") return "Day 2";
  if (value === "day_3") return "Day 3";
  if (value === "new_lead") return "New Lead";
  if (value === "due") return "Due";
  return value;
}

function formatDate(value: string): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

export default function OutreachEventsPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<OutreachEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [typeFilter, setTypeFilter] = useState<OutreachType>("due");
  const [selected, setSelected] = useState<OutreachEvent | null>(null);

  useEffect(() => {
    const params = new URLSearchParams({ limit: "200" });
    params.set("outreach_type", typeFilter);

    setLoading(true);
    setError("");
    fetch(`${API_BASE}/api/outreach-events?${params.toString()}`, { headers: authHeaders(token) })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => setItems(data.items || []))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Unknown error"))
      .finally(() => setLoading(false));
  }, [token, typeFilter]);

  return (
    <div style={{ padding: 24, fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0 }}>Outreach Activity</h1>
          <p style={{ margin: "6px 0 0", color: "#666", fontSize: 14 }}>
            Split by tab to avoid one big dump.
          </p>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {tabs.map((tab) => (
          <button
            key={tab.value}
            onClick={() => {
              setTypeFilter(tab.value);
              setSelected(null);
            }}
            style={{
              padding: "8px 12px",
              borderRadius: 999,
              border: typeFilter === tab.value ? "1px solid #1d4ed8" : "1px solid #cbd5e1",
              background: typeFilter === tab.value ? "#dbeafe" : "#fff",
              color: typeFilter === tab.value ? "#1e3a8a" : "#334155",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? <p>Loading…</p> : null}
      {error ? <p style={{ color: "#b91c1c" }}>Error: {error}</p> : null}
      {!loading && !error && items.length === 0 ? <p>No outreach activity found.</p> : null}

      {!loading && !error && items.length > 0 ? (
        <div style={{ overflowX: "auto", border: "1px solid #e5e7eb", borderRadius: 10 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1200 }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <th style={thStyle}>Created</th>
                <th style={thStyle}>Job ID</th>
                <th style={thStyle}>Lead</th>
                <th style={thStyle}>Type</th>
                <th style={thStyle}>Qualified</th>
                <th style={thStyle}>Details</th>
                <th style={thStyle}>Messenger</th>
                <th style={thStyle}>Aircall</th>
                <th style={thStyle}>Dry Run</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} style={{ borderTop: "1px solid #e5e7eb" }}>
                  <td style={tdStyle}>{formatDate(item.created_at)}</td>
                  <td style={tdStyle}>
                    {item.lead_url ? (
                      <Link to={item.lead_url} style={{ color: "#2563eb", textDecoration: "none" }}>
                        {item.job_id || item.smartmoving_id || "Open"}
                      </Link>
                    ) : (
                      item.job_id || item.smartmoving_id || ""
                    )}
                  </td>
                  <td style={tdStyle}>{item.lead_name || ""}</td>
                  <td style={tdStyle}>{formatType(item.outreach_type)}</td>
                  <td style={tdStyle}>{yesNo(item.qualified)}</td>
                  <td style={tdStyle}>
                    <button
                      type="button"
                      onClick={() => setSelected(item)}
                      style={{
                        border: "none",
                        background: "none",
                        color: "#2563eb",
                        cursor: "pointer",
                        padding: 0,
                        textDecoration: "underline",
                        fontSize: 13,
                      }}
                    >
                      View
                    </button>
                  </td>
                  <td style={tdStyle}>{yesNo(item.messenger)}</td>
                  <td style={tdStyle}>{yesNo(item.aircall)}</td>
                  <td style={tdStyle}>{yesNo(item.dry_run)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {selected ? (
        <div style={{ marginTop: 16, border: "1px solid #e5e7eb", borderRadius: 10, padding: 14, background: "#fff" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <h2 style={{ margin: 0, fontSize: 16 }}>Outreach Details</h2>
            <button
              type="button"
              onClick={() => setSelected(null)}
              style={{ border: "1px solid #cbd5e1", borderRadius: 6, background: "#fff", padding: "4px 10px", cursor: "pointer" }}
            >
              Close
            </button>
          </div>
          <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
            <div><strong>Reason:</strong> {selected.qualification_reason || ""}</div>
            <div><strong>Message:</strong></div>
            <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.4, border: "1px solid #e5e7eb", borderRadius: 6, padding: 10 }}>
              {selected.message || ""}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: "12px 14px",
  textAlign: "left",
  fontSize: 13,
  color: "#475569",
  borderBottom: "1px solid #e5e7eb",
  whiteSpace: "nowrap",
};

const tdStyle: React.CSSProperties = {
  padding: "12px 14px",
  verticalAlign: "top",
  fontSize: 14,
  color: "#111827",
};
