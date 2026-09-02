import { useEffect, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders } from "./AuthContext";

export type CommunicationTarget = {
  channel: string;
  clientIdentifier: string;
  companyIdentifier: string;
};

type Candidate = { id: string; name: string; phone: string; email: string; company: string };
type CompanyOption = { id: string; name: string };

export default function ConnectCommunicationLeadModal({ target, token, onClose, onConnected }: {
  target: CommunicationTarget;
  token: string | null;
  onClose: () => void;
  onConnected: (lead: { id: string; name: string; company: string; rep?: string }) => void;
}) {
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<Candidate[]>([]);
  const [scopeLabel, setScopeLabel] = useState("");
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [creating, setCreating] = useState(false);
  const [companyId, setCompanyId] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState(["sms", "phone", "call", "calls"].includes(target.channel.toLowerCase()) ? target.clientIdentifier : "");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true); setError("");
      const params = new URLSearchParams({ channel: target.channel, client_identifier: target.clientIdentifier, company_identifier: target.companyIdentifier, search });
      try {
        const response = await fetch(`${API_BASE}/api/communication-associations/candidates?${params}`, { headers: authHeaders(token), signal: controller.signal });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "Could not load leads");
        setItems(body.items || []);
        setScopeLabel(String(body.scope_label || ""));
        const availableCompanies = (body.companies || []) as CompanyOption[];
        setCompanies(availableCompanies);
        setCompanyId((current) => current || availableCompanies[0]?.id || "");
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Could not load leads");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [search, target, token]);

  async function connect(lead: Candidate) {
    setSaving(lead.id); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/communication-associations`, {
        method: "PUT", headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({ channel: target.channel, client_identifier: target.clientIdentifier, company_identifier: target.companyIdentifier, lead_id: lead.id }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "Could not connect lead");
      onConnected(body.lead);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not connect lead");
    } finally { setSaving(""); }
  }

  async function createLead() {
    if (!fullName.trim() || !companyId) return;
    setSaving("new"); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/communication-associations/create-lead`, {
        method: "POST", headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({
          channel: target.channel,
          client_identifier: target.clientIdentifier,
          company_identifier: target.companyIdentifier,
          company_id: companyId,
          full_name: fullName.trim(),
          phone: phone.trim(),
          email: email.trim(),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "Could not create lead");
      onConnected(body.lead);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create lead");
    } finally { setSaving(""); }
  }

  return <div role="presentation" onMouseDown={onClose} style={{ position: "fixed", inset: 0, zIndex: 2000, background: "rgba(15,23,42,.42)", display: "grid", placeItems: "center", padding: 16 }}>
    <section role="dialog" aria-modal="true" aria-label="Connect communication to lead" onMouseDown={(event) => event.stopPropagation()} style={{ width: "min(620px, 100%)", maxHeight: "min(720px, 90vh)", overflow: "hidden", background: "#fff", borderRadius: 10, boxShadow: "0 20px 50px rgba(0,0,0,.25)", display: "flex", flexDirection: "column" }}>
      <header style={{ padding: "18px 20px", borderBottom: "1px solid #d8dde6", display: "flex", justifyContent: "space-between", gap: 16 }}><div><h2 style={{ margin: 0, color: "#032d60", fontSize: 20 }}>Connect to a lead</h2><div style={{ marginTop: 5, color: "#64748b", fontSize: 13 }}>{scopeLabel ? `Showing leads under ${scopeLabel}` : "Finding the destination…"}</div></div><button type="button" onClick={onClose} aria-label="Close" style={{ border: 0, background: "transparent", fontSize: 24, cursor: "pointer" }}>×</button></header>
      <div style={{ padding: 16, borderBottom: "1px solid #e2e8f0" }}><input autoFocus type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, phone, email, or SmartMoving ID" style={{ width: "100%", padding: "11px 12px", border: "1px solid #94a3b8", borderRadius: 6, boxSizing: "border-box" }} /></div>
      {error ? <div style={{ margin: 16, color: "#ba0517" }}>{error}</div> : null}
      <div style={{ overflowY: "auto", minHeight: 180 }}>{loading ? <p style={{ padding: 20 }}>Loading leads…</p> : items.length ? items.map((lead) => <button key={lead.id} type="button" disabled={Boolean(saving)} onClick={() => void connect(lead)} style={{ width: "100%", border: 0, borderBottom: "1px solid #e2e8f0", background: "#fff", padding: "13px 20px", textAlign: "left", cursor: saving ? "wait" : "pointer" }}><strong style={{ color: "#0b5cab" }}>{lead.name || "Unnamed lead"}</strong><span style={{ display: "block", color: "#475569", fontSize: 12, marginTop: 4 }}>{[lead.company, lead.phone, lead.email].filter(Boolean).join(" · ")}</span></button>) : creating ? <div style={{ padding: 20, display: "grid", gap: 12 }}>
        <strong style={{ color: "#032d60" }}>Create a new lead</strong>
        {companies.length > 1 ? <label style={{ display: "grid", gap: 5, fontSize: 12, color: "#475569" }}>Company<select value={companyId} onChange={(event) => setCompanyId(event.target.value)} style={{ padding: 10, border: "1px solid #94a3b8", borderRadius: 6 }}>{companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}</select></label> : null}
        <input value={fullName} onChange={(event) => setFullName(event.target.value)} placeholder="Full name" aria-label="Full name" style={{ padding: 10, border: "1px solid #94a3b8", borderRadius: 6 }} />
        <input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="Phone" aria-label="Phone" style={{ padding: 10, border: "1px solid #94a3b8", borderRadius: 6 }} />
        <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Email" aria-label="Email" style={{ padding: 10, border: "1px solid #94a3b8", borderRadius: 6 }} />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}><button type="button" onClick={() => setCreating(false)} style={{ padding: "9px 14px", border: "1px solid #0176d3", borderRadius: 5, background: "#fff", color: "#0176d3", cursor: "pointer" }}>Back</button><button type="button" disabled={!fullName.trim() || !companyId || Boolean(saving)} onClick={() => void createLead()} style={{ padding: "9px 14px", border: 0, borderRadius: 5, background: "#0176d3", color: "#fff", cursor: saving ? "wait" : "pointer", opacity: !fullName.trim() || !companyId ? .55 : 1 }}>{saving === "new" ? "Creating…" : "Create and connect"}</button></div>
      </div> : <div style={{ padding: 20 }}><p style={{ margin: "0 0 14px", color: "#64748b" }}>No matching leads found.</p><button type="button" onClick={() => { setFullName(search.trim()); setCreating(true); }} style={{ padding: "10px 15px", border: 0, borderRadius: 5, background: "#0176d3", color: "#fff", cursor: "pointer", fontWeight: 700 }}>Create new lead</button></div>}</div>
    </section>
  </div>;
}
