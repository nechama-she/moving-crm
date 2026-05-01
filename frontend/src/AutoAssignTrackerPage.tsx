import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type AssignmentMode = "auto" | "queued" | "manual" | "";

type FilterCompany = {
  id: string;
  name: string;
};

type FilterRep = {
  id: string;
  name: string;
  email: string;
};

type AutoAssignEvent = {
  id: number;
  lead_id: string;
  lead_name: string;
  lead_url: string;
  company_id: string;
  company_name: string;
  assigned_to: string;
  rep_name: string;
  assignment_mode: AssignmentMode;
  assignment_reason: string;
  note: string;
  created_at: string;
};

type TrackerStats = {
  total: number;
  queued: number;
  auto: number;
};

function formatDate(value: string): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function modeBadge(mode: AssignmentMode): React.CSSProperties {
  if (mode === "auto") return { ...badgeBase, background: "#d1fae5", color: "#065f46", border: "1px solid #a7f3d0" };
  if (mode === "queued") return { ...badgeBase, background: "#fee2e2", color: "#991b1b", border: "1px solid #fecaca" };
  return { ...badgeBase, background: "#e2e8f0", color: "#334155", border: "1px solid #cbd5e1" };
}

export default function AutoAssignTrackerPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<AutoAssignEvent[]>([]);
  const [companies, setCompanies] = useState<FilterCompany[]>([]);
  const [reps, setReps] = useState<FilterRep[]>([]);
  const [stats, setStats] = useState<TrackerStats>({ total: 0, queued: 0, auto: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [companyIdFilter, setCompanyIdFilter] = useState("");
  const [repIdFilter, setRepIdFilter] = useState("");
  const [modeFilter, setModeFilter] = useState<AssignmentMode>("");
  const [startDateFilter, setStartDateFilter] = useState("");
  const [endDateFilter, setEndDateFilter] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/auto-assign-filters`, { headers: authHeaders(token) })
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
    async function load() {
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({ limit: "500", offset: "0" });
        if (companyIdFilter) params.set("company_id", companyIdFilter);
        if (repIdFilter) params.set("rep_user_id", repIdFilter);
        if (modeFilter) params.set("assignment_mode", modeFilter);
        if (startDateFilter) params.set("start_at", `${startDateFilter}T00:00:00`);
        if (endDateFilter) params.set("end_at", `${endDateFilter}T23:59:59`);

        const res = await fetch(`${API_BASE}/api/auto-assign-events?${params.toString()}`, {
          headers: authHeaders(token),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (cancelled) return;
        setItems(data.items || []);
        setStats(data.stats || { total: 0, queued: 0, auto: 0 });
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [token, companyIdFilter, repIdFilter, modeFilter, startDateFilter, endDateFilter]);

  const disasterRate = useMemo(() => {
    if (!stats.total) return 0;
    return Math.round((stats.queued / stats.total) * 100);
  }, [stats]);

  return (
    <div style={{ padding: "20px 24px", fontFamily: "inherit", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Auto Assignment Tracker</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Track every assignment decision and quickly spot queued lead spikes.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginBottom: 14 }}>
        <div style={kpiCard}>
          <div style={kpiLabel}>Total Events</div>
          <div style={kpiValue}>{stats.total}</div>
        </div>
        <div style={kpiCardWarn}>
          <div style={kpiLabel}>Queued (Risk)</div>
          <div style={kpiValue}>{stats.queued}</div>
        </div>
        <div style={kpiCardGood}>
          <div style={kpiLabel}>Auto Assigned</div>
          <div style={kpiValue}>{stats.auto}</div>
        </div>
        <div style={kpiCard}>
          <div style={kpiLabel}>Queue Rate</div>
          <div style={kpiValue}>{disasterRate}%</div>
        </div>
      </div>

      <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", marginBottom: 16 }}>
        <label style={filterLabel}>
          Date From
          <input type="date" value={startDateFilter} onChange={(e) => setStartDateFilter(e.target.value)} style={filterInput} />
        </label>
        <label style={filterLabel}>
          Date To
          <input type="date" value={endDateFilter} onChange={(e) => setEndDateFilter(e.target.value)} style={filterInput} />
        </label>
        <label style={filterLabel}>
          Company
          <select value={companyIdFilter} onChange={(e) => setCompanyIdFilter(e.target.value)} style={filterInput}>
            <option value="">All companies</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        <label style={filterLabel}>
          Sales Rep
          <select value={repIdFilter} onChange={(e) => setRepIdFilter(e.target.value)} style={filterInput}>
            <option value="">All reps</option>
            {reps.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </label>
        <label style={filterLabel}>
          Mode
          <select value={modeFilter} onChange={(e) => setModeFilter(e.target.value as AssignmentMode)} style={filterInput}>
            <option value="">All modes</option>
            <option value="auto">Auto</option>
            <option value="queued">Queued</option>
            <option value="manual">Manual</option>
          </select>
        </label>
      </div>

      {loading ? <p>Loading...</p> : null}
      {error ? <p style={{ color: "#b91c1c" }}>Error: {error}</p> : null}

      {!loading && !error ? (
        <div style={{ border: "1px solid #dddbda", borderRadius: 6, overflow: "auto", background: "#fff" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1050 }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <th style={thStyle}>Created</th>
                <th style={thStyle}>Lead</th>
                <th style={thStyle}>Company</th>
                <th style={thStyle}>Mode</th>
                <th style={thStyle}>Reason</th>
                <th style={thStyle}>Assigned Rep</th>
                <th style={thStyle}>Note</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td style={tdStyle} colSpan={7}>No assignment events found.</td>
                </tr>
              ) : null}
              {items.map((item) => (
                <tr key={item.id} style={{ borderTop: "1px solid #e5e7eb", background: item.assignment_mode === "queued" ? "#fff7f7" : "#fff" }}>
                  <td style={tdStyle}>{formatDate(item.created_at)}</td>
                  <td style={tdStyle}>
                    {item.lead_url ? (
                      <Link to={item.lead_url} style={{ color: "#2563eb", textDecoration: "none" }}>
                        {item.lead_name || item.lead_id || "Open"}
                      </Link>
                    ) : (
                      item.lead_name || item.lead_id || ""
                    )}
                  </td>
                  <td style={tdStyle}>{item.company_name || ""}</td>
                  <td style={tdStyle}><span style={modeBadge(item.assignment_mode)}>{item.assignment_mode || ""}</span></td>
                  <td style={tdStyle}>{item.assignment_reason || ""}</td>
                  <td style={tdStyle}>{item.rep_name || "Unassigned"}</td>
                  <td style={tdStyle}>{item.note || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

const badgeBase: React.CSSProperties = {
  display: "inline-block",
  borderRadius: 999,
  padding: "2px 8px",
  fontSize: 12,
  fontWeight: 700,
  textTransform: "uppercase",
};

const kpiCard: React.CSSProperties = {
  border: "1px solid #dbe3eb",
  borderRadius: 6,
  background: "#fff",
  padding: 12,
};

const kpiCardWarn: React.CSSProperties = {
  ...kpiCard,
  border: "1px solid #fecaca",
  background: "#fff5f5",
};

const kpiCardGood: React.CSSProperties = {
  ...kpiCard,
  border: "1px solid #bbf7d0",
  background: "#f0fdf4",
};

const kpiLabel: React.CSSProperties = {
  fontSize: 12,
  color: "#64748b",
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  fontWeight: 700,
};

const kpiValue: React.CSSProperties = {
  fontSize: 28,
  color: "#0f172a",
  fontWeight: 700,
  marginTop: 2,
};

const filterLabel: React.CSSProperties = {
  display: "grid",
  gap: 4,
  fontSize: 12,
  color: "#475569",
};

const filterInput: React.CSSProperties = {
  border: "1px solid #dddbda",
  borderRadius: 4,
  padding: "7px 10px",
  fontSize: 13,
  background: "#fff",
};

const thStyle: React.CSSProperties = {
  padding: "11px 12px",
  textAlign: "left",
  fontSize: 12,
  color: "#475569",
  borderBottom: "1px solid #e5e7eb",
  whiteSpace: "nowrap",
};

const tdStyle: React.CSSProperties = {
  padding: "11px 12px",
  fontSize: 13,
  color: "#111827",
  verticalAlign: "top",
};
