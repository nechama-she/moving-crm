import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";

type OutreachType = "due" | "day_2" | "day_3" | "new_lead";

interface FilterCompany {
  id: string;
  name: string;
}

interface FilterRep {
  id: string;
  name: string;
  email: string;
}

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
  company_name?: string;
  sales_rep_name?: string;
}

const tabs: Array<{ value: OutreachType; label: string }> = [
  { value: "due", label: "Due" },
  { value: "day_2", label: "Day 2" },
  { value: "day_3", label: "Day 3" },
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
  const [companies, setCompanies] = useState<FilterCompany[]>([]);
  const [reps, setReps] = useState<FilterRep[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [typeFilter, setTypeFilter] = useState<OutreachType>("due");
  const [companyIdFilter, setCompanyIdFilter] = useState("");
  const [repIdFilter, setRepIdFilter] = useState("");
  const [startDateFilter, setStartDateFilter] = useState("");
  const [endDateFilter, setEndDateFilter] = useState("");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<OutreachEvent | null>(null);

  const PAGE_SIZE = 500;
  const MAX_ROWS_SCAN = 5000;

  useEffect(() => {
    fetch(`${API_BASE}/api/outreach-filters`, { headers: authHeaders(token) })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setCompanies(data.companies || []);
        setReps(data.sales_reps || []);
      })
      .catch(() => {
        setCompanies([]);
        setReps([]);
      });
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    async function loadAll() {
      setLoading(true);
      setError("");
      setInfo("");
      try {
        let offset = 0;
        let hasMore = true;
        const all: OutreachEvent[] = [];

        while (hasMore && all.length < MAX_ROWS_SCAN) {
          const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
          params.set("outreach_type", typeFilter);
          params.set("sort_dir", sortDir);
          if (companyIdFilter) params.set("company_id", companyIdFilter);
          if (repIdFilter) params.set("rep_user_id", repIdFilter);
          if (startDateFilter) params.set("start_at", `${startDateFilter}T00:00:00`);
          if (endDateFilter) params.set("end_at", `${endDateFilter}T23:59:59`);

          const res = await fetch(`${API_BASE}/api/outreach-events?${params.toString()}`, { headers: authHeaders(token) });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await res.json();

          const pageItems = (data.items || []) as OutreachEvent[];
          all.push(...pageItems);
          hasMore = Boolean(data.has_more);
          offset += PAGE_SIZE;
        }

        if (!cancelled) {
          setItems(all);
          if (hasMore) {
            setInfo(`Showing first ${MAX_ROWS_SCAN} rows. Narrow filters to see less data.`);
          }
        }
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadAll();
    return () => { cancelled = true; };
  }, [token, typeFilter, companyIdFilter, repIdFilter, startDateFilter, endDateFilter, sortDir]);

  return (
    <div style={{ padding: "20px 24px", fontFamily: "inherit", height: "calc(100vh - 52px)", boxSizing: "border-box", overflow: "hidden", display: "flex", flexDirection: "column" }}>
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

      <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", marginBottom: 16 }}>
        <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
          Date From
          <input type="date" value={startDateFilter} onChange={(e) => setStartDateFilter(e.target.value)} style={filterInput} />
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
          Date To
          <input type="date" value={endDateFilter} onChange={(e) => setEndDateFilter(e.target.value)} style={filterInput} />
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
          Company
          <select value={companyIdFilter} onChange={(e) => setCompanyIdFilter(e.target.value)} style={filterInput}>
            <option value="">All companies</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
          Sales Rep
          <select value={repIdFilter} onChange={(e) => setRepIdFilter(e.target.value)} style={filterInput}>
            <option value="">All reps</option>
            {reps.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
          Sort By Created
          <select value={sortDir} onChange={(e) => setSortDir(e.target.value as "asc" | "desc")} style={filterInput}>
            <option value="desc">Newest first</option>
            <option value="asc">Oldest first</option>
          </select>
        </label>
      </div>

      {loading ? <p>Loading…</p> : null}
      {error ? <p style={{ color: "#b91c1c" }}>Error: {error}</p> : null}
      {info ? <p style={{ color: "#0f766e" }}>{info}</p> : null}
      {!loading && !error && items.length === 0 ? <p>No outreach activity found.</p> : null}

      {!loading && !error && items.length > 0 ? (
        <div style={{ overflow: "auto", border: "1px solid #e5e7eb", borderRadius: 10, background: "#fff", flex: 1, minHeight: 0 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1200 }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <th style={thStyle}>Created</th>
                <th style={thStyle}>Job ID</th>
                <th style={thStyle}>Lead</th>
                <th style={thStyle}>Company</th>
                <th style={thStyle}>Sales Rep</th>
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
                  <td style={tdStyle}>{item.company_name || ""}</td>
                  <td style={tdStyle}>{item.sales_rep_name || ""}</td>
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
        <div
          onClick={() => setSelected(null)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(2, 6, 23, 0.45)",
            zIndex: 1200,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 20,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(820px, 100%)",
              maxHeight: "85vh",
              overflow: "auto",
              border: "1px solid #d6d6d6",
              borderRadius: 10,
              background: "#fff",
              boxShadow: "0 18px 45px rgba(0,0,0,.25)",
              padding: 16,
            }}
          >
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
              <div><strong>Type:</strong> {formatType(selected.outreach_type)}</div>
              <div><strong>Reason:</strong> {selected.qualification_reason || ""}</div>
              <div><strong>Message:</strong></div>
              <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.4, border: "1px solid #e5e7eb", borderRadius: 6, padding: 10, background: "#f8fafc" }}>
                {selected.message || ""}
              </div>
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

const filterInput: React.CSSProperties = {
  border: "1px solid #dddbda",
  borderRadius: 4,
  padding: "7px 10px",
  fontSize: 13,
  background: "#fff",
};
