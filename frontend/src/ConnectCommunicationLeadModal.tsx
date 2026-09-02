import { useEffect, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders } from "./AuthContext";

export type CommunicationTarget = {
  channel: string;
  clientIdentifier: string;
  companyIdentifier: string;
};

type Candidate = { id: string; name: string; phone: string; email: string; company: string };

export default function ConnectCommunicationLeadModal({ target, token, onClose, onConnected }: {
  target: CommunicationTarget;
  token: string | null;
  onClose: () => void;
  onConnected: (lead: { id: string; name: string; company: string; rep?: string }) => void;
}) {
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<Candidate[]>([]);
  const [companies, setCompanies] = useState<string[]>([]);
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
        setCompanies((body.companies || []).map((company: { name: string }) => company.name));
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

  return <div role="presentation" onMouseDown={onClose} style={{ position: "fixed", inset: 0, zIndex: 2000, background: "rgba(15,23,42,.42)", display: "grid", placeItems: "center", padding: 16 }}>
    <section role="dialog" aria-modal="true" aria-label="Connect communication to lead" onMouseDown={(event) => event.stopPropagation()} style={{ width: "min(620px, 100%)", maxHeight: "min(720px, 90vh)", overflow: "hidden", background: "#fff", borderRadius: 10, boxShadow: "0 20px 50px rgba(0,0,0,.25)", display: "flex", flexDirection: "column" }}>
      <header style={{ padding: "18px 20px", borderBottom: "1px solid #d8dde6", display: "flex", justifyContent: "space-between", gap: 16 }}><div><h2 style={{ margin: 0, color: "#032d60", fontSize: 20 }}>Connect to a lead</h2><div style={{ marginTop: 5, color: "#64748b", fontSize: 13 }}>{companies.length ? `Showing leads under ${companies.join(", ")}` : "Finding the destination company…"}</div></div><button type="button" onClick={onClose} aria-label="Close" style={{ border: 0, background: "transparent", fontSize: 24, cursor: "pointer" }}>×</button></header>
      <div style={{ padding: 16, borderBottom: "1px solid #e2e8f0" }}><input autoFocus type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, phone, email, or SmartMoving ID" style={{ width: "100%", padding: "11px 12px", border: "1px solid #94a3b8", borderRadius: 6, boxSizing: "border-box" }} /></div>
      {error ? <div style={{ margin: 16, color: "#ba0517" }}>{error}</div> : null}
      <div style={{ overflowY: "auto", minHeight: 180 }}>{loading ? <p style={{ padding: 20 }}>Loading leads…</p> : items.length ? items.map((lead) => <button key={lead.id} type="button" disabled={Boolean(saving)} onClick={() => void connect(lead)} style={{ width: "100%", border: 0, borderBottom: "1px solid #e2e8f0", background: "#fff", padding: "13px 20px", textAlign: "left", cursor: saving ? "wait" : "pointer" }}><strong style={{ color: "#0b5cab" }}>{lead.name || "Unnamed lead"}</strong><span style={{ display: "block", color: "#475569", fontSize: 12, marginTop: 4 }}>{[lead.company, lead.phone, lead.email].filter(Boolean).join(" · ")}</span></button>) : <p style={{ padding: 20, color: "#64748b" }}>No matching leads found.</p>}</div>
    </section>
  </div>;
}
