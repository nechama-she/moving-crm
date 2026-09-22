import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import "./InventoryCatalogPage.css";

export type CatalogItem = { id: string; name: string; description: string; cuft: number; weight: number; active: boolean };

export default function CatalogItemDialog({ item, initialName = "", onClose, onSaved }: {
  item?: CatalogItem; initialName?: string; onClose: () => void; onSaved: (item: CatalogItem) => void;
}) {
  const { token } = useAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(item?.name || initialName);
  const [description, setDescription] = useState(item?.description || "");
  const [cuft, setCuft] = useState(item ? String(item.cuft) : "");
  const [weight, setWeight] = useState(item ? String(item.weight) : "0");
  const [active, setActive] = useState(item?.active ?? true);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const saving = useRef(false);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (saving.current) return;
    saving.current = true; setBusy(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/inventory-catalog${item ? `/${encodeURIComponent(item.id)}` : ""}`, {
        method: item ? "PUT" : "POST", headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, cuft, weight, active }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Check the item name, volume, and weight, then try again.");
      onSaved(body);
    } catch (e) { setError((e as Error).message); }
    finally { saving.current = false; setBusy(false); }
  }
  return createPortal(<dialog className="ic-dialog" ref={dialog} aria-labelledby="ic-dialog-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={save}>
      <header className="ic-toolbar"><h2 id="ic-dialog-title">{item ? "Edit catalog item" : "Add catalog item"}</h2><button type="button" className="slds-button slds-button_neutral" onClick={onClose} disabled={busy} aria-label="Close item editor">Close</button></header>
      <p>Catalog items are shared across companies.</p>
      <fieldset disabled={busy}>
        <label>Item name<input autoFocus required maxLength={255} value={name} onChange={e => setName(e.target.value)} /></label>
        <div className="ic-measurements">
          <label>Volume per item (cu ft)<input type="number" required min="0.01" max="10000" step="0.01" value={cuft} onChange={e => setCuft(e.target.value)} /></label>
          <label>Weight per item (lb)<input type="number" required min="0" max="1000000" step="0.01" value={weight} onChange={e => setWeight(e.target.value)} /></label>
        </div>
        <label>Description (optional)<textarea maxLength={2000} value={description} onChange={e => setDescription(e.target.value)} /></label>
        {item && <label className="ic-checkbox"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} /> Available for new selections</label>}
      </fieldset>
      {error && <p role="alert" className="ic-error">{error}</p>}
      <footer className="ic-actions"><button type="button" className="slds-button slds-button_neutral" disabled={busy} onClick={onClose}>Cancel</button><button className="slds-button slds-button_brand" disabled={busy}>{busy ? "Saving..." : item ? "Save item" : "Add item"}</button></footer>
    </form>
  </dialog>, document.body);
}
