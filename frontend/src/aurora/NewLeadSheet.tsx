import { useState } from "react";
import { API_BASE } from "../apiConfig";
import { authHeaders } from "../AuthContext";
import Icon from "./Icon";

type Option = { id: string; name: string };
const EMPTY = { company_id: "", full_name: "", phone: "", email: "", pickup_zip: "", delivery_zip: "", move_date: "", move_size: "", referral_source: "", assigned_to: "", notes: "" };

// Adds a lead by hand: a standalone CRM lead (no SmartMoving), with the rep picked for it. Saved, it opens the lead.
export default function NewLeadSheet({ token, companies, reps, onClose, onCreated }: {
  token: string | null; companies: Option[]; reps: Option[]; onClose: () => void; onCreated: (leadId: string) => void;
}) {
  const [form, setForm] = useState({ ...EMPTY, company_id: companies.length === 1 ? companies[0].id : "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (field: keyof typeof EMPTY) => (event: { target: { value: string } }) => setForm(current => ({ ...current, [field]: event.target.value }));
  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/leads/new`, {
        method: "POST", headers: { ...authHeaders(token), "Content-Type": "application/json" }, body: JSON.stringify(form),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Could not add the lead. Please try again.");
      onCreated(body.lead_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not add the lead. Please try again.");
      setBusy(false);
    }
  }
  return (
    <div className="aur-sheet-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <aside className="aur-sheet" role="dialog" aria-modal="true" aria-label="New lead" onKeyDown={event => { if (event.key === "Escape" && !busy) onClose(); }}>
        <div className="aur-sheet-head">
          <div><strong>New lead</strong><small className="aur-muted">Added in the CRM only</small></div>
          <button type="button" className="aur-icon-btn" aria-label="Close" disabled={busy} onClick={onClose}><Icon name="close" size={16} /></button>
        </div>
        <form className="aur-sheet-body aur-new-lead" onSubmit={save}>
          <label className="aur-field">Company
            <select required value={form.company_id} disabled={busy} onChange={set("company_id")}>
              <option value="" disabled>Choose a company</option>
              {companies.map(company => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
          </label>
          <label className="aur-field">Full name<input required autoFocus maxLength={255} value={form.full_name} disabled={busy} onChange={set("full_name")} /></label>
          <div className="aur-new-lead-row">
            <label className="aur-field">Phone<input type="tel" maxLength={40} value={form.phone} disabled={busy} onChange={set("phone")} /></label>
            <label className="aur-field">Email<input type="email" maxLength={255} value={form.email} disabled={busy} onChange={set("email")} /></label>
          </div>
          <label className="aur-field">Moving from<input maxLength={500} placeholder="Address, city or ZIP" value={form.pickup_zip} disabled={busy} onChange={set("pickup_zip")} /></label>
          <label className="aur-field">Moving to<input maxLength={500} placeholder="Address, city or ZIP" value={form.delivery_zip} disabled={busy} onChange={set("delivery_zip")} /></label>
          <div className="aur-new-lead-row">
            <label className="aur-field">Move date<input type="date" value={form.move_date} disabled={busy} onChange={set("move_date")} /></label>
            <label className="aur-field">Move size<input maxLength={120} placeholder="e.g. 2 Bedrooms" value={form.move_size} disabled={busy} onChange={set("move_size")} /></label>
          </div>
          <label className="aur-field">Referral source<input maxLength={255} value={form.referral_source} disabled={busy} onChange={set("referral_source")} /></label>
          <label className="aur-field">Rep
            <select value={form.assigned_to} disabled={busy} onChange={set("assigned_to")}>
              <option value="">Unassigned</option>
              {reps.map(rep => <option key={rep.id} value={rep.id}>{rep.name}</option>)}
            </select>
          </label>
          <label className="aur-field">Notes<textarea rows={4} maxLength={5000} value={form.notes} disabled={busy} onChange={set("notes")} /></label>
          {error && <p className="aur-alert" role="alert">{error}</p>}
          <div className="aur-new-lead-actions">
            <button type="button" className="aur-btn is-ghost" disabled={busy} onClick={onClose}>Cancel</button>
            <button type="submit" className="aur-btn is-primary" disabled={busy || !form.company_id || !form.full_name.trim()}>{busy ? "Adding…" : "Add lead"}</button>
          </div>
        </form>
      </aside>
    </div>
  );
}
