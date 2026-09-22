import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import CatalogItemDialog, { type CatalogItem } from "./CatalogItemDialog";
import "./InventoryCatalogPage.css";

export default function InventoryCatalogPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<CatalogItem | "new" | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError("");
    fetch(`${API_BASE}/api/inventory-catalog`, { headers: authHeaders(token), signal: abort.signal })
      .then(async response => { if (!response.ok) throw new Error("Could not load the inventory catalog."); return response.json(); })
      .then(body => { if (!abort.signal.aborted) setItems(body.items); })
      .catch(e => { if (!abort.signal.aborted) setError(e.message); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [token, retry]);
  const shown = items.filter(item => `${item.name} ${item.description}`.toLowerCase().includes(search.trim().toLowerCase()))
    .sort((a, b) => a.name.localeCompare(b.name) || a.cuft - b.cuft);
  return <main className="ic-page">
    <Link to="/settings" className="slds-button">Back to Settings</Link>
    <section className="ic-card">
      <header className="ic-toolbar"><div><h1>Inventory catalog</h1><p>Manage shared items used in customer inventories and moving terms.</p></div><button className="slds-button slds-button_brand" onClick={() => setEditing("new")}>+ Add item</button></header>
      <label className="ic-search">Search catalog<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by item name or description" /></label>
      {notice && <p role="status" className="ic-notice">{notice}</p>}
      {error && <p role="alert" className="ic-error">{error} <button className="slds-button" onClick={() => setRetry(value => value + 1)}>Try again</button></p>}
      {loading ? <p role="status">Loading catalog...</p> : <>
        <p>{shown.length} items</p>
        <div className="ic-table-wrap"><table><thead><tr><th>Item</th><th>Cu ft / item</th><th>Lb / item</th><th>Status</th><th><span className="slds-assistive-text">Actions</span></th></tr></thead><tbody>{shown.map(item => <tr key={item.id}><td><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</td><td>{item.cuft.toLocaleString()}</td><td>{item.weight.toLocaleString()}</td><td>{item.active ? "Active" : "Inactive"}</td><td><button className="slds-button slds-button_neutral" aria-label={`Edit ${item.name}`} onClick={() => setEditing(item)}>Edit</button></td></tr>)}</tbody></table></div>
        {!shown.length && !error && <p>No items match your search. Use Add item to create one.</p>}
      </>}
    </section>
    {editing && <CatalogItemDialog item={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={item => { setItems(current => [...current.filter(row => row.id !== item.id), item]); setSearch(item.name); setNotice(`${item.name} saved to the catalog.`); setEditing(null); }} />}
  </main>;
}
