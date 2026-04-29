import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Rep = {
  id: string;
  name: string;
  email: string;
  role: string;
};

type LeadRow = {
  id: string;
  full_name?: string;
  company_name?: string;
  created_time?: string;
};

const PAGE_SIZE = 200;
const MAX_LEADS_SCAN = 5000;

function toMs(value: string | undefined): number {
  if (!value) return 0;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? 0 : d.getTime();
}

function prettyDate(value: string | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

export default function PeriodAssignPage() {
  const { token } = useAuth();
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [reps, setReps] = useState<Rep[]>([]);
  const [repId, setRepId] = useState("");
  const [previewLeads, setPreviewLeads] = useState<LeadRow[]>([]);
  const [loadingReps, setLoadingReps] = useState(true);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  useEffect(() => {
    setLoadingReps(true);
    setError("");
    fetch(`${API_BASE}/api/users`, { headers: authHeaders(token) })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((rows: Rep[]) => {
        const salesReps = (rows || []).filter((u) => u.role === "sales_rep");
        setReps(salesReps);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load reps"))
      .finally(() => setLoadingReps(false));
  }, [token]);

  const selectedRep = useMemo(() => reps.find((r) => r.id === repId), [reps, repId]);

  async function loadPreview() {
    setError("");
    setInfo("");
    setPreviewLeads([]);

    const startMs = toMs(startAt);
    const endMs = toMs(endAt);
    if (!startMs || !endMs || endMs <= startMs) {
      setError("Choose a valid start and end period.");
      return;
    }

    setLoadingPreview(true);
    try {
      let offset = 0;
      let hasMore = true;
      const all: LeadRow[] = [];

      while (hasMore && all.length < MAX_LEADS_SCAN) {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(offset),
        });
        const res = await fetch(`${API_BASE}/api/leads?${params.toString()}`, { headers: authHeaders(token) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const items = (data.items || []) as LeadRow[];

        for (const lead of items) {
          const createdMs = toMs(lead.created_time);
          if (createdMs >= startMs && createdMs <= endMs) {
            all.push(lead);
          }
        }

        hasMore = Boolean(data.has_more);
        offset += PAGE_SIZE;
      }

      if (hasMore) {
        setInfo(`Preview capped at ${MAX_LEADS_SCAN} scanned leads. Narrow period if needed.`);
      }

      setPreviewLeads(all);
      if (!all.length) {
        setInfo("No leads found in this period.");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load leads preview");
    } finally {
      setLoadingPreview(false);
    }
  }

  const preparedPayload = {
    rep_id: repId,
    period_start: startAt,
    period_end: endAt,
    lead_ids: previewLeads.map((l) => l.id),
  };

  return (
    <div style={{ padding: "20px 24px", fontFamily: "inherit", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Assign Leads By Period</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Pick a time period and a sales rep. This screen prepares everything except the actual assign call.
      </p>

      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", marginBottom: 14, background: "#fff", border: "1px solid #dddbda", borderRadius: 4, padding: 16, boxShadow: "0 1px 2px rgba(0,0,0,.06)" }}>
        <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
          Start
          <input
            type="datetime-local"
            value={startAt}
            onChange={(e) => setStartAt(e.target.value)}
            style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
          />
        </label>

        <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
          End
          <input
            type="datetime-local"
            value={endAt}
            onChange={(e) => setEndAt(e.target.value)}
            style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
          />
        </label>

        <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
          Sales Rep
          <select
            value={repId}
            onChange={(e) => setRepId(e.target.value)}
            style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
            disabled={loadingReps}
          >
            <option value="">Select rep...</option>
            {reps.map((rep) => (
              <option key={rep.id} value={rep.id}>
                {rep.name} ({rep.email})
              </option>
            ))}
          </select>
        </label>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <button
          onClick={loadPreview}
          disabled={loadingPreview}
          style={{ border: "none", background: loadingPreview ? "#5a9fd4" : "#0176d3", color: "#fff", borderRadius: 4, padding: "8px 16px", fontWeight: 600 }}
        >
          {loadingPreview ? "Loading Preview..." : "Load Leads In Period"}
        </button>
        <button
          onClick={() => { setPreviewLeads([]); setInfo(""); setError(""); }}
          style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "8px 14px", color: "#3e3e3c" }}
        >
          Clear
        </button>
      </div>

      {error ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{error}</p> : null}
      {info ? <p style={{ marginBottom: 10, color: "#2e844a", fontSize: 13 }}>{info}</p> : null}

      <div style={{ marginBottom: 14, border: "1px solid #dddbda", borderRadius: 4, padding: 14, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)" }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#3e3e3c" }}>Prepared Assignment</h2>
        <div style={{ fontSize: 13, color: "#3e3e3c", display: "grid", gap: 4 }}>
          <div>Rep: {selectedRep ? `${selectedRep.name} (${selectedRep.email})` : "Not selected"}</div>
          <div>Period: {startAt || "-"} to {endAt || "-"}</div>
          <div>Leads matched: {previewLeads.length}</div>
          <div>API execution: pending (waiting for your endpoint contract)</div>
        </div>
      </div>

      {previewLeads.length > 0 ? (
        <div style={{ border: "1px solid #dddbda", borderRadius: 4, overflow: "auto", background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 780 }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <th style={th}>Lead</th>
                <th style={th}>Company</th>
                <th style={th}>Created</th>
                <th style={th}>Lead ID</th>
              </tr>
            </thead>
            <tbody>
              {previewLeads.slice(0, 300).map((lead) => (
                <tr key={lead.id} style={{ borderTop: "1px solid #e5e7eb" }}>
                  <td style={td}>{lead.full_name || ""}</td>
                  <td style={td}>{lead.company_name || ""}</td>
                  <td style={td}>{prettyDate(lead.created_time)}</td>
                  <td style={td}>{lead.id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <details style={{ marginTop: 14 }}>
        <summary style={{ cursor: "pointer", color: "#2563eb" }}>Show payload preview</summary>
        <pre style={{ marginTop: 10, background: "#0f172a", color: "#e2e8f0", padding: 12, borderRadius: 8, overflow: "auto" }}>
{JSON.stringify(preparedPayload, null, 2)}
        </pre>
      </details>
    </div>
  );
}

const th: React.CSSProperties = {
  padding: "9px 12px",
  textAlign: "left",
  fontSize: 11,
  fontWeight: 700,
  color: "#3e3e3c",
  borderBottom: "2px solid #dddbda",
  whiteSpace: "nowrap",
  background: "#f3f2f2",
  textTransform: "uppercase",
  letterSpacing: "0.04em",
};

const td: React.CSSProperties = {
  padding: "10px 12px",
  fontSize: 14,
  color: "#111827",
  verticalAlign: "top",
};
