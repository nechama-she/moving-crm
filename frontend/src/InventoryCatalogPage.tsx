import { useEffect, useRef, useState } from "react";
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
  const [transferring, setTransferring] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);
  async function remove(item?: CatalogItem) {
    if (!window.confirm(item ? `Delete "${item.name}" from the catalog? Saved inventory records will be kept.` : 'Keep only the largest-volume item for each matching name and remove the other entries? The retained item keeps its own weight and settings. Saved records will be kept.')) return;
    setTransferring(true); setError(''); setNotice('');
    try {
      const response = await fetch(`${API_BASE}/api/inventory-catalog/${item ? encodeURIComponent(item.id) : 'deduplicate'}`, {
        method: item ? 'DELETE' : 'POST', headers: authHeaders(token),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not update the catalog.');
      setNotice(item ? `${item.name} deleted.` : `${result.removed} duplicate items removed.`);
      setRetry(value => value + 1);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not update the catalog.'); }
    finally { setTransferring(false); }
  }
  async function transfer(file?: File) {
    setTransferring(true); setError(""); setNotice("");
    try {
      const form = new FormData();
      if (file) form.append("file", file);
      const headers = new Headers(authHeaders(token));
      headers.delete("Content-Type");
      const response = await fetch(`${API_BASE}/api/inventory-catalog/${file ? "import" : "export"}`, {
        method: file ? "POST" : "GET", headers, ...(file ? { body: form } : {}),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : "Could not transfer the catalog. Please try again.");
      }
      if (file) {
        const result = await response.json();
        setNotice(`Catalog uploaded: ${result.created} items added, ${result.updated} items updated.`);
        setSearch(""); setRetry(value => value + 1);
      } else {
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url; link.download = "inventory-catalog.csv";
        document.body.appendChild(link); link.click(); link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        setNotice("Full catalog downloaded.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not transfer the catalog.");
    } finally {
      setTransferring(false);
      if (uploadInput.current) uploadInput.current.value = "";
    }
  }
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError("");
    fetch(`${API_BASE}/api/inventory-catalog`, { headers: authHeaders(token), signal: abort.signal })
      .then(async response => { if (!response.ok) throw new Error("Could not load the inventory catalog."); return response.json(); })
      .then(body => { if (!abort.signal.aborted) setItems(body.items); })
      .catch(e => { if (!abort.signal.aborted) setError(e.message); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [token, retry]);
  const searchWords = search.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const shown = items.filter(item => searchWords.every(word => `${item.name} ${item.description}`.toLowerCase().includes(word)))
    .sort((a, b) => a.name.localeCompare(b.name) || a.cuft - b.cuft);
  return <main className="ic-page">
    <Link to="/settings" className="slds-button">Back to Settings</Link>
    <section className="ic-card">
      <header className="ic-toolbar"><div><h1>Inventory catalog</h1><p>Manage shared items used in customer inventories and moving terms.</p></div><div className="ic-transfer-actions">
        <button className="slds-button slds-button_neutral" disabled={transferring || loading} onClick={() => void transfer()}>Download CSV</button>
        <button className="slds-button slds-button_neutral" disabled={transferring || loading} onClick={() => uploadInput.current?.click()}>Upload CSV</button>
        <button className="slds-button slds-button_neutral" disabled={transferring || loading} onClick={() => void remove()}>Remove duplicates</button>
        <input ref={uploadInput} type="file" accept=".csv,text/csv" hidden aria-label="Upload inventory catalog CSV" onChange={e => { const file = e.target.files?.[0]; if (file) void transfer(file); }} />
        <button className="slds-button slds-button_brand" disabled={transferring} onClick={() => setEditing("new")}>+ Add item</button>
      </div></header>
      <p>Upload updates matching IDs, or matches by item name and volume when IDs are blank. Capitalization and spacing around punctuation are ignored. New items are added; repeated identical rows are imported once. Items omitted from the file are kept.</p>
      {transferring && <p role="status">Updating catalog...</p>}
      <label className="ic-search">Search catalog<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by item name or description" /></label>
      {notice && <p role="status" className="ic-notice">{notice}</p>}
      {error && <p role="alert" className="ic-error">{error} <button className="slds-button" onClick={() => setRetry(value => value + 1)}>Try again</button></p>}
      {loading ? <p role="status">Loading catalog...</p> : <>
        <p>{shown.length} items</p>
        <div className="ic-table-wrap"><table><thead><tr><th>Item</th><th>Cu ft / item</th><th>Lb / item</th><th>Status</th><th><span className="slds-assistive-text">Actions</span></th></tr></thead><tbody>{shown.map(item => <tr key={item.id}><td><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</td><td>{item.cuft.toLocaleString()}</td><td>{item.weight.toLocaleString()}</td><td>{item.active ? "Active" : "Inactive"}</td><td><button className="slds-button slds-button_neutral" disabled={transferring} aria-label={`Edit ${item.name}`} onClick={() => setEditing(item)}>Edit</button><button className="slds-button slds-button_destructive" disabled={transferring} aria-label={`Delete ${item.name}`} onClick={() => void remove(item)}>Delete</button></td></tr>)}</tbody></table></div>
        {!shown.length && !error && <p>No items match your search. Use Add item to create one.</p>}
      </>}
    </section>
    {editing && <CatalogItemDialog item={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={item => { setItems(current => [...current.filter(row => row.id !== item.id), item]); setSearch(item.name); setNotice(`${item.name} saved to the catalog.`); setEditing(null); }} />}
  </main>;
}
