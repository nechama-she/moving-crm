import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { API_BASE } from './apiConfig';
import { authHeaders, useAuth } from './AuthContext';
import CatalogItemDialog, { type CatalogItem } from './CatalogItemDialog';
import './BulkyCatalogPicker.css';

export default function BulkyCatalogPicker({ initialName, onSelect, onClose, onSelectMany }: {
  onSelectMany?: (items: CatalogItem[]) => void;
  initialName: string; onSelect: (item: CatalogItem) => void; onClose: () => void;
}) {
  const { token } = useAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const [search, setSearch] = useState(initialName);
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<CatalogItem[]>([]);
  const [adding, setAdding] = useState(false);
  useEffect(() => { const el = dialog.current; el?.showModal(); return () => el?.close(); }, []);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true); setError('');
    fetch(`${API_BASE}/api/inventory-catalog`, { headers: authHeaders(token), signal: abort.signal })
      .then(async response => { if (!response.ok) throw new Error('Could not load the catalog.'); return response.json(); })
      .then(body => { if (!abort.signal.aborted) setItems(body.items); })
      .catch(e => { if (!abort.signal.aborted) setError(e.message); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [token, retry]);
  const shown = items.filter(item => item.active && `${item.name} ${item.description}`.toLowerCase().includes(search.trim().toLowerCase()));
  return createPortal(<>
    <dialog ref={dialog} className="bulky-catalog-dialog" aria-labelledby="bulky-catalog-title" onCancel={onClose}>
      <header><h2 id="bulky-catalog-title">{onSelectMany ? 'Choose catalog items' : 'Choose a catalog item'}</h2><button type="button" className="slds-button" onClick={onClose}>Close</button></header>
      <label>Search catalog<input autoFocus type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search items" /></label>
      <button type="button" className="slds-button" onClick={() => setAdding(true)}>+ Add catalog item</button>
      {error && <p role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>Try again</button></p>}
      <div className="bulky-catalog-results">
        {loading ? <p role="status">Loading catalog...</p> : shown.map(item => onSelectMany ? <label key={item.id} className="bulky-catalog-option"><input type="checkbox" checked={selected.some(row => row.id === item.id)} onChange={e => setSelected(rows => e.target.checked ? [...rows,item] : rows.filter(row => row.id !== item.id))} /><span>{item.name}</span><small>{item.cuft} cu ft</small></label> : <button type="button" key={item.id} onClick={() => onSelect(item)}><span>{item.name}</span><small>{item.cuft} cu ft</small></button>)}
        {!loading && !error && !shown.length && <p>No matching items. Add a catalog item above.</p>}
      </div>
      {onSelectMany && <footer className="bulky-catalog-footer"><span aria-live="polite">{selected.length} selected</span><button type="button" className="slds-button" onClick={onClose}>Cancel</button><button type="button" className="slds-button slds-button_brand" disabled={!selected.length} onClick={() => onSelectMany(selected)}>Add selected items</button></footer>}
    </dialog>
    {adding && <CatalogItemDialog initialName={search} onClose={() => setAdding(false)} onSaved={item => { if (!onSelectMany) { onSelect(item); return; } setItems(rows => [...rows.filter(row => row.id !== item.id),item]); setSelected(rows => [...rows.filter(row => row.id !== item.id),item]); setAdding(false); }} />}
  </>, document.body);
}
