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
  role: string;
  companies?: UserCompany[];
};

export default function SalesRepsPage() {
  const { token, user } = useAuth();
  const [users, setUsers] = useState<AppUser[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [smartmovingRepId, setSmartmovingRepId] = useState("");
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
      const [usersRes, companiesRes] = await Promise.all([
        fetch(`${API_BASE}/api/users`, { headers: authHeaders(token) }),
        fetch(`${API_BASE}/api/companies`, { headers: authHeaders(token) }),
      ]);
      if (!usersRes.ok) throw new Error(`Users HTTP ${usersRes.status}`);
      if (!companiesRes.ok) throw new Error(`Companies HTTP ${companiesRes.status}`);
      const usersData = (await usersRes.json()) as AppUser[];
      const companiesData = (await companiesRes.json()) as Company[];
      setUsers(usersData || []);
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
              <th style={th}>Email</th>
              <th style={th}>Phone</th>
              <th style={th}>SmartMoving Rep ID</th>
              <th style={th}>Companies</th>
              <th style={th}>Assign Company</th>
              <th style={th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td style={td} colSpan={7}>Loading...</td>
              </tr>
            ) : null}
            {!loading && salesReps.length === 0 ? (
              <tr>
                <td style={td} colSpan={7}>No sales reps yet.</td>
              </tr>
            ) : null}

            {!loading && salesReps.map((rep) => (
              <RepRow
                key={rep.id}
                rep={rep}
                companies={companies}
                onAssign={assignCompany}
                onUnassign={unassignCompany}
                onDelete={deleteRep}
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
  onAssign,
  onUnassign,
  onDelete,
}: {
  rep: AppUser;
  companies: Company[];
  onAssign: (userId: string, companyId: string) => Promise<void>;
  onUnassign: (userId: string, companyId: string) => Promise<void>;
  onDelete: (userId: string, repName: string) => Promise<void>;
}) {
  const [selectedCompanyId, setSelectedCompanyId] = useState("");
  const assigned = rep.companies || [];
  const assignedIds = new Set(assigned.map((c) => c.id));
  const availableCompanies = companies.filter((c) => !assignedIds.has(c.id));

  return (
    <tr style={{ borderTop: "1px solid #e5e7eb" }}>
      <td style={td}>{rep.name}</td>
      <td style={td}>{rep.email}</td>
      <td style={td}>{rep.phone || ""}</td>
      <td style={td}>{rep.smartmoving_rep_id || ""}</td>
      <td style={td}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {assigned.length === 0 ? <span style={{ color: "#706e6b", fontSize: 12 }}>No companies</span> : null}
          {assigned.map((c) => (
            <span key={c.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, border: "1px solid #c9c7c5", borderRadius: 16, padding: "3px 8px", fontSize: 12, color: "#3e3e3c", background: "#f8f9fa" }}>
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
      </td>
      <td style={td}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
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
      </td>
      <td style={td}>
        <button
          type="button"
          onClick={() => void onDelete(rep.id, rep.name)}
          style={{ border: "1px solid #f9b9b5", background: "#fff", color: "#ba0517", borderRadius: 4, padding: "6px 10px", fontSize: 12, fontWeight: 600 }}
        >
          Delete Rep
        </button>
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
