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
  lead_created_at: string;
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

function localBoundaryIso(dateOnly: string, endOfDay = false): string {
  const clock = endOfDay ? "23:59:59" : "00:00:00";
  const d = new Date(`${dateOnly}T${clock}`);
  const tzMinutes = -d.getTimezoneOffset();
  const sign = tzMinutes >= 0 ? "+" : "-";
  const hours = String(Math.floor(Math.abs(tzMinutes) / 60)).padStart(2, "0");
  const minutes = String(Math.abs(tzMinutes) % 60).padStart(2, "0");
  return `${dateOnly}T${clock}${sign}${hours}:${minutes}`;
}

function modeBadge(mode: AssignmentMode): React.CSSProperties {
  if (mode === "auto") return { ...badgeBase, background: "#d1fae5", color: "#065f46", border: "1px solid #a7f3d0" };
  if (mode === "queued") return { ...badgeBase, background: "#fef9c3", color: "#854d0e", border: "1px solid #fde68a" };
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
  const [runMode, setRunMode] = useState<"dry" | "live">("dry");
  const [runBusy, setRunBusy] = useState(false);
  const [runMessage, setRunMessage] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const todayStr = (() => { const d = new Date(); const y = d.getFullYear(); const m = String(d.getMonth() + 1).padStart(2, "0"); const day = String(d.getDate()).padStart(2, "0"); return `${y}-${m}-${day}`; })();
  const [startDateFilter, setStartDateFilter] = useState(todayStr);
  const [endDateFilter, setEndDateFilter] = useState(todayStr);

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
        if (startDateFilter) params.set("start_at", localBoundaryIso(startDateFilter, false));
        if (endDateFilter) params.set("end_at", localBoundaryIso(endDateFilter, true));

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
  }, [token, companyIdFilter, repIdFilter, modeFilter, startDateFilter, endDateFilter, reloadKey]);

  async function runBacklogNow() {
    setRunBusy(true);
    setRunMessage("");
    try {
      const dryRun = runMode === "dry";
      const res = await fetch(`${API_BASE}/api/auto-assign-run-ui?dry_run=${dryRun ? "true" : "false"}`, {
        method: "POST",
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRunMessage(data?.message || (dryRun ? "Dry-run completed" : "Live run completed"));
      setReloadKey((v) => v + 1);
    } catch (err: unknown) {
      setRunMessage(err instanceof Error ? `Run failed: ${err.message}` : "Run failed");
    } finally {
      setRunBusy(false);
    }
  }

  const disasterRate = useMemo(() => {
    if (!stats.total) return 0;
    return Math.round((stats.queued / stats.total) * 100);
  }, [stats]);

  const activeKpiButton = (mode: AssignmentMode | "all") => {
    if (mode === "all") return modeFilter === "";
    return modeFilter === mode;
  };

  return (
    <div style={{ padding: "20px 24px", fontFamily: "inherit", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Auto Assignment Tracker</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Track every assignment decision and quickly spot queued lead spikes.
      </p>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>Run Mode</span>
        <button
          type="button"
          onClick={() => setRunMode("dry")}
          style={{
            border: runMode === "dry" ? "1px solid #1d4ed8" : "1px solid #cbd5e1",
            background: runMode === "dry" ? "#eff6ff" : "#fff",
            color: "#1e3a8a",
            borderRadius: 6,
            padding: "6px 10px",
            cursor: "pointer",
            fontWeight: 700,
          }}
        >
          Dry Run
        </button>
        <button
          type="button"
          onClick={() => setRunMode("live")}
          style={{
            border: runMode === "live" ? "1px solid #b91c1c" : "1px solid #cbd5e1",
            background: runMode === "live" ? "#fff1f2" : "#fff",
            color: "#7f1d1d",
            borderRadius: 6,
            padding: "6px 10px",
            cursor: "pointer",
            fontWeight: 700,
          }}
        >
          Live
        </button>
        <button
          type="button"
          onClick={() => void runBacklogNow()}
          disabled={runBusy}
          style={{
            border: "1px solid #0f766e",
            background: runBusy ? "#d1fae5" : "#ecfeff",
            color: "#134e4a",
            borderRadius: 6,
            padding: "6px 12px",
            cursor: runBusy ? "default" : "pointer",
            fontWeight: 700,
          }}
        >
          {runBusy ? "Running..." : `Run Now (${runMode === "dry" ? "Dry" : "Live"})`}
        </button>
        {runMode === "live" ? (
          <span style={{ fontSize: 12, color: "#b91c1c", fontWeight: 700 }}>Live mode updates assignments and SmartMoving.</span>
        ) : null}
        {runMessage ? <span style={{ fontSize: 12, color: "#334155" }}>{runMessage}</span> : null}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginBottom: 14 }}>
        <button type="button" style={kpiButton(kpiCard, activeKpiButton("all"))} onClick={() => setModeFilter("")}>
          <div style={kpiLabel}>Total Events</div>
          <div style={kpiValue}>{stats.total}</div>
        </button>
        <button type="button" style={kpiButton(kpiCardWarn, activeKpiButton("queued"))} onClick={() => setModeFilter("queued")}>
          <div style={kpiLabel}>Queued</div>
          <div style={kpiValue}>{stats.queued}</div>
        </button>
        <button type="button" style={kpiButton(kpiCardGood, activeKpiButton("auto"))} onClick={() => setModeFilter("auto")}>
          <div style={kpiLabel}>Auto Assigned</div>
          <div style={kpiValue}>{stats.auto}</div>
        </button>
        <button type="button" style={kpiButton(kpiCard, activeKpiButton("queued"))} onClick={() => setModeFilter("queued")}>
          <div style={kpiLabel}>Queue Rate</div>
          <div style={kpiValue}>{disasterRate}%</div>
        </button>
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
                <th style={thStyle}>Lead Created</th>
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
                  <td style={tdStyle} colSpan={8}>No assignment events found.</td>
                </tr>
              ) : null}
              {items.map((item) => (
                <tr key={item.id} style={{ borderTop: "1px solid #e5e7eb", background: item.assignment_mode === "queued" ? "#fff7f7" : "#fff" }}>
                  <td style={tdStyle}>{formatDate(item.created_at)}</td>
                  <td style={tdStyle}>{formatDate(item.lead_created_at)}</td>
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

function kpiButton(base: React.CSSProperties, active: boolean): React.CSSProperties {
  return {
    ...base,
    width: "100%",
    textAlign: "left",
    cursor: "pointer",
    boxShadow: active ? "0 0 0 2px #1d4ed8 inset" : "none",
  };
}

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
