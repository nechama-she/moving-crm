import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Company = {
  id: string;
  name: string;
};

type UserCompany = {
  id: string;
  name: string;
};

type AppUser = {
  id: string;
  name: string;
  email: string;
  phone?: string;
  smartmoving_rep_id?: string;
  aircall_number_id?: string;
  role: string;
  companies?: UserCompany[];
  commission_percent?: number;
};

type CommissionSettingsResponse = {
  default_percent?: number;
  items?: Array<{
    user_id: string;
    percent?: number | null;
    effective_percent?: number;
  }>;
};

type RepUpdatePayload = {
  name: string;
  phone: string;
  smartmoving_rep_id: string;
  aircall_number_id: string;
};

export default function SalesRepsPage() {
  const { token, user } = useAuth();
  const [users, setUsers] = useState<AppUser[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [defaultCommissionPercent, setDefaultCommissionPercent] = useState<number>(((1 - 0.035) / 3) * 100);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [smartmovingRepId, setSmartmovingRepId] = useState("");
  const [aircallNumberId, setAircallNumberId] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [selectedCompanyIds, setSelectedCompanyIds] = useState<string[]>([]);

  const salesReps = useMemo(
    () => users.filter((u) => u.role === "sales_rep").sort((a, b) => a.name.localeCompare(b.name)),
    [users]
  );

  const canUse = user?.role === "admin";

  useEffect(() => {
    if (!canUse) {
      setLoading(false);
      return;
    }
    void loadData();
  }, [token, canUse]);

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const [usersRes, companiesRes, commissionRes] = await Promise.all([
        fetch(`${API_BASE}/api/users`, { headers: authHeaders(token) }),
        fetch(`${API_BASE}/api/companies`, { headers: authHeaders(token) }),
        fetch(`${API_BASE}/api/users/sales-rep-commission-settings`, { headers: authHeaders(token) }),
      ]);
      if (!usersRes.ok) throw new Error(`Users HTTP ${usersRes.status}`);
      if (!companiesRes.ok) throw new Error(`Companies HTTP ${companiesRes.status}`);
      const usersData = (await usersRes.json()) as AppUser[];
      const companiesData = (await companiesRes.json()) as Company[];
      let fallbackDefault = ((1 - 0.035) / 3) * 100;
      const commissionByUserId = new Map<string, number>();
      if (commissionRes.ok) {
        const commissionData = (await commissionRes.json()) as CommissionSettingsResponse;
        if (typeof commissionData.default_percent === "number") {
          fallbackDefault = commissionData.default_percent;
        }
        for (const item of commissionData.items || []) {
          if (item && item.user_id && typeof item.effective_percent === "number") {
            commissionByUserId.set(item.user_id, item.effective_percent);
          }
        }
      }
      setDefaultCommissionPercent(fallbackDefault);
      setUsers((usersData || []).map((u) => ({
        ...u,
        commission_percent: commissionByUserId.get(u.id) ?? fallbackDefault,
      })));
      setCompanies((companiesData || []).sort((a, b) => a.name.localeCompare(b.name)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load reps and companies");
    } finally {
      setLoading(false);
    }
  }

  function toggleCompany(companyId: string) {
    setSelectedCompanyIds((prev) =>
      prev.includes(companyId) ? prev.filter((id) => id !== companyId) : [...prev, companyId]
    );
  }

  async function copyPassword() {
    if (!password) return;
    try {
      await navigator.clipboard.writeText(password);
      setInfo("Temporary password copied.");
    } catch {
      setError("Could not copy password. Please copy manually.");
    }
  }

  async function createSalesRep() {
    setError("");
    setInfo("");
    if (!name.trim() || !email.trim() || !phone.trim() || !password.trim()) {
      setError("Name, email, phone, and password are required.");
      return;
    }

    setSaving(true);
    try {
      const createRes = await fetch(`${API_BASE}/api/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          phone: phone.trim(),
          smartmoving_rep_id: smartmovingRepId.trim(),
          aircall_number_id: aircallNumberId.trim(),
          password,
          role: "sales_rep",
        }),
      });
      if (!createRes.ok) {
        const err = await createRes.json().catch(() => ({ detail: "Failed to create rep" }));
        throw new Error(err.detail || "Failed to create rep");
      }

      const created = (await createRes.json()) as AppUser;

      for (const companyId of selectedCompanyIds) {
        const assignRes = await fetch(`${API_BASE}/api/users/${created.id}/companies`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders(token) },
          body: JSON.stringify({ company_id: companyId }),
        });
        if (!assignRes.ok) {
          const err = await assignRes.json().catch(() => ({ detail: "Company assignment failed" }));
          throw new Error(`Created rep but failed assigning company: ${err.detail || assignRes.status}`);
        }
      }

      setInfo("Sales rep created.");
      setName("");
      setEmail("");
      setPhone("");
      setSmartmovingRepId("");
      setAircallNumberId("");
      setPassword("");
      setShowPassword(false);
      setSelectedCompanyIds([]);
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create rep");
    } finally {
      setSaving(false);
    }
  }

  async function assignCompany(userId: string, companyId: string) {
    if (!companyId) return;
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/${userId}/companies`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ company_id: companyId }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to assign company" }));
        throw new Error(err.detail || "Failed to assign company");
      }
      setInfo("Company assigned.");
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to assign company");
    }
  }

  async function unassignCompany(userId: string, companyId: string) {
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/${userId}/companies/${companyId}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to remove company" }));
        throw new Error(err.detail || "Failed to remove company");
      }
      setInfo("Company removed from rep.");
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to remove company");
    }
  }

  async function deleteRep(userId: string, repName: string) {
    const ok = window.confirm(`Delete rep ${repName}? This will unassign their leads.`);
    if (!ok) return;

    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/${userId}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to delete rep" }));
        throw new Error(err.detail || "Failed to delete rep");
      }
      setInfo("Rep deleted.");
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete rep");
    }
  }

  async function updateRep(userId: string, payload: RepUpdatePayload) {
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/${userId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          name: payload.name.trim(),
          phone: payload.phone.trim(),
          smartmoving_rep_id: payload.smartmoving_rep_id.trim(),
          aircall_number_id: payload.aircall_number_id.trim(),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to update rep" }));
        throw new Error(err.detail || "Failed to update rep");
      }
      setInfo("Rep updated.");
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update rep");
      throw err;
    }
  }

  async function updateRepCommission(userId: string, percent: number | null) {
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/sales-rep-commission-settings/${userId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ percent }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to update commission percent" }));
        throw new Error(err.detail || "Failed to update commission percent");
      }
      setInfo("Commission percent updated.");
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update commission percent");
      throw err;
    }
  }

  if (!canUse) {
    return (
      <div style={{ padding: "20px 24px" }}>
        <h1 style={{ fontSize: 20, color: "#032d60", marginBottom: 8 }}>Sales Reps</h1>
        <p style={{ color: "#ba0517" }}>Only admins can manage sales reps.</p>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Sales Reps</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Add reps and map them to companies for assignment and routing.
      </p>

      <div style={{ border: "1px solid #dddbda", borderRadius: 4, padding: 16, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)", marginBottom: 14 }}>
        <h2 style={sectionHeader}>Create Sales Rep</h2>
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <label style={fieldLabel}>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Phone
            <input value={phone} onChange={(e) => setPhone(e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            SmartMoving Rep ID
            <input value={smartmovingRepId} onChange={(e) => setSmartmovingRepId(e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Aircall Number ID
            <input value={aircallNumberId} onChange={(e) => setAircallNumberId(e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Temporary Password
            <div style={{ display: "grid", gap: 4 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{ ...inputStyle, flex: 1, height: 34 }}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "0 10px", fontSize: 12, height: 34 }}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
              <button
                type="button"
                onClick={() => void copyPassword()}
                disabled={!password}
                style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "0 10px", fontSize: 12, height: 34 }}
              >
                Copy
              </button>
              </div>
              <span style={{ display: "block", width: "100%", marginTop: 0, fontSize: 11, lineHeight: 1.35, color: "#706e6b", paddingLeft: 10 }}>
                This is the password the rep will use for first login.
              </span>
            </div>
          </label>
        </div>

        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#3e3e3c", marginBottom: 6 }}>Assign Companies</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {companies.map((company) => {
              const checked = selectedCompanyIds.includes(company.id);
              return (
                <button
                  type="button"
                  key={company.id}
                  onClick={() => toggleCompany(company.id)}
                  style={{
                    border: checked ? "1px solid #0176d3" : "1px solid #c9c7c5",
                    background: checked ? "#eaf5fe" : "#fff",
                    color: checked ? "#014486" : "#3e3e3c",
                    borderRadius: 16,
                    padding: "5px 10px",
                    fontSize: 12,
                  }}
                >
                  {company.name}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ marginTop: 14 }}>
          <button
            type="button"
            onClick={createSalesRep}
            disabled={saving}
            style={{ border: "none", background: saving ? "#5a9fd4" : "#0176d3", color: "#fff", borderRadius: 4, padding: "8px 14px", fontWeight: 600 }}
          >
            {saving ? "Creating..." : "Create Rep"}
          </button>
        </div>
      </div>

      {error ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{error}</p> : null}
      {info ? <p style={{ marginBottom: 10, color: "#2e844a", fontSize: 13 }}>{info}</p> : null}

      <div style={{ border: "1px solid #dddbda", borderRadius: 4, overflow: "auto", background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 900 }}>
          <thead>
            <tr>
              <th style={th}>Rep</th>
              <th style={th}>Commission %</th>
              <th style={th}>Email</th>
              <th style={th}>Phone</th>
              <th style={th}>SmartMoving Rep ID</th>
              <th style={th}>Aircall Number ID</th>
              <th style={th}>Companies</th>
              <th style={th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td style={td} colSpan={8}>Loading...</td>
              </tr>
            ) : null}
            {!loading && salesReps.length === 0 ? (
              <tr>
                <td style={td} colSpan={8}>No sales reps yet.</td>
              </tr>
            ) : null}

            {!loading && salesReps.map((rep) => (
              <RepRow
                key={rep.id}
                rep={rep}
                companies={companies}
                onUpdate={updateRep}
                onAssign={assignCompany}
                onUnassign={unassignCompany}
                onDelete={deleteRep}
                onUpdateCommission={updateRepCommission}
                defaultCommissionPercent={defaultCommissionPercent}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RepRow({
  rep,
  companies,
  onUpdate,
  onAssign,
  onUnassign,
  onDelete,
  onUpdateCommission,
  defaultCommissionPercent,
}: {
  rep: AppUser;
  companies: Company[];
  onUpdate: (userId: string, payload: RepUpdatePayload) => Promise<void>;
  onAssign: (userId: string, companyId: string) => Promise<void>;
  onUnassign: (userId: string, companyId: string) => Promise<void>;
  onDelete: (userId: string, repName: string) => Promise<void>;
  onUpdateCommission: (userId: string, percent: number | null) => Promise<void>;
  defaultCommissionPercent: number;
}) {
  const [selectedCompanyId, setSelectedCompanyId] = useState("");
  const [showCompanyManager, setShowCompanyManager] = useState(false);
  const [name, setName] = useState(rep.name || "");
  const [phone, setPhone] = useState(rep.phone || "");
  const [smartmovingRepId, setSmartmovingRepId] = useState(rep.smartmoving_rep_id || "");
  const [aircallNumberId, setAircallNumberId] = useState(rep.aircall_number_id || "");
  const [commissionPercent, setCommissionPercent] = useState(
    String(typeof rep.commission_percent === "number" ? rep.commission_percent : defaultCommissionPercent)
  );
  const [savingRep, setSavingRep] = useState(false);
  const [savingCommission, setSavingCommission] = useState(false);
  const assigned = rep.companies || [];
  const assignedIds = new Set(assigned.map((c) => c.id));
  const availableCompanies = companies.filter((c) => !assignedIds.has(c.id));
  const previewCompanies = assigned.slice(0, 2);
  const extraCompaniesCount = Math.max(0, assigned.length - previewCompanies.length);

  useEffect(() => {
    setCommissionPercent(String(typeof rep.commission_percent === "number" ? rep.commission_percent : defaultCommissionPercent));
  }, [rep.commission_percent, defaultCommissionPercent]);

  async function saveRep() {
    setSavingRep(true);
    try {
      await onUpdate(rep.id, {
        name,
        phone,
        smartmoving_rep_id: smartmovingRepId,
        aircall_number_id: aircallNumberId,
      });
    } catch {
      // Parent handles message display.
    } finally {
      setSavingRep(false);
    }
  }

  async function saveCommissionPercent() {
    const parsed = Number(commissionPercent);
    if (!Number.isFinite(parsed)) return;
    if (parsed < 0 || parsed > 100) return;
    setSavingCommission(true);
    try {
      await onUpdateCommission(rep.id, parsed);
    } catch {
      // Parent handles message display.
    } finally {
      setSavingCommission(false);
    }
  }

  async function resetCommissionPercent() {
    setSavingCommission(true);
    try {
      await onUpdateCommission(rep.id, null);
    } catch {
      // Parent handles message display.
    } finally {
      setSavingCommission(false);
    }
  }

  return (
    <tr style={{ borderTop: "1px solid #e5e7eb" }}>
      <td style={td}>
        <input value={name} onChange={(e) => setName(e.target.value)} style={{ ...inputStyle, minWidth: 170, padding: "6px 8px" }} />
      </td>
      <td style={td}>
        <div style={{ display: "grid", gap: 6, minWidth: 180 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input
              type="number"
              min={0}
              max={100}
              step="0.000001"
              value={commissionPercent}
              onChange={(e) => setCommissionPercent(e.target.value)}
              style={{ ...inputStyle, minWidth: 92, padding: "6px 8px" }}
            />
            <span style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>%</span>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => void saveCommissionPercent()}
              disabled={savingCommission}
              style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "4px 8px", fontSize: 11, fontWeight: 700 }}
            >
              {savingCommission ? "Saving..." : "Save %"}
            </button>
            <button
              type="button"
              onClick={() => void resetCommissionPercent()}
              disabled={savingCommission}
              style={{ border: "1px solid #c9c7c5", background: "#fff", color: "#334155", borderRadius: 4, padding: "4px 8px", fontSize: 11, fontWeight: 700 }}
            >
              Default
            </button>
          </div>
          <div style={{ fontSize: 11, color: "#64748b" }}>Default: {defaultCommissionPercent.toFixed(6)}%</div>
        </div>
      </td>
      <td style={td}>{rep.email}</td>
      <td style={td}>
        <input value={phone} onChange={(e) => setPhone(e.target.value)} style={{ ...inputStyle, minWidth: 130, padding: "6px 8px" }} />
      </td>
      <td style={td}>
        <input value={smartmovingRepId} onChange={(e) => setSmartmovingRepId(e.target.value)} style={{ ...inputStyle, minWidth: 170, padding: "6px 8px" }} />
      </td>
      <td style={td}>
        <input
          value={aircallNumberId}
          onChange={(e) => setAircallNumberId(e.target.value)}
          style={{ ...inputStyle, minWidth: 170, padding: "6px 8px" }}
        />
      </td>
      <td style={td}>
        <div style={{ minWidth: 280 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>{assigned.length} assigned</span>
            {previewCompanies.map((c) => (
              <span key={c.id} style={{ border: "1px solid #cbd5e1", borderRadius: 999, padding: "2px 8px", fontSize: 11, color: "#334155", background: "#f8fafc" }}>
                {c.name}
              </span>
            ))}
            {extraCompaniesCount > 0 ? <span style={{ fontSize: 11, color: "#64748b" }}>+{extraCompaniesCount} more</span> : null}
            <button
              type="button"
              onClick={() => setShowCompanyManager((v) => !v)}
              style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "4px 8px", fontSize: 11, fontWeight: 700 }}
            >
              {showCompanyManager ? "Close" : "Manage"}
            </button>
          </div>

          {showCompanyManager ? (
            <div style={{ marginTop: 8, border: "1px solid #e2e8f0", borderRadius: 8, padding: 8, background: "#f8fafc" }}>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                {assigned.length === 0 ? <span style={{ color: "#706e6b", fontSize: 12 }}>No companies</span> : null}
                {assigned.map((c) => (
                  <span key={c.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, border: "1px solid #c9c7c5", borderRadius: 16, padding: "3px 8px", fontSize: 12, color: "#3e3e3c", background: "#fff" }}>
                    {c.name}
                    <button
                      type="button"
                      onClick={() => void onUnassign(rep.id, c.id)}
                      style={{ border: "none", background: "transparent", color: "#ba0517", fontSize: 12, padding: 0, cursor: "pointer" }}
                      title="Remove"
                    >
                      x
                    </button>
                  </span>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <select value={selectedCompanyId} onChange={(e) => setSelectedCompanyId(e.target.value)} style={{ ...inputStyle, minWidth: 220 }}>
                  <option value="">Select company...</option>
                  {availableCompanies.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => void onAssign(rep.id, selectedCompanyId)}
                  disabled={!selectedCompanyId}
                  style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "6px 10px", fontSize: 12, fontWeight: 600 }}
                >
                  Assign
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </td>
      <td style={td}>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={() => void saveRep()}
            disabled={savingRep}
            style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "6px 10px", fontSize: 12, fontWeight: 600 }}
          >
            {savingRep ? "Saving..." : "Save"}
          </button>
          <button
            type="button"
            onClick={() => void onDelete(rep.id, rep.name)}
            style={{ border: "1px solid #f9b9b5", background: "#fff", color: "#ba0517", borderRadius: 4, padding: "6px 10px", fontSize: 12, fontWeight: 600 }}
          >
            Delete Rep
          </button>
        </div>
      </td>
    </tr>
  );
}

const sectionHeader: React.CSSProperties = {
  margin: "0 0 10px",
  fontSize: 13,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "#3e3e3c",
};

const fieldLabel: React.CSSProperties = {
  display: "grid",
  gap: 5,
  fontSize: 13,
  fontWeight: 600,
  color: "#3e3e3c",
};

const inputStyle: React.CSSProperties = {
  border: "1px solid #dddbda",
  borderRadius: 4,
  padding: "8px 10px",
  background: "#fff",
  fontSize: 13,
};

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
  fontSize: 13,
  color: "#111827",
  verticalAlign: "top",
};
