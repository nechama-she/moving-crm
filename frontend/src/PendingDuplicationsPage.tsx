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
  is_sample?: boolean;
};

type CompanyOption = {
  id: string;
  name: string;
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
  const [running, setRunning] = useState("");
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [runItem, setRunItem] = useState<PendingDuplication | null>(null);
  const [runCompanyId, setRunCompanyId] = useState("");
  const [runReferralSource, setRunReferralSource] = useState("");
  const [runError, setRunError] = useState("");
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);

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

  useEffect(() => {
    fetch(`${API_BASE}/api/companies/mine`, { headers: authHeaders(token) })
      .then(async (response) => {
        if (!response.ok) throw new Error(await responseError(response));
        return response.json();
      })
      .then((rows: Array<Record<string, unknown>>) => {
        setCompanies((Array.isArray(rows) ? rows : []).map((row) => ({
          id: String(row.id || ""),
          name: String(row.name || ""),
        })).filter((company) => company.id && company.name));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load companies"));
  }, [token]);

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

  function openDuplicateNow(item: PendingDuplication) {
    const matchingCompany = companies.find((company) => company.name === item.target_company_name);
    setRunItem(item);
    setRunCompanyId(matchingCompany?.id || "");
    setRunReferralSource(item.target_referral_source || "");
    setRunError("");
    setRunResult(null);
    setError("");
  }

  async function duplicateNow() {
    if (!runItem || !runCompanyId || !runReferralSource.trim()) return;
    setRunning(runItem.schedule_name);
    setRunError("");
    setRunResult(null);
    setError("");
    try {
      const response = await fetch(
        `${API_BASE}/api/lead-duplications/pending/${encodeURIComponent(runItem.schedule_name)}/run-now`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders(token) },
          body: JSON.stringify({ company_id: runCompanyId, referral_source: runReferralSource.trim() }),
        },
      );
      if (!response.ok) throw new Error(await responseError(response));
      const responseBody = await response.json();
      setItems((current) => current.filter((row) => row.schedule_name !== runItem.schedule_name));
      setRunResult((responseBody?.result || {}) as Record<string, unknown>);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "Could not complete duplication");
    } finally {
      setRunning("");
    }
  }

  if (user?.role !== "admin") {
    return <div style={page}><p style={errorBox}>Admin access is required.</p></div>;
  }

  return (
    <div className="pending-dup-page" style={page}>
      {runItem ? (
        <div className="pending-dup-modal-backdrop" style={modalBackdrop} role="presentation" onClick={() => !running && setRunItem(null)}>
          <section className="pending-dup-modal" style={modal} role="dialog" aria-modal="true" aria-labelledby="duplicate-now-title" onClick={(event) => event.stopPropagation()}>
            <header style={modalHeader}>
              <div>
                <h2 id="duplicate-now-title" style={{ margin: 0, color: "#032d60", fontSize: 18 }}>Duplicate Now</h2>
                <p style={{ margin: "3px 0 0", color: "#706e6b", fontSize: 12 }}>{runItem.lead_name || runItem.lead_id}</p>
              </div>
              <button type="button" aria-label="Close" disabled={Boolean(running)} onClick={() => setRunItem(null)} style={closeButton}>×</button>
            </header>
            <div style={modalBody}>
              <label style={fieldLabel}>
                Company
                <select value={runCompanyId} onChange={(event) => setRunCompanyId(event.target.value)} style={fieldInput} autoFocus>
                  <option value="">Select a company</option>
                  {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
                </select>
              </label>
              <label style={fieldLabel}>
                Referral Source
                <input value={runReferralSource} onChange={(event) => setRunReferralSource(event.target.value)} placeholder="Facebook-Company-HHG" style={fieldInput} />
              </label>
              <p style={{ margin: 0, color: "#706e6b", fontSize: 11 }}>This starts the duplication immediately and removes its pending schedule.</p>
              {runError ? <div style={modalError}><strong>Duplication failed</strong><span>{runError}</span></div> : null}
              {runResult ? (
                <div style={modalSuccess}>
                  <strong>Duplication completed</strong>
                  <span>SmartMoving and Moving CRM returned successfully.</span>
                  <details>
                    <summary>View complete responses</summary>
                    <pre style={{ maxHeight: 220, overflow: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(runResult, null, 2)}</pre>
                  </details>
                </div>
              ) : null}
              {runItem.is_sample ? <div style={demoNotice}>Dev preview only — this sample cannot create or delete anything.</div> : null}
            </div>
            <footer className="pending-dup-modal-footer" style={modalFooter}>
              <button type="button" disabled={Boolean(running)} onClick={() => setRunItem(null)} style={secondaryButton}>{runResult ? "Close" : "Cancel"}</button>
              {!runResult ? (
                <button type="button" disabled={runItem.is_sample || Boolean(running) || !runCompanyId || !runReferralSource.trim()} onClick={() => void duplicateNow()} style={primaryButton}>
                  {runItem.is_sample ? "Preview Only" : running ? "Waiting for responses..." : "Duplicate Now"}
                </button>
              ) : null}
            </footer>
          </section>
        </div>
      ) : null}
      <div className="pending-dup-header" style={headerRow}>
        <div>
          <h1 style={title}>Pending Lead Duplications</h1>
          <p style={subtitle}>Leads waiting for their scheduled copy to another company.</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading} style={secondaryButton}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error ? <div style={errorBox}>{error}</div> : null}

      <section className="pending-dup-card" style={card}>
        <div className="pending-dup-card-header" style={cardHeader}>
          <strong>
            {items.filter((item) => !item.is_sample).length} pending
            {items.some((item) => item.is_sample) ? " · 1 dev preview" : ""}
          </strong>
          <span style={{ color: "#706e6b", fontSize: 12 }}>Schedules disappear automatically after they run.</span>
        </div>

        {loading && items.length === 0 ? (
          <p style={emptyState}>Loading pending duplications…</p>
        ) : items.length === 0 ? (
          <p style={emptyState}>No leads are waiting for duplication.</p>
        ) : (
          <div className="pending-dup-table-wrap" style={{ overflowX: "auto" }}>
            <table className="pending-dup-table" style={table}>
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
                      ) : <strong>{item.lead_name || "Unknown lead"}</strong>}
                      {item.is_sample ? <span style={demoBadge}>DEV SAMPLE</span> : null}
                      {item.lead_id ? (
                        <div style={idText}>
                          <Link to={`/leads/${item.lead_id}`} style={idLink}>
                            {item.lead_id}
                          </Link>
                        </div>
                      ) : null}
                    </td>
                    <td style={td}>
                      {item.smartmoving_id && !item.is_sample ? (
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
                    <td className="pending-dup-actions" style={{ ...td, textAlign: "right" }}>
                      <button
                        type="button"
                        onClick={() => openDuplicateNow(item)}
                        disabled={running === item.schedule_name || deleting === item.schedule_name}
                        style={{ ...primaryButton, marginRight: 6 }}
                      >
                        {running === item.schedule_name ? "Starting..." : "Duplicate Now"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void deleteSchedule(item)}
                        disabled={item.is_sample || deleting === item.schedule_name || running === item.schedule_name}
                        title={item.is_sample ? "Dev preview rows cannot be deleted" : "Delete pending duplication"}
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
const primaryButton: React.CSSProperties = {
  padding: "6px 10px",
  border: "1px solid #0176d3",
  borderRadius: 4,
  background: "#0176d3",
  color: "#fff",
  fontWeight: 700,
  cursor: "pointer",
};
const demoBadge: React.CSSProperties = { display: "inline-block", marginTop: 5, marginLeft: 6, padding: "2px 6px", borderRadius: 999, background: "#fff1d6", color: "#8c4b02", fontSize: 9, fontWeight: 800, letterSpacing: ".04em" };
const demoNotice: React.CSSProperties = { padding: "9px 10px", border: "1px solid #fe9339", borderRadius: 4, background: "#fff7ed", color: "#8c4b02", fontSize: 11, fontWeight: 700 };
const modalError: React.CSSProperties = { padding: "10px 11px", display: "grid", gap: 4, border: "1px solid #ea001e", borderRadius: 4, background: "#fef1ee", color: "#ba0517", fontSize: 11, overflowWrap: "anywhere" };
const modalSuccess: React.CSSProperties = { padding: "10px 11px", display: "grid", gap: 4, border: "1px solid #2e844a", borderRadius: 4, background: "#f3fdf6", color: "#194e31", fontSize: 11 };
const modalBackdrop: React.CSSProperties = { position: "fixed", inset: 0, zIndex: 100, padding: 16, display: "grid", placeItems: "center", background: "rgba(8, 21, 38, .52)" };
const modal: React.CSSProperties = { width: "min(500px, 100%)", overflow: "hidden", border: "1px solid #dddbda", borderRadius: 8, background: "#fff", boxShadow: "0 14px 45px rgba(0,0,0,.25)" };
const modalHeader: React.CSSProperties = { padding: "14px 16px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, borderBottom: "1px solid #dddbda", background: "#f3f3f3" };
const closeButton: React.CSSProperties = { border: 0, background: "transparent", color: "#706e6b", fontSize: 24, cursor: "pointer" };
const modalBody: React.CSSProperties = { padding: 16, display: "grid", gap: 14 };
const fieldLabel: React.CSSProperties = { display: "grid", gap: 5, color: "#3e3e3c", fontSize: 12, fontWeight: 700 };
const fieldInput: React.CSSProperties = { width: "100%", height: 40, boxSizing: "border-box", border: "1px solid #c9c7c5", borderRadius: 4, padding: "0 10px", background: "#fff", color: "#181818", font: "inherit" };
const modalFooter: React.CSSProperties = { padding: "12px 16px", display: "flex", justifyContent: "flex-end", gap: 8, borderTop: "1px solid #dddbda", background: "#fafaf9" };
