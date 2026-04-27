import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";

type OutreachType = "" | "due" | "day_2" | "day_3" | "new_lead";

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

const typeOptions: Array<{ value: OutreachType; label: string }> = [
  { value: "", label: "All" },
  { value: "due", label: "Due" },
  { value: "day_2", label: "Day 2" },
  { value: "day_3", label: "Day 3" },
  { value: "new_lead", label: "New Lead" },
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
  const [typeFilter, setTypeFilter] = useState<OutreachType>("");

  useEffect(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (typeFilter) params.set("outreach_type", typeFilter);

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
            Clear view of due followups, day 2, day 3, and new-lead messages.
          </p>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
          Type
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as OutreachType)}
            style={{ padding: "8px 10px", borderRadius: 6, border: "1px solid #ccc", background: "#fff" }}
          >
            {typeOptions.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
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
                <th style={thStyle}>Reason</th>
                <th style={thStyle}>Message</th>
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
                  <td style={tdStyle}>{item.qualification_reason || ""}</td>
                  <td style={{ ...tdStyle, maxWidth: 420 }}>
                    <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.4 }}>{item.message || ""}</div>
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
