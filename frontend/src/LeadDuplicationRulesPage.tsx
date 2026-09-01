import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Company = { id: string; name: string };
type Rule = {
  id: string;
  source_company_id: string;
  source_company_name: string;
  source_referral_source: string;
  target_company_id: string;
  target_company_name: string;
  target_referral_source: string;
  delay_minutes: number;
  active: boolean;
};
type FormState = Omit<Rule, "id" | "source_company_name" | "target_company_name">;

const blankForm: FormState = {
  source_company_id: "",
  source_referral_source: "",
  target_company_id: "",
  target_referral_source: "",
  delay_minutes: 480,
  active: true,
};

async function responseError(response: Response): Promise<string> {
  const body = await response.json().catch(() => null);
  return body?.detail || `Request failed (${response.status})`;
}

function formatDelay(minutes: number): string {
  if (minutes === 0) return "Immediately";
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return [hours ? `${hours}h` : "", remainder ? `${remainder}m` : ""].filter(Boolean).join(" ");
}

function calculateTargetCampaign(
  sourceCampaign: string,
  targetCompanyId: string,
  campaigns: Record<string, string[]>,
): string {
  if (!sourceCampaign || !targetCompanyId) return "";
  const hhgPosition = sourceCampaign.indexOf("-HHG");
  if (hhgPosition < 0) return "";
  const suffix = sourceCampaign.slice(hhgPosition);
  const targetCampaigns = campaigns[targetCompanyId] || [];

  // Prefer an existing campaign with the exact same HHG suffix.
  const exactMatch = targetCampaigns.find((campaign) => campaign.endsWith(suffix));
  if (exactMatch) return exactMatch;

  // Otherwise use the target company's campaign prefix with the source suffix.
  const targetPattern = targetCampaigns.find((campaign) => campaign.includes("-HHG"));
  if (!targetPattern) return "";
  return `${targetPattern.slice(0, targetPattern.indexOf("-HHG"))}${suffix}`;
}

export default function LeadDuplicationRulesPage() {
  const { token, user } = useAuth();
  const [rules, setRules] = useState<Rule[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [campaigns, setCampaigns] = useState<Record<string, string[]>>({});
  const [form, setForm] = useState<FormState>(blankForm);
  const [editingId, setEditingId] = useState("");
  const [targetReferralEdited, setTargetReferralEdited] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/lead-duplication-rules`, { headers: authHeaders(token) });
      if (!response.ok) throw new Error(await responseError(response));
      const body = await response.json();
      setRules(body.rules || []);
      setCompanies(body.companies || []);
      setCampaigns(body.campaigns || {});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load duplication rules");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { void load(); }, [load]);

  const sourceCampaigns = useMemo(
    () => campaigns[form.source_company_id] || [],
    [campaigns, form.source_company_id],
  );

  useEffect(() => {
    if (targetReferralEdited) return;
    const calculated = calculateTargetCampaign(form.source_referral_source, form.target_company_id, campaigns);
    setForm((current) => current.target_referral_source === calculated
      ? current
      : { ...current, target_referral_source: calculated });
  }, [campaigns, form.source_referral_source, form.target_company_id, targetReferralEdited]);

  function editRule(rule: Rule) {
    setTargetReferralEdited(true);
    setEditingId(rule.id);
    setForm({
      source_company_id: rule.source_company_id,
      source_referral_source: rule.source_referral_source,
      target_company_id: rule.target_company_id,
      target_referral_source: rule.target_referral_source,
      delay_minutes: rule.delay_minutes,
      active: rule.active,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function cancelEdit() {
    setEditingId("");
    setForm(blankForm);
    setTargetReferralEdited(false);
    setError("");
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/lead-duplication-rules${editingId ? `/${editingId}` : ""}`, {
        method: editingId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify(form),
      });
      if (!response.ok) throw new Error(await responseError(response));
      cancelEdit();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save duplication rule");
    } finally {
      setSaving(false);
    }
  }

  async function remove(rule: Rule) {
    if (!window.confirm(`Delete duplication from ${rule.source_company_name} / ${rule.source_referral_source} to ${rule.target_company_name}?`)) return;
    setError("");
    const response = await fetch(`${API_BASE}/api/lead-duplication-rules/${rule.id}`, {
      method: "DELETE",
      headers: authHeaders(token),
    });
    if (!response.ok) {
      setError(await responseError(response));
      return;
    }
    setRules((current) => current.filter((item) => item.id !== rule.id));
  }

  async function toggle(rule: Rule) {
    const response = await fetch(`${API_BASE}/api/lead-duplication-rules/${rule.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({
        source_company_id: rule.source_company_id,
        source_referral_source: rule.source_referral_source,
        target_company_id: rule.target_company_id,
        target_referral_source: rule.target_referral_source,
        delay_minutes: rule.delay_minutes,
        active: !rule.active,
      }),
    });
    if (!response.ok) {
      setError(await responseError(response));
      return;
    }
    const updated = await response.json();
    setRules((current) => current.map((item) => item.id === rule.id ? updated : item));
  }

  if (user?.role !== "admin") return <div style={page}><div style={errorBox}>Admin access is required.</div></div>;

  return (
    <div style={page}>
      <h1 style={title}>Lead Duplication Rules</h1>
      <p style={subtitle}>Choose where leads from each company and campaign should be duplicated. Add multiple rules to send the same lead to multiple companies.</p>
      {error ? <div style={errorBox}>{error}</div> : null}

      <form onSubmit={save} style={card}>
        <h2 style={cardTitle}>{editingId ? "Edit Rule" : "Add Rule"}</h2>
        <div style={formGrid}>
          <label style={label}>Source company
            <select required value={form.source_company_id} onChange={(e) => { setTargetReferralEdited(false); setForm({ ...form, source_company_id: e.target.value, source_referral_source: "", target_referral_source: "" }); }} style={input}>
              <option value="">Select company</option>
              {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
          </label>
          <label style={label}>Source campaign
            <input required list="source-campaigns" value={form.source_referral_source} onChange={(e) => { setTargetReferralEdited(false); setForm({ ...form, source_referral_source: e.target.value }); }} style={input} placeholder="Select or enter campaign" />
            <datalist id="source-campaigns">{sourceCampaigns.map((campaign) => <option key={campaign} value={campaign} />)}</datalist>
          </label>
          <label style={label}>Duplicate to company
            <select required value={form.target_company_id} onChange={(e) => { setTargetReferralEdited(false); setForm({ ...form, target_company_id: e.target.value }); }} style={input}>
              <option value="">Select company</option>
              {companies.filter((company) => company.id !== form.source_company_id).map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
          </label>
          <label style={label}>Target campaign
            <input required value={form.target_referral_source} onChange={(e) => { setTargetReferralEdited(true); setForm({ ...form, target_referral_source: e.target.value }); }} style={input} placeholder="Calculated automatically or enter campaign" />
            {form.source_referral_source && form.target_company_id && !form.target_referral_source
              ? <span style={{ color: "#ba0517", fontSize: 11, fontWeight: 400 }}>No campaign pattern was found for the target company.</span>
              : null}
          </label>
          <label style={label}>Delay (minutes)
            <input required type="number" min={0} max={525600} value={form.delay_minutes} onChange={(e) => setForm({ ...form, delay_minutes: Number(e.target.value) })} style={input} />
          </label>
          <label style={{ ...label, flexDirection: "row", alignItems: "center", alignSelf: "end", minHeight: 38 }}>
            <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Enabled
          </label>
        </div>
        <div style={actions}>
          <button type="submit" disabled={saving} style={primaryButton}>{saving ? "Saving..." : editingId ? "Save Changes" : "Add Rule"}</button>
          {editingId ? <button type="button" onClick={cancelEdit} style={secondaryButton}>Cancel</button> : null}
        </div>
      </form>

      <section style={card}>
        <h2 style={cardTitle}>Configured Rules ({rules.length})</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={table}>
            <thead><tr><th style={th}>Source</th><th style={th}>Source Campaign</th><th style={th}>Duplicate To</th><th style={th}>Target Campaign</th><th style={th}>Delay</th><th style={th}>Status</th><th style={th}>Actions</th></tr></thead>
            <tbody>
              {rules.map((rule) => <tr key={rule.id} style={{ opacity: rule.active ? 1 : 0.6 }}>
                <td style={td}>{rule.source_company_name}</td><td style={td}>{rule.source_referral_source}</td><td style={td}>{rule.target_company_name}</td><td style={td}>{rule.target_referral_source}</td><td style={td}>{formatDelay(rule.delay_minutes)}</td>
                <td style={td}><button type="button" onClick={() => void toggle(rule)} style={statusButton}>{rule.active ? "Enabled" : "Disabled"}</button></td>
                <td style={{ ...td, whiteSpace: "nowrap" }}><button type="button" onClick={() => editRule(rule)} style={linkButton}>Edit</button><button type="button" onClick={() => void remove(rule)} style={{ ...linkButton, color: "#ba0517" }}>Delete</button></td>
              </tr>)}
              {!loading && rules.length === 0 ? <tr><td colSpan={7} style={{ ...td, textAlign: "center", color: "#706e6b", padding: 30 }}>No duplication rules configured.</td></tr> : null}
              {loading ? <tr><td colSpan={7} style={{ ...td, textAlign: "center", padding: 30 }}>Loading rules...</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

const page: React.CSSProperties = { padding: "22px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box", background: "#f3f3f3" };
const title: React.CSSProperties = { margin: 0, color: "#032d60", fontSize: 24 };
const subtitle: React.CSSProperties = { color: "#706e6b", margin: "6px 0 18px" };
const card: React.CSSProperties = { background: "#fff", border: "1px solid #dddbda", borderRadius: 6, padding: 18, marginBottom: 18 };
const cardTitle: React.CSSProperties = { color: "#032d60", fontSize: 16, margin: "0 0 14px" };
const formGrid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 };
const label: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 6, color: "#181818", fontSize: 13, fontWeight: 600 };
const input: React.CSSProperties = { minHeight: 38, border: "1px solid #c9c7c5", borderRadius: 4, padding: "7px 10px", boxSizing: "border-box", background: "#fff" };
const actions: React.CSSProperties = { display: "flex", gap: 8, marginTop: 16 };
const primaryButton: React.CSSProperties = { border: 0, borderRadius: 4, padding: "9px 16px", background: "#0176d3", color: "#fff", fontWeight: 600, cursor: "pointer" };
const secondaryButton: React.CSSProperties = { border: "1px solid #0176d3", borderRadius: 4, padding: "8px 16px", background: "#fff", color: "#0176d3", fontWeight: 600, cursor: "pointer" };
const errorBox: React.CSSProperties = { background: "#fef1ee", border: "1px solid #ea001e", borderRadius: 4, color: "#ba0517", padding: 10, marginBottom: 14 };
const table: React.CSSProperties = { width: "100%", minWidth: 900, borderCollapse: "collapse", fontSize: 13 };
const th: React.CSSProperties = { textAlign: "left", color: "#3e3e3c", padding: "10px 9px", borderBottom: "1px solid #c9c7c5", background: "#f3f3f3" };
const td: React.CSSProperties = { padding: "11px 9px", borderBottom: "1px solid #e5e5e5", verticalAlign: "top" };
const linkButton: React.CSSProperties = { border: 0, background: "transparent", color: "#0176d3", cursor: "pointer", padding: "3px 8px 3px 0", fontWeight: 600 };
const statusButton: React.CSSProperties = { border: "1px solid #c9c7c5", background: "#fff", borderRadius: 12, padding: "3px 9px", cursor: "pointer", fontSize: 12 };
