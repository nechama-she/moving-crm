import { useEffect, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Rep = {
  id: string;
  name: string;
  email: string;
  role: string;
  phone?: string;
};

type AdminUnavailabilityWindow = {
  id: string;
  admin_user_id: string;
  start_at: string;
  end_at: string;
  reason?: string;
  available_rep_ids?: string[];
  available_reps?: Array<{
    id: string;
    name: string;
    email: string;
    phone?: string;
  }>;
};

type RepSlot = {
  id?: string;
  start: string;
  end: string;
};

type RepAvailabilityWindow = {
  id: string;
  rep_user_id: string;
  start_at: string;
  end_at: string;
  reason?: string;
};

type ReferralRule = {
  id: string;
  company_id: string;
  referral_source: string;
  rep_assignments: ReferralRepAssignment[];
  active: boolean;
};

type ReferralRepAssignment = {
  rep_user_id: string;
  schedule: "always" | "scheduled";
  start_date?: string;
  end_date?: string;
};

type ReferralRuleData = {
  rules: ReferralRule[];
  companies: Array<{ id: string; name: string }>;
  reps: Array<{ id: string; name: string; email: string; company_ids: string[] }>;
  referral_sources: Record<string, string[]>;
};

function ReferralAssignmentRulesPanel() {
  const { token } = useAuth();
  const [data, setData] = useState<ReferralRuleData>({ rules: [], companies: [], reps: [], referral_sources: {} });
  const [companyId, setCompanyId] = useState("");
  const [referralSource, setReferralSource] = useState("");
  const [manualReferralSource, setManualReferralSource] = useState(false);
  const [repAssignments, setRepAssignments] = useState<Record<string, ReferralRepAssignment>>({});
  const [active, setActive] = useState(true);
  const [editingId, setEditingId] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/referral-assignment-rules`, { headers: authHeaders(token) })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<ReferralRuleData>;
      })
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load assignment rules"));
  }, [token]);

  function resetForm() {
    setCompanyId("");
    setReferralSource("");
    setManualReferralSource(false);
    setRepAssignments({});
    setActive(true);
    setEditingId("");
  }

  async function saveRule() {
    setError("");
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/api/referral-assignment-rules${editingId ? `/${editingId}` : ""}`, {
        method: editingId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ company_id: companyId, referral_source: referralSource, rep_assignments: Object.values(repAssignments), active }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setData((await res.json()) as ReferralRuleData);
      resetForm();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save assignment rule");
    } finally {
      setSaving(false);
    }
  }

  async function deleteRule(ruleId: string) {
    if (!window.confirm("Delete this referral source assignment rule?")) return;
    setError("");
    const res = await fetch(`${API_BASE}/api/referral-assignment-rules/${ruleId}`, {
      method: "DELETE",
      headers: authHeaders(token),
    });
    if (!res.ok) {
      setError(`HTTP ${res.status}`);
      return;
    }
    setData((await res.json()) as ReferralRuleData);
    if (editingId === ruleId) resetForm();
  }

  function editRule(rule: ReferralRule) {
    setCompanyId(rule.company_id);
    setReferralSource(rule.referral_source);
    setManualReferralSource(false);
    setRepAssignments(Object.fromEntries((rule.rep_assignments || []).map((assignment) => [assignment.rep_user_id, assignment])));
    setActive(rule.active);
    setEditingId(rule.id);
    setError("");
  }

  const companyName = new Map(data.companies.map((company) => [company.id, company.name]));
  const repName = new Map(data.reps.map((rep) => [rep.id, rep.name]));
  const eligibleReps = data.reps.filter((rep) => rep.company_ids.includes(companyId));
  const saveDisabled = saving || !companyId || !referralSource.trim() || Object.keys(repAssignments).length === 0;

  function toggleRep(repId: string) {
    setRepAssignments((current) => {
      if (current[repId]) {
        const next = { ...current };
        delete next[repId];
        return next;
      }
      return { ...current, [repId]: { rep_user_id: repId, schedule: "always" } };
    });
  }

  function updateRepSchedule(repId: string, patch: Partial<ReferralRepAssignment>) {
    setRepAssignments((current) => ({
      ...current,
      [repId]: { ...(current[repId] || { rep_user_id: repId, schedule: "always" }), ...patch },
    }));
  }

  return (
    <section style={{ marginBottom: 22 }}>
      <div style={referralSectionHeader}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, color: "#032d60" }}>Referral Source Assignment</h2>
          <p style={{ margin: "5px 0 0", color: "#706e6b", fontSize: 13 }}>Route leads to the right sales reps based on company and Referral Source.</p>
        </div>
        <span style={referralCountBadge}>{data.rules.length} {data.rules.length === 1 ? "rule" : "rules"}</span>
      </div>

      <div style={referralCard}>
        <h3 style={referralCardTitle}>{editingId ? "Edit Assignment Rule" : "New Assignment Rule"}</h3>
        <div style={referralFormGrid}>
          <label style={referralLabel}>
            Company
            <select style={referralInput} value={companyId} onChange={(event) => { setCompanyId(event.target.value); setReferralSource(""); setManualReferralSource(false); setRepAssignments({}); }}>
              <option value="">Select company</option>
              {data.companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
          </label>
          <label style={referralLabel}>
            Referral Source
            {!manualReferralSource ? (
              <select
                style={referralInput}
                value={referralSource}
                disabled={!companyId}
                onChange={(event) => {
                  if (event.target.value === "__manual__") {
                    setReferralSource("");
                    setManualReferralSource(true);
                  } else {
                    setReferralSource(event.target.value);
                  }
                }}
              >
                <option value="">Select Referral Source</option>
                {(data.referral_sources[companyId] || []).map((source) => <option key={source} value={source}>{source}</option>)}
                <option value="__manual__">Enter a new Referral Source...</option>
              </select>
            ) : (
              <div style={{ display: "flex", gap: 7 }}>
                <input autoFocus style={referralInput} value={referralSource} onChange={(event) => setReferralSource(event.target.value)} placeholder="Enter Referral Source" />
                <button type="button" style={referralSecondaryButton} onClick={() => { setReferralSource(""); setManualReferralSource(false); }}>Choose existing</button>
              </div>
            )}
          </label>
        </div>

        <fieldset style={referralRepFieldset}>
          <legend style={referralLegend}>Assign to reps</legend>
          {!companyId ? <div style={referralEmptyHint}>Select a company to see its sales reps.</div> : null}
          {companyId && eligibleReps.length === 0 ? <div style={referralEmptyHint}>No sales reps are assigned to this company.</div> : null}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(330px, 1fr))", gap: 10 }}>
            {eligibleReps.map((rep) => {
              const assignment = repAssignments[rep.id];
              const selected = Boolean(assignment);
              return (
                <div key={rep.id} style={{ ...referralRepOption, ...(selected ? referralRepOptionSelected : {}), display: "block" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer" }}>
                    <input type="checkbox" checked={selected} onChange={() => toggleRep(rep.id)} />
                    <span><strong style={{ display: "block", color: "#181818" }}>{rep.name}</strong><span style={{ color: "#706e6b", fontSize: 11 }}>{rep.email}</span></span>
                  </label>
                  {selected ? (
                    <div style={{ borderTop: "1px solid #d8e6f5", marginTop: 9, paddingTop: 9 }}>
                      <label style={{ ...referralLabel, fontSize: 12 }}>
                        Availability
                        <select style={{ ...referralInput, minHeight: 34 }} value={assignment.schedule} onChange={(event) => updateRepSchedule(rep.id, { schedule: event.target.value as "always" | "scheduled" })}>
                          <option value="always">Always</option>
                          <option value="scheduled">Specific dates</option>
                        </select>
                      </label>
                      {assignment.schedule === "scheduled" ? (
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 9 }}>
                          <label style={{ ...referralLabel, fontSize: 11 }}>Start date<input type="date" style={referralInput} value={assignment.start_date || ""} onChange={(event) => updateRepSchedule(rep.id, { start_date: event.target.value })} /></label>
                          <label style={{ ...referralLabel, fontSize: 11 }}>End date<input type="date" style={referralInput} value={assignment.end_date || ""} onChange={(event) => updateRepSchedule(rep.id, { end_date: event.target.value })} /></label>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </fieldset>

        <label style={{ display: "inline-flex", alignItems: "center", gap: 7, marginTop: 13, fontSize: 13, fontWeight: 600, color: "#181818" }}>
          <input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} /> Rule enabled
        </label>
        {error ? <div style={referralErrorBox}>{error}</div> : null}
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button type="button" onClick={saveRule} disabled={saveDisabled} style={{ ...referralPrimaryButton, opacity: saveDisabled ? 0.55 : 1, cursor: saveDisabled ? "not-allowed" : "pointer" }}>{saving ? "Saving..." : editingId ? "Save Changes" : "Add Rule"}</button>
          {editingId ? <button type="button" onClick={resetForm} style={referralSecondaryButton}>Cancel</button> : null}
        </div>
      </div>

      <div style={referralCard}>
        <h3 style={referralCardTitle}>Configured Rules</h3>
        <div style={{ overflowX: "auto" }}>
          <table style={referralTable}>
            <thead><tr><th style={referralTh}>Company</th><th style={referralTh}>Referral Source</th><th style={referralTh}>Assigned Reps</th><th style={referralTh}>Status</th><th style={referralTh}>Actions</th></tr></thead>
            <tbody>
              {data.rules.map((rule) => (
                <tr key={rule.id} style={{ opacity: rule.active ? 1 : 0.62 }}>
                  <td style={referralTd}>{companyName.get(rule.company_id) || rule.company_id}</td>
                  <td style={referralTd}><strong>{rule.referral_source}</strong></td>
                  <td style={referralTd}><div style={{ display: "grid", gap: 5 }}>{rule.rep_assignments.map((assignment) => <div key={assignment.rep_user_id}><span style={referralRepBadge}>{repName.get(assignment.rep_user_id) || assignment.rep_user_id}</span><span style={{ marginLeft: 7, color: "#706e6b", fontSize: 12 }}>{assignment.schedule === "always" ? "Always" : `${assignment.start_date} – ${assignment.end_date}`}</span></div>)}</div></td>
                  <td style={referralTd}><span style={{ ...referralStatusBadge, ...(rule.active ? referralStatusEnabled : referralStatusDisabled) }}>{rule.active ? "Enabled" : "Disabled"}</span></td>
                  <td style={{ ...referralTd, whiteSpace: "nowrap" }}><button type="button" onClick={() => editRule(rule)} style={referralLinkButton}>Edit</button><button type="button" onClick={() => deleteRule(rule.id)} style={{ ...referralLinkButton, color: "#ba0517" }}>Delete</button></td>
                </tr>
              ))}
              {data.rules.length === 0 ? <tr><td colSpan={5} style={{ ...referralTd, padding: 30, textAlign: "center", color: "#706e6b" }}>No assignment rules configured.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

const referralSectionHeader: React.CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 12 };
const referralCountBadge: React.CSSProperties = { borderRadius: 14, background: "#eef4ff", color: "#014486", padding: "4px 10px", fontSize: 12, fontWeight: 700, whiteSpace: "nowrap" };
const referralCard: React.CSSProperties = { background: "#fff", border: "1px solid #dddbda", borderRadius: 6, padding: 18, marginBottom: 14, boxShadow: "0 1px 2px rgba(0,0,0,.04)" };
const referralCardTitle: React.CSSProperties = { color: "#032d60", fontSize: 15, margin: "0 0 14px" };
const referralFormGrid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 };
const referralLabel: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 6, color: "#181818", fontSize: 13, fontWeight: 600 };
const referralInput: React.CSSProperties = { width: "100%", minHeight: 38, border: "1px solid #c9c7c5", borderRadius: 4, padding: "7px 10px", boxSizing: "border-box", background: "#fff", color: "#181818" };
const referralRepFieldset: React.CSSProperties = { border: "1px solid #dddbda", borderRadius: 5, padding: 12, margin: "15px 0 0", minWidth: 0 };
const referralLegend: React.CSSProperties = { padding: "0 5px", color: "#3e3e3c", fontSize: 12, fontWeight: 700 };
const referralEmptyHint: React.CSSProperties = { padding: "8px 2px", color: "#706e6b", fontSize: 13 };
const referralRepOption: React.CSSProperties = { display: "flex", alignItems: "center", gap: 9, minWidth: 0, border: "1px solid #dddbda", borderRadius: 5, padding: "9px 10px", background: "#fff", cursor: "pointer", fontSize: 13 };
const referralRepOptionSelected: React.CSSProperties = { borderColor: "#0176d3", background: "#eef4ff", boxShadow: "inset 0 0 0 1px #0176d3" };
const referralPrimaryButton: React.CSSProperties = { border: 0, borderRadius: 4, padding: "9px 16px", background: "#0176d3", color: "#fff", fontWeight: 700 };
const referralSecondaryButton: React.CSSProperties = { border: "1px solid #0176d3", borderRadius: 4, padding: "8px 16px", background: "#fff", color: "#0176d3", fontWeight: 700, cursor: "pointer" };
const referralErrorBox: React.CSSProperties = { background: "#fef1ee", border: "1px solid #ea001e", borderRadius: 4, color: "#ba0517", padding: 10, marginTop: 13, fontSize: 13 };
const referralTable: React.CSSProperties = { width: "100%", minWidth: 760, borderCollapse: "collapse", fontSize: 13 };
const referralTh: React.CSSProperties = { textAlign: "left", color: "#3e3e3c", padding: "10px 9px", borderBottom: "1px solid #c9c7c5", background: "#f3f3f3", fontSize: 12, textTransform: "uppercase", letterSpacing: ".025em" };
const referralTd: React.CSSProperties = { padding: "11px 9px", borderBottom: "1px solid #e5e5e5", verticalAlign: "middle", color: "#181818" };
const referralRepBadge: React.CSSProperties = { display: "inline-flex", borderRadius: 12, border: "1px solid #c9c7c5", padding: "3px 8px", background: "#fff", color: "#3e3e3c", fontSize: 12 };
const referralStatusBadge: React.CSSProperties = { display: "inline-flex", alignItems: "center", borderRadius: 12, padding: "3px 9px", fontSize: 12, fontWeight: 700 };
const referralStatusEnabled: React.CSSProperties = { color: "#2e844a", background: "#ecf7ee", border: "1px solid #91db8b" };
const referralStatusDisabled: React.CSSProperties = { color: "#706e6b", background: "#f3f3f3", border: "1px solid #c9c7c5" };
const referralLinkButton: React.CSSProperties = { border: 0, background: "transparent", color: "#0176d3", cursor: "pointer", padding: "4px 10px 4px 0", fontWeight: 700 };

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

function toLocalInputValue(value: string | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function PeriodAssignPage() {
  const { token } = useAuth();
  const [nowMs, setNowMs] = useState<number>(Date.now());
  const [reps, setReps] = useState<Rep[]>([]);
  const [admins, setAdmins] = useState<Rep[]>([]);
  const [loadingReps, setLoadingReps] = useState(true);
  const [loadingWindows, setLoadingWindows] = useState(false);
  const [savingWindow, setSavingWindow] = useState(false);
  const [windowError, setWindowError] = useState("");
  const [windowInfo, setWindowInfo] = useState("");
  const [adminId, setAdminId] = useState("");
  const [unavailableStart, setUnavailableStart] = useState("");
  const [unavailableEnd, setUnavailableEnd] = useState("");
  const [unavailableReason, setUnavailableReason] = useState("");
  const [selectedRepIds, setSelectedRepIds] = useState<string[]>([]);
  const [repSlotsByRep, setRepSlotsByRep] = useState<Record<string, RepSlot[]>>({});
  const [windows, setWindows] = useState<AdminUnavailabilityWindow[]>([]);
  const [repWindows, setRepWindows] = useState<RepAvailabilityWindow[]>([]);
  const [editingWindowId, setEditingWindowId] = useState("");
  const [editStart, setEditStart] = useState("");
  const [editEnd, setEditEnd] = useState("");
  const [editReason, setEditReason] = useState("");
  const [editSelectedRepIds, setEditSelectedRepIds] = useState<string[]>([]);
  const [editRepSlotsByRep, setEditRepSlotsByRep] = useState<Record<string, RepSlot[]>>({});

  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);

  function defaultSlot(start: string, end: string): RepSlot {
    return { start: start || "", end: end || "" };
  }

  useEffect(() => {
    setLoadingReps(true);
    fetch(`${API_BASE}/api/users`, { headers: authHeaders(token) })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((rows: Rep[]) => {
        const salesReps = (rows || []).filter((u) => u.role === "sales_rep");
        const adminUsers = (rows || []).filter((u) => u.role === "admin");
        setReps(salesReps);
        setAdmins(adminUsers);
        if (!adminId && adminUsers.length) {
          setAdminId(adminUsers[0].id);
        }
      })
      .catch((err: unknown) => setWindowError(err instanceof Error ? err.message : "Failed to load users"))
      .finally(() => setLoadingReps(false));
  }, [token, adminId]);

  useEffect(() => {
    if (!adminId) return;
    loadAllWindows(adminId);
  }, [adminId]);

  async function loadAdminWindows(targetAdminId: string) {
    setLoadingWindows(true);
    setWindowError("");
    try {
      const params = new URLSearchParams({ admin_id: targetAdminId });
      const res = await fetch(`${API_BASE}/api/users/admin-unavailability?${params.toString()}`, {
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as AdminUnavailabilityWindow[];
      setWindows(data || []);
    } catch (err: unknown) {
      setWindowError(err instanceof Error ? err.message : "Failed to load admin unavailable windows");
    } finally {
      setLoadingWindows(false);
    }
  }

  async function loadRepWindows() {
    const res = await fetch(`${API_BASE}/api/users/rep-availability`, {
      headers: authHeaders(token),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as RepAvailabilityWindow[];
    setRepWindows(data || []);
  }

  async function loadAllWindows(targetAdminId: string) {
    await Promise.all([loadAdminWindows(targetAdminId), loadRepWindows()]);
  }

  function toggleSelectedRep(repId: string) {
    setSelectedRepIds((prev) => {
      if (prev.includes(repId)) {
        return prev.filter((id) => id !== repId);
      }
      return [...prev, repId];
    });
    setRepSlotsByRep((prev) => {
      if (prev[repId]) return prev;
      return {
        ...prev,
        [repId]: [defaultSlot(unavailableStart, unavailableEnd)],
      };
    });
  }

  function addRepSlot(repId: string) {
    setRepSlotsByRep((prev) => {
      const existing = prev[repId] || [defaultSlot(unavailableStart, unavailableEnd)];
      return {
        ...prev,
        [repId]: [...existing, defaultSlot(unavailableStart, unavailableEnd)],
      };
    });
  }

  function removeRepSlot(repId: string, slotIndex: number) {
    setRepSlotsByRep((prev) => {
      const existing = prev[repId] || [];
      if (existing.length <= 1) {
        const nextState = { ...prev };
        delete nextState[repId];
        setSelectedRepIds((ids) => ids.filter((id) => id !== repId));
        return nextState;
      }
      const next = existing.filter((_, idx) => idx !== slotIndex);
      return { ...prev, [repId]: next };
    });
  }

  function updateRepSlot(repId: string, slotIndex: number, patch: Partial<RepSlot>) {
    setRepSlotsByRep((prev) => {
      const existing = prev[repId] || [defaultSlot(unavailableStart, unavailableEnd)];
      const next = existing.map((slot, idx) => (idx === slotIndex ? { ...slot, ...patch } : slot));
      return { ...prev, [repId]: next };
    });
  }

  function addEditRepSlot(repId: string) {
    setEditRepSlotsByRep((prev) => {
      const existing = prev[repId] || [defaultSlot(editStart, editEnd)];
      return {
        ...prev,
        [repId]: [...existing, defaultSlot(editStart, editEnd)],
      };
    });
  }

  function removeEditRepSlot(repId: string, slotIndex: number) {
    setEditRepSlotsByRep((prev) => {
      const existing = prev[repId] || [];
      if (existing.length <= 1) {
        const nextState = { ...prev };
        delete nextState[repId];
        setEditSelectedRepIds((ids) => ids.filter((id) => id !== repId));
        return nextState;
      }
      const next = existing.filter((_, idx) => idx !== slotIndex);
      return { ...prev, [repId]: next };
    });
  }

  function updateEditRepSlot(repId: string, slotIndex: number, patch: Partial<RepSlot>) {
    setEditRepSlotsByRep((prev) => {
      const existing = prev[repId] || [defaultSlot(editStart, editEnd)];
      const next = existing.map((slot, idx) => (idx === slotIndex ? { ...slot, ...patch } : slot));
      return { ...prev, [repId]: next };
    });
  }

  function toggleEditSelectedRep(repId: string) {
    setEditSelectedRepIds((prev) => {
      if (prev.includes(repId)) return prev.filter((id) => id !== repId);
      return [...prev, repId];
    });
    setEditRepSlotsByRep((prev) => {
      if (prev[repId]) return prev;
      return {
        ...prev,
        [repId]: [defaultSlot(editStart, editEnd)],
      };
    });
  }

  function overlaps(aStart: string, aEnd: string, bStart: string, bEnd: string): boolean {
    const a1 = toMs(aStart);
    const a2 = toMs(aEnd);
    const b1 = toMs(bStart);
    const b2 = toMs(bEnd);
    if (!a1 || !a2 || !b1 || !b2) return false;
    return a1 < b2 && b1 < a2;
  }

  function isActiveNow(start: string | undefined, end: string | undefined): boolean {
    const s = toMs(start);
    const e = toMs(end);
    if (!s || !e) return false;
    return s <= nowMs && nowMs < e;
  }

  function getRepWindowsForAdminWindow(window: AdminUnavailabilityWindow, repId: string): RepAvailabilityWindow[] {
    const token = `[admin_window:${window.id}]`;
    const tokenMatches = repWindows.filter((rw) => rw.rep_user_id === repId && (rw.reason || "").includes(token));
    if (tokenMatches.length > 0) {
      return tokenMatches.sort((a, b) => toMs(a.start_at) - toMs(b.start_at));
    }
    const legacyMatches = repWindows.filter(
      (rw) =>
        rw.rep_user_id === repId &&
        overlaps(rw.start_at, rw.end_at, window.start_at, window.end_at) &&
        (rw.reason || "").toLowerCase().includes("linked to admin unavailability"),
    );
    return legacyMatches.sort((a, b) => toMs(a.start_at) - toMs(b.start_at));
  }

  function startEditWindow(window: AdminUnavailabilityWindow) {
    const selected = window.available_rep_ids || [];
    const nextSlotsByRep: Record<string, RepSlot[]> = {};
    selected.forEach((repId) => {
      const linked = getRepWindowsForAdminWindow(window, repId);
      nextSlotsByRep[repId] = linked.length
        ? linked.map((slot) => ({ id: slot.id, start: toLocalInputValue(slot.start_at), end: toLocalInputValue(slot.end_at) }))
        : [defaultSlot(toLocalInputValue(window.start_at), toLocalInputValue(window.end_at))];
    });
    setEditingWindowId(window.id);
    setEditStart(toLocalInputValue(window.start_at));
    setEditEnd(toLocalInputValue(window.end_at));
    setEditReason(window.reason || "");
    setEditSelectedRepIds(selected);
    setEditRepSlotsByRep(nextSlotsByRep);
    setWindowError("");
    setWindowInfo("");
  }

  async function saveWindowUpdate(window: AdminUnavailabilityWindow) {
    setWindowError("");
    setWindowInfo("");

    const startMs = toMs(editStart);
    const endMs = toMs(editEnd);
    if (!startMs || !endMs || endMs <= startMs) {
      setWindowError("End must be after start.");
      return;
    }

    setSavingWindow(true);
    try {
      const adminRes = await fetch(`${API_BASE}/api/users/admin-unavailability/${window.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          start_at: new Date(editStart).toISOString(),
          end_at: new Date(editEnd).toISOString(),
          reason: editReason,
          rep_user_ids: editSelectedRepIds,
        }),
      });
      if (!adminRes.ok) {
        const err = await adminRes.json().catch(() => ({ detail: "Failed to update window" }));
        throw new Error(err.detail || "Failed to update window");
      }

      const windowToken = `[admin_window:${window.id}]`;
      const syncTasks = reps.map(async (rep) => {
        const repId = rep.id;
        const existing = getRepWindowsForAdminWindow(window, repId);

        for (const slot of existing) {
          const delRes = await fetch(`${API_BASE}/api/users/rep-availability/${slot.id}`, {
            method: "DELETE",
            headers: authHeaders(token),
          });
          if (!delRes.ok) throw new Error("Failed to sync rep slots");
        }

        if (!editSelectedRepIds.includes(repId)) return;

        const sourceSlots = editRepSlotsByRep[repId] || [defaultSlot(editStart, editEnd)];
        const validSlots = sourceSlots.filter((slot) => {
          const s = toMs(slot.start);
          const e = toMs(slot.end);
          return Boolean(s && e && e > s);
        });

        for (const slot of validSlots) {
          const createRes = await fetch(`${API_BASE}/api/users/rep-availability`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders(token) },
            body: JSON.stringify({
              rep_user_id: repId,
              start_at: new Date(slot.start).toISOString(),
              end_at: new Date(slot.end).toISOString(),
              reason: `${windowToken} Linked to admin unavailability (${new Date(editStart).toLocaleString()} - ${new Date(editEnd).toLocaleString()})`,
            }),
          });
          if (!createRes.ok) throw new Error("Failed to sync rep slots");
        }
      });

      await Promise.all(syncTasks);
      setEditingWindowId("");
      setWindowInfo("Admin slot and rep slots updated.");
      await loadAllWindows(adminId);
    } catch (err: unknown) {
      setWindowError(err instanceof Error ? err.message : "Failed to update window");
    } finally {
      setSavingWindow(false);
    }
  }

  async function createAdminWindow() {
    setWindowError("");
    setWindowInfo("");
    if (!adminId) {
      setWindowError("Select an admin.");
      return;
    }
    if (!unavailableStart || !unavailableEnd) {
      setWindowError("Select start and end date/time.");
      return;
    }
    const startMs = toMs(unavailableStart);
    const endMs = toMs(unavailableEnd);
    if (!startMs || !endMs || endMs <= startMs) {
      setWindowError("End must be after start.");
      return;
    }

    setSavingWindow(true);
    try {
      const res = await fetch(`${API_BASE}/api/users/admin-unavailability`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          admin_user_id: adminId,
          start_at: new Date(unavailableStart).toISOString(),
          end_at: new Date(unavailableEnd).toISOString(),
          reason: unavailableReason,
          rep_user_ids: selectedRepIds,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to save" }));
        throw new Error(err.detail || "Failed to save");
      }
      const createdWindow = (await res.json()) as AdminUnavailabilityWindow;
      const windowToken = `[admin_window:${createdWindow.id}]`;

      // Persist per-rep availability windows tied to this rule setup.
      const repTasks = selectedRepIds.map(async (repId) => {
        const sourceSlots = repSlotsByRep[repId] || [defaultSlot(unavailableStart, unavailableEnd)];
        const validSlots = sourceSlots.filter((slot) => {
          const s = toMs(slot.start);
          const e = toMs(slot.end);
          return Boolean(s && e && e > s);
        });

        for (const slot of validSlots) {
          const createRes = await fetch(`${API_BASE}/api/users/rep-availability`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders(token) },
            body: JSON.stringify({
              rep_user_id: repId,
              start_at: new Date(slot.start).toISOString(),
              end_at: new Date(slot.end).toISOString(),
              reason: `${windowToken} Linked to admin unavailability (${new Date(unavailableStart).toLocaleString()} - ${new Date(unavailableEnd).toLocaleString()})`,
            }),
          });
          if (!createRes.ok) throw new Error("Failed to save rep availability slot");
        }
      });
      await Promise.all(repTasks);

      setUnavailableStart("");
      setUnavailableEnd("");
      setUnavailableReason("");
      setSelectedRepIds([]);
      setRepSlotsByRep({});
      setWindowInfo("Admin unavailable window saved.");
      await loadAllWindows(adminId);
    } catch (err: unknown) {
      setWindowError(err instanceof Error ? err.message : "Failed to save admin unavailable window");
    } finally {
      setSavingWindow(false);
    }
  }

  async function deleteAdminWindow(windowId: string) {
    setWindowError("");
    setWindowInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/admin-unavailability/${windowId}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setWindowInfo("Unavailable window removed.");
      await loadAllWindows(adminId);
    } catch (err: unknown) {
      setWindowError(err instanceof Error ? err.message : "Failed to delete window");
    }
  }

  return (
    <div className="user-setup-page" style={{ padding: "22px 24px", fontFamily: "inherit", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box", background: "#f3f3f3" }}>
      <h1 style={{ fontSize: 24, color: "#032d60", fontWeight: 700, margin: 0 }}>Assignment Rules</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Configure lead routing by Referral Source and keep date-based availability rules below.
      </p>

      <ReferralAssignmentRulesPanel />

      <div className="user-setup-create-card" style={{ marginBottom: 14, border: "1px solid #dddbda", borderRadius: 4, padding: 14, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)" }}>
        <h2 style={{ margin: "0 0 10px", fontSize: 13, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#3e3e3c" }}>
          Admin Unavailability + Available Reps
        </h2>

        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", marginBottom: 10 }}>
          <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
            Admin
            <select
              value={adminId}
              onChange={(e) => setAdminId(e.target.value)}
              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
              disabled={loadingReps}
            >
              <option value="">Select admin...</option>
              {admins.map((admin) => (
                <option key={admin.id} value={admin.id}>
                  {admin.name} ({admin.email})
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
            Unavailable From
            <input
              type="datetime-local"
              value={unavailableStart}
              onChange={(e) => setUnavailableStart(e.target.value)}
              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
            />
          </label>

          <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
            Unavailable Until
            <input
              type="datetime-local"
              value={unavailableEnd}
              onChange={(e) => setUnavailableEnd(e.target.value)}
              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
            />
          </label>
        </div>

        <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c", marginBottom: 10 }}>
          Reason (optional)
          <input
            type="text"
            value={unavailableReason}
            onChange={(e) => setUnavailableReason(e.target.value)}
            placeholder="Vacation, sick day, after-hours, etc."
            style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
          />
        </label>

        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#3e3e3c", marginBottom: 6 }}>
            Reps Available In This Window
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {reps.map((rep) => {
              const checked = selectedRepIds.includes(rep.id);
              const slots = repSlotsByRep[rep.id] || [defaultSlot(unavailableStart, unavailableEnd)];
              return (
                <div key={rep.id} style={{ border: checked ? "1px solid #0176d3" : "1px solid #d9d9d9", borderRadius: 8, padding: 10, background: checked ? "#f0f8ff" : "#fff" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, color: "#3e3e3c", marginBottom: checked ? 8 : 0 }}>
                    <input type="checkbox" checked={checked} onChange={() => toggleSelectedRep(rep.id)} />
                    {rep.name}
                  </label>
                  {checked ? (
                    <div style={{ display: "grid", gap: 8 }}>
                      {slots.map((slot, slotIndex) => (
                        <div key={`${rep.id}-slot-${slotIndex}`} style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", alignItems: "end" }}>
                          <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                            Availability Start
                            <input
                              type="datetime-local"
                              value={slot.start}
                              onChange={(e) => updateRepSlot(rep.id, slotIndex, { start: e.target.value })}
                              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                            />
                          </label>
                          <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                            Availability End
                            <input
                              type="datetime-local"
                              value={slot.end}
                              onChange={(e) => updateRepSlot(rep.id, slotIndex, { end: e.target.value })}
                              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                            />
                          </label>
                          <div>
                            <button
                              type="button"
                              onClick={() => removeRepSlot(rep.id, slotIndex)}
                              style={{ border: "1px solid #f9b9b5", background: "#fff", color: "#ba0517", borderRadius: 4, padding: "6px 10px", fontSize: 12 }}
                            >
                              {slots.length <= 1 ? "Remove Rep" : "Remove Slot"}
                            </button>
                          </div>
                        </div>
                      ))}
                      <div>
                        <button
                          type="button"
                          onClick={() => addRepSlot(rep.id)}
                          style={{ border: "1px solid #91c8f6", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "6px 10px", fontSize: 12, fontWeight: 600 }}
                        >
                          + Add Slot
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <button
            type="button"
            onClick={createAdminWindow}
            disabled={savingWindow || !adminId}
            style={{ border: "none", background: savingWindow ? "#5a9fd4" : "#0176d3", color: "#fff", borderRadius: 4, padding: "8px 14px", fontWeight: 600 }}
          >
            {savingWindow ? "Saving..." : "Mark Admin Unavailable"}
          </button>
          <button
            type="button"
            onClick={() => loadAllWindows(adminId)}
            disabled={!adminId || loadingWindows}
            style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "8px 14px", color: "#3e3e3c" }}
          >
            Refresh
          </button>
        </div>

        {windowError ? <p style={{ marginBottom: 8, color: "#ba0517", fontSize: 13 }}>{windowError}</p> : null}
        {windowInfo ? <p style={{ marginBottom: 8, color: "#2e844a", fontSize: 13 }}>{windowInfo}</p> : null}

        <div style={{ display: "grid", gap: 12 }}>
          {!loadingWindows && windows.length === 0 ? (
            <div style={{ border: "1px solid #dddbda", borderRadius: 4, padding: 12, background: "#fff" }}>
              No unavailable windows set.
            </div>
          ) : null}

          {windows.map((w) => {
            const isEditing = editingWindowId === w.id;
            const selectedIds = isEditing ? editSelectedRepIds : (w.available_rep_ids || []);
            return (
              <div key={w.id} style={{ border: "1px solid #dddbda", borderRadius: 8, background: "#fff", padding: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                  <strong style={{ color: "#032d60" }}>Admin Slot</strong>
                  <div style={{ display: "flex", gap: 8 }}>
                    {!isEditing ? (
                      <button
                        type="button"
                        onClick={() => startEditWindow(w)}
                        style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "5px 10px", fontSize: 12 }}
                      >
                        Edit
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => saveWindowUpdate(w)}
                          disabled={savingWindow}
                          style={{ border: "none", background: "#0176d3", color: "#fff", borderRadius: 4, padding: "5px 10px", fontSize: 12 }}
                        >
                          {savingWindow ? "Saving..." : "Update"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingWindowId("")}
                          style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "5px 10px", fontSize: 12 }}
                        >
                          Cancel
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      onClick={() => deleteAdminWindow(w.id)}
                      style={{ border: "1px solid #f9b9b5", background: "#fff", color: "#ba0517", borderRadius: 4, padding: "5px 10px", fontSize: 12 }}
                    >
                      Delete
                    </button>
                  </div>
                </div>

                {!isEditing ? (
                  <div style={{ display: "grid", gap: 6, marginBottom: 10, fontSize: 13 }}>
                    <div><strong>From:</strong> {prettyDate(w.start_at)}</div>
                    <div><strong>Until:</strong> {prettyDate(w.end_at)}</div>
                    <div><strong>Reason:</strong> {w.reason || ""}</div>
                  </div>
                ) : (
                  <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", marginBottom: 10 }}>
                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                      Unavailable From
                      <input
                        type="datetime-local"
                        value={editStart}
                        onChange={(e) => setEditStart(e.target.value)}
                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                      />
                    </label>
                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                      Unavailable Until
                      <input
                        type="datetime-local"
                        value={editEnd}
                        onChange={(e) => setEditEnd(e.target.value)}
                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                      />
                    </label>
                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                      Reason
                      <input
                        type="text"
                        value={editReason}
                        onChange={(e) => setEditReason(e.target.value)}
                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                      />
                    </label>
                  </div>
                )}

                <div style={{ borderTop: "1px solid #eef0f2", paddingTop: 10 }}>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 700 }}>
                    Available Reps And Their Slots
                  </div>
                  <div style={{ display: "grid", gap: 8 }}>
                    {reps.map((rep) => {
                      const selected = selectedIds.includes(rep.id);
                      const linked = getRepWindowsForAdminWindow(w, rep.id);
                      const slots = isEditing
                        ? (editRepSlotsByRep[rep.id] || [defaultSlot(editStart, editEnd)])
                        : linked.map((slot) => ({ start: toLocalInputValue(slot.start_at), end: toLocalInputValue(slot.end_at) }));
                      const adminWindowActiveNow = isActiveNow(isEditing ? editStart : toLocalInputValue(w.start_at), isEditing ? editEnd : toLocalInputValue(w.end_at));
                      const repSlotActiveNow = slots.some((slot) => isActiveNow(slot.start, slot.end));
                      const repAvailableNow = Boolean(selected && adminWindowActiveNow && repSlotActiveNow);
                      return (
                        <div key={`${w.id}-${rep.id}`} style={{ border: selected ? "1px solid #91c8f6" : "1px solid #e5e7eb", borderRadius: 6, padding: 8, background: selected ? "#f8fbff" : "#fff" }}>
                          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, color: "#334155" }}>
                            <input
                              type="checkbox"
                              checked={selected}
                              disabled={!isEditing}
                              onChange={() => toggleEditSelectedRep(rep.id)}
                            />
                            {rep.name}
                            <span
                              style={{
                                marginLeft: "auto",
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 6,
                                fontSize: 11,
                                fontWeight: 700,
                                color: repAvailableNow ? "#166534" : "#475569",
                              }}
                            >
                              <span
                                style={{
                                  width: 8,
                                  height: 8,
                                  borderRadius: 999,
                                  background: repAvailableNow ? "#22c55e" : "#94a3b8",
                                  display: "inline-block",
                                }}
                              />
                              {repAvailableNow ? "Available now" : "Not available"}
                            </span>
                          </label>
                          {selected ? (
                            isEditing ? (
                              <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                                {slots.map((slot, slotIndex) => (
                                  <div key={`${w.id}-${rep.id}-edit-slot-${slotIndex}`} style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", alignItems: "end" }}>
                                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                                      Start
                                      <input
                                        type="datetime-local"
                                        value={slot.start}
                                        onChange={(e) => updateEditRepSlot(rep.id, slotIndex, { start: e.target.value })}
                                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                                      />
                                    </label>
                                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                                      End
                                      <input
                                        type="datetime-local"
                                        value={slot.end}
                                        onChange={(e) => updateEditRepSlot(rep.id, slotIndex, { end: e.target.value })}
                                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                                      />
                                    </label>
                                    <div>
                                      <button
                                        type="button"
                                        onClick={() => removeEditRepSlot(rep.id, slotIndex)}
                                        style={{ border: "1px solid #f9b9b5", background: "#fff", color: "#ba0517", borderRadius: 4, padding: "6px 10px", fontSize: 12 }}
                                      >
                                        {slots.length <= 1 ? "Remove Rep" : "Remove Slot"}
                                      </button>
                                    </div>
                                  </div>
                                ))}
                                <div>
                                  <button
                                    type="button"
                                    onClick={() => addEditRepSlot(rep.id)}
                                    style={{ border: "1px solid #91c8f6", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "6px 10px", fontSize: 12, fontWeight: 600 }}
                                  >
                                    + Add Slot
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div style={{ marginTop: 6, fontSize: 12, color: "#475569", display: "grid", gap: 4 }}>
                                {slots.length > 0
                                  ? slots.map((slot, idx) => (
                                    <div key={`${w.id}-${rep.id}-view-slot-${idx}`}>
                                      {slot.start && slot.end ? `${prettyDate(slot.start)} - ${prettyDate(slot.end)}` : "No specific rep slot"}
                                    </div>
                                  ))
                                  : "No specific rep slot"}
                              </div>
                            )
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
