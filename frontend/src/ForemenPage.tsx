import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Company = { id: string; name: string };
type Foreman = { id: string; name: string; email: string; phone?: string; companies?: Company[] };

export default function ForemenPage() {
  const { token, user } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [foremen, setForemen] = useState<Foreman[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [companyIds, setCompanyIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setError("");
    const [companiesResponse, foremenResponse] = await Promise.all([
      fetch(`${API_BASE}/api/companies/mine`, { headers: authHeaders(token) }),
      fetch(`${API_BASE}/api/users/foremen`, { headers: authHeaders(token) }),
    ]);
    if (!companiesResponse.ok || !foremenResponse.ok) throw new Error("Could not load foremen setup");
    setCompanies(await companiesResponse.json());
    setForemen(await foremenResponse.json());
  }, [token]);

  useEffect(() => { void load().catch((reason) => setError(reason.message)); }, [load]);

  function toggleCompany(companyId: string) {
    setCompanyIds((current) => current.includes(companyId) ? current.filter((id) => id !== companyId) : [...current, companyId]);
  }

  async function createForeman() {
    if (!name.trim() || !email.trim() || !password || companyIds.length === 0) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/users/foremen`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ name: name.trim(), email: email.trim(), phone: phone.trim(), password, company_ids: companyIds }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
      setName(""); setEmail(""); setPhone(""); setPassword(""); setCompanyIds([]);
      setMessage("Foreman created.");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create foreman");
    } finally { setBusy(false); }
  }

  async function saveCompanies(foreman: Foreman, nextIds: string[]) {
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/users/foremen/${foreman.id}/companies`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ company_ids: nextIds }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
      setMessage(`${foreman.name}'s companies updated.`);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update foreman");
    } finally { setBusy(false); }
  }

  if (!user || !["admin", "dispatch"].includes(user.role)) return <main style={page}><p>Access denied.</p></main>;

  return <main className="user-setup-page" style={page}>
    <header style={{ marginBottom: 16 }}><h1 style={title}>Foremen</h1><p style={subtitle}>Create read-only foremen and control which companies they can work for.</p></header>
    {error ? <div style={errorBox}>{error}</div> : null}{message ? <div style={successBox}>{message}</div> : null}
    <section style={card}>
      <h2 style={sectionTitle}>Create Foreman</h2>
      <div style={formGrid}>
        <label style={label}>Name<input style={input} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label style={label}>Email<input style={input} type="email" name="new-foreman-email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label style={label}>Phone (optional)<input style={input} type="tel" name="new-foreman-phone" autoComplete="off" value={phone} onChange={(e) => setPhone(e.target.value)} /></label>
        <label style={label}>Temporary Password<input style={input} type="password" name="new-foreman-password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      </div>
      <div style={{ marginTop: 12 }}><strong style={{ fontSize: 12, color: "#3e3e3c" }}>Companies</strong><div style={chips}>
        {companies.map((company) => <button type="button" key={company.id} onClick={() => toggleCompany(company.id)} style={companyIds.includes(company.id) ? selectedChip : chip}>{company.name}</button>)}
      </div></div>
      <button type="button" disabled={busy || !name.trim() || !email.trim() || !password || companyIds.length === 0} onClick={() => void createForeman()} style={primary}>{busy ? "Saving…" : "Create Foreman"}</button>
    </section>
    <section style={{ display: "grid", gap: 10 }}>
      {foremen.map((foreman) => {
        const assigned = new Set((foreman.companies || []).map((company) => company.id));
        return <article key={foreman.id} style={card}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}><div><h2 style={{ ...sectionTitle, marginBottom: 2 }}>{foreman.name}</h2><span style={{ color: "#706e6b", fontSize: 12 }}>{foreman.email}</span></div><span style={badge}>READ ONLY</span></div>
          <div style={chips}>{companies.map((company) => {
            const checked = assigned.has(company.id);
            return <button type="button" disabled={busy} key={company.id} style={checked ? selectedChip : chip} onClick={() => {
              const next = checked ? [...assigned].filter((id) => id !== company.id) : [...assigned, company.id];
              if (next.length > 0) void saveCompanies(foreman, next);
            }}>{company.name}</button>;
          })}</div>
        </article>;
      })}
    </section>
  </main>;
}

const page: React.CSSProperties = { padding: "20px 24px 40px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box", background: "#f6f8fb" };
const title: React.CSSProperties = { margin: "0 0 4px", color: "#032d60", fontSize: 22 };
const subtitle: React.CSSProperties = { margin: 0, color: "#706e6b", fontSize: 13 };
const card: React.CSSProperties = { border: "1px solid #dddbda", borderRadius: 6, padding: 16, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)", marginBottom: 14 };
const sectionTitle: React.CSSProperties = { margin: "0 0 12px", color: "#032d60", fontSize: 15 };
const formGrid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(210px,1fr))", gap: 10 };
const label: React.CSSProperties = { display: "grid", gap: 5, color: "#3e3e3c", fontSize: 12, fontWeight: 700 };
const input: React.CSSProperties = { minWidth: 0, border: "1px solid #c9c7c5", borderRadius: 4, padding: "8px 10px", font: "inherit" };
const chips: React.CSSProperties = { display: "flex", flexWrap: "wrap", gap: 7, margin: "9px 0 14px" };
const chip: React.CSSProperties = { border: "1px solid #c9c7c5", borderRadius: 999, padding: "5px 10px", background: "#fff", color: "#3e3e3c", cursor: "pointer" };
const selectedChip: React.CSSProperties = { ...chip, border: "1px solid #0176d3", background: "#eaf5fe", color: "#014486", fontWeight: 700 };
const primary: React.CSSProperties = { border: 0, borderRadius: 4, padding: "8px 14px", background: "#0176d3", color: "#fff", fontWeight: 700 };
const badge: React.CSSProperties = { alignSelf: "start", borderRadius: 999, padding: "3px 8px", background: "#eef4ff", color: "#032d60", fontSize: 10, fontWeight: 800 };
const errorBox: React.CSSProperties = { ...card, borderColor: "#ea001e", color: "#ba0517", background: "#fef1ee" };
const successBox: React.CSSProperties = { ...card, borderColor: "#2e844a", color: "#194e31", background: "#f3fdf6" };
