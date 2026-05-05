import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Company = {
  id: string;
  name: string;
  phone?: string;
  facebook_page_id?: string;
  aircall_number_id?: string;
  samrtmoving_branch_id?: string;
  timezone?: string;
};

type CompanyForm = {
  name: string;
  phone: string;
  facebook_page_id: string;
  aircall_number_id: string;
  samrtmoving_branch_id: string;
  timezone: string;
};

const emptyForm: CompanyForm = {
  name: "",
  phone: "",
  facebook_page_id: "",
  aircall_number_id: "",
  samrtmoving_branch_id: "",
  timezone: "America/New_York",
};

export default function CompaniesPage() {
  const { token, user } = useAuth();
  const canUse = user?.role === "admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const [form, setForm] = useState<CompanyForm>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const editing = !!editingId;

  useEffect(() => {
    if (!canUse) {
      setLoading(false);
      return;
    }
    void loadCompanies();
  }, [token, canUse]);

  async function loadCompanies() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/companies`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as Company[];
      setCompanies((data || []).sort((a, b) => (a.name || "").localeCompare(b.name || "")));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load companies");
    } finally {
      setLoading(false);
    }
  }

  function updateField<K extends keyof CompanyForm>(key: K, value: CompanyForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function resetForm() {
    setEditingId(null);
    setForm(emptyForm);
  }

  function startEdit(company: Company) {
    setEditingId(company.id);
    setForm({
      name: company.name || "",
      phone: company.phone || "",
      facebook_page_id: company.facebook_page_id || "",
      aircall_number_id: company.aircall_number_id || "",
      samrtmoving_branch_id: company.samrtmoving_branch_id || "",
      timezone: company.timezone || "America/New_York",
    });
    setError("");
    setInfo("");
  }

  async function saveCompany() {
    setError("");
    setInfo("");

    if (!form.name.trim()) {
      setError("Company name is required.");
      return;
    }

    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        phone: form.phone.trim(),
        facebook_page_id: form.facebook_page_id.trim(),
        aircall_number_id: form.aircall_number_id.trim(),
        samrtmoving_branch_id: form.samrtmoving_branch_id.trim(),
        timezone: form.timezone.trim() || "America/New_York",
      };

      const url = editingId ? `${API_BASE}/api/companies/${editingId}` : `${API_BASE}/api/companies`;
      const method = editingId ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      setInfo(editing ? "Company updated." : "Company created.");
      resetForm();
      await loadCompanies();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save company");
    } finally {
      setSaving(false);
    }
  }

  async function deleteCompany(company: Company) {
    const ok = window.confirm(`Delete company ${company.name}? This cannot be undone.`);
    if (!ok) return;

    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/companies/${company.id}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || "Failed to delete company");
      }
      setInfo("Company deleted.");
      if (editingId === company.id) resetForm();
      await loadCompanies();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete company");
    }
  }

  const filteredCompanies = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter((c) => {
      const fields = [
        c.name || "",
        c.phone || "",
        c.facebook_page_id || "",
        c.aircall_number_id || "",
        c.samrtmoving_branch_id || "",
        c.timezone || "",
      ];
      return fields.some((v) => v.toLowerCase().includes(q));
    });
  }, [companies, search]);

  if (!canUse) {
    return (
      <div style={{ padding: "20px 24px" }}>
        <h1 style={{ fontSize: 20, color: "#032d60", marginBottom: 8 }}>Companies</h1>
        <p style={{ color: "#ba0517" }}>Only admins can manage company settings.</p>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Companies</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Add, edit, and remove company records used for lead routing, messaging, and SmartMoving sync.
      </p>

      <div style={{ border: "1px solid #dddbda", borderRadius: 4, padding: 16, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)", marginBottom: 14 }}>
        <h2 style={sectionHeader}>{editing ? "Edit Company" : "Create Company"}</h2>
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <label style={fieldLabel}>
            Name
            <input value={form.name} onChange={(e) => updateField("name", e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Phone
            <input value={form.phone} onChange={(e) => updateField("phone", e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Facebook Page ID
            <input value={form.facebook_page_id} onChange={(e) => updateField("facebook_page_id", e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Aircall Number ID
            <input value={form.aircall_number_id} onChange={(e) => updateField("aircall_number_id", e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            SmartMoving Branch ID
            <input value={form.samrtmoving_branch_id} onChange={(e) => updateField("samrtmoving_branch_id", e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Timezone
            <input value={form.timezone} onChange={(e) => updateField("timezone", e.target.value)} style={inputStyle} />
          </label>
        </div>

        <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={() => void saveCompany()}
            disabled={saving}
            style={{ border: "none", background: saving ? "#5a9fd4" : "#0176d3", color: "#fff", borderRadius: 4, padding: "8px 14px", fontWeight: 600 }}
          >
            {saving ? (editing ? "Saving..." : "Creating...") : (editing ? "Save Company" : "Create Company")}
          </button>
          {editing ? (
            <button
              type="button"
              onClick={resetForm}
              style={{ border: "1px solid #c9c7c5", background: "#fff", color: "#3e3e3c", borderRadius: 4, padding: "8px 14px", fontWeight: 600 }}
            >
              Cancel
            </button>
          ) : null}
        </div>
      </div>

      {error ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{error}</p> : null}
      {info ? <p style={{ marginBottom: 10, color: "#2e844a", fontSize: 13 }}>{info}</p> : null}

      <div style={{ border: "1px solid #dddbda", borderRadius: 4, overflow: "auto", background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)" }}>
        <div style={{ padding: 12, borderBottom: "1px solid #dddbda", display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
          <strong style={{ color: "#032d60", fontSize: 14 }}>Company Directory</strong>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search companies"
            style={{ ...inputStyle, width: 250, margin: 0 }}
          />
        </div>

        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1080 }}>
          <thead>
            <tr>
              <th style={th}>Name</th>
              <th style={th}>Phone</th>
              <th style={th}>Facebook Page ID</th>
              <th style={th}>Aircall Number ID</th>
              <th style={th}>SmartMoving Branch ID</th>
              <th style={th}>Timezone</th>
              <th style={th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td style={td} colSpan={7}>Loading...</td>
              </tr>
            ) : null}

            {!loading && filteredCompanies.length === 0 ? (
              <tr>
                <td style={td} colSpan={7}>No companies found.</td>
              </tr>
            ) : null}

            {!loading && filteredCompanies.map((company) => (
              <tr key={company.id} style={{ borderTop: "1px solid #f1f0ef" }}>
                <td style={td}>{company.name || "-"}</td>
                <td style={td}>{company.phone || "-"}</td>
                <td style={td}>{company.facebook_page_id || "-"}</td>
                <td style={td}>{company.aircall_number_id || "-"}</td>
                <td style={td}>{company.samrtmoving_branch_id || "-"}</td>
                <td style={td}>{company.timezone || "-"}</td>
                <td style={td}>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      type="button"
                      onClick={() => startEdit(company)}
                      style={{ border: "1px solid #0176d3", color: "#0176d3", background: "#fff", borderRadius: 4, padding: "4px 10px", fontSize: 12, fontWeight: 600 }}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => void deleteCompany(company)}
                      style={{ border: "1px solid #ba0517", color: "#ba0517", background: "#fff", borderRadius: 4, padding: "4px 10px", fontSize: 12, fontWeight: 600 }}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
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
  fontSize: 12,
  color: "#3e3e3c",
  fontWeight: 600,
};

const inputStyle: React.CSSProperties = {
  height: 34,
  border: "1px solid #c9c7c5",
  borderRadius: 4,
  padding: "0 10px",
  fontSize: 13,
  color: "#181818",
  background: "#fff",
  boxSizing: "border-box",
};

const th: React.CSSProperties = {
  textAlign: "left",
  fontSize: 12,
  color: "#706e6b",
  fontWeight: 700,
  padding: "10px 12px",
  borderBottom: "1px solid #dddbda",
  background: "#fafaf9",
  whiteSpace: "nowrap",
};

const td: React.CSSProperties = {
  padding: "10px 12px",
  fontSize: 13,
  color: "#181818",
  verticalAlign: "top",
};
