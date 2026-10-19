import { useEffect, useState } from 'react';
import { API_BASE } from './apiConfig';
import { authHeaders, useAuth } from './AuthContext';

export type CatalogSet = {id: string; name: string; components: {item_id: string; quantity: number}[]};
type Item = {id: string; name: string; cuft: number; active: boolean};

export default function CatalogSets({items}: {items: Item[]}) {
  const {token} = useAuth();
  const [sets, setSets] = useState<CatalogSet[]>([]);
  const [draft, setDraft] = useState<CatalogSet | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    fetch(`${API_BASE}/api/inventory-catalog/sets`, {headers: authHeaders(token), signal: abort.signal})
      .then(async response => {if (!response.ok) throw new Error('Could not load sets.'); return response.json();})
      .then(data => {if (!abort.signal.aborted) {setSets(data.sets); setError('');}})
      .catch(err => {if (!abort.signal.aborted) setError(err.message);})
      .finally(() => {if (!abort.signal.aborted) setLoading(false);});
    return () => abort.abort();
  }, [token, retry]);
  const lookup = new Map(items.map(item => [item.id, item]));
  const total = (set: CatalogSet) => set.components.reduce((sum, part) => sum + (lookup.get(part.item_id)?.cuft || 0) * part.quantity, 0);
  async function save(remove?: CatalogSet) {
    const value = remove || draft;
    if (!value) return;
    if (remove && !window.confirm(`Delete the preset "${remove.name}"? Existing inventories will keep their pieces.`)) return;
    setBusy(true); setError('');
    try {
      const response = await fetch(`${API_BASE}/api/inventory-catalog/sets${value.id ? `/${encodeURIComponent(value.id)}` : ''}`, {
        method: remove ? 'DELETE' : value.id ? 'PUT' : 'POST', headers: {...authHeaders(token), 'Content-Type': 'application/json'},
        ...(remove ? {} : {body: JSON.stringify({name: value.name, components: value.components})}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the set name, items and quantities.');
      setSets(current => remove ? current.filter(row => row.id !== value.id) : [...current.filter(row => row.id !== data.id), data]);
      if (!remove || draft?.id === remove.id) setDraft(null);
    } catch (err) {setError(err instanceof Error ? err.message : 'Could not save set.');}
    finally {setBusy(false);}
  }
  return <section className="ic-card ic-sets">
    <header className="ic-toolbar"><div><h2>Item sets</h2><p>Suggested pieces people can add together, then adjust individually.</p></div>
      <button className="slds-button slds-button_brand" disabled={busy || loading} onClick={() => setDraft({id: '', name: '', components: [{item_id: '', quantity: 1}]})}>Add set</button>
    </header>
    {error && <p className="ic-error" role="alert">{error} <button className="slds-button" onClick={() => setRetry(value => value + 1)}>Reload sets</button></p>}
    {draft && <form className="ic-set-editor" onSubmit={event => {event.preventDefault(); void save();}}>
      <label>Set name<input required maxLength={200} value={draft.name} placeholder="King bedroom set" disabled={busy} onChange={event => setDraft({...draft, name: event.target.value})}/></label>
      {draft.components.map((part, index) => <div className="ic-set-piece" key={index}>
        <label>Included item<select required disabled={busy} value={part.item_id} onChange={event => setDraft({...draft, components: draft.components.map((row, i) => i === index ? {...row, item_id: event.target.value} : row)})}>
          <option value="">Choose an item</option>
          {items.filter(item => item.active || item.id === part.item_id).map(item => <option key={item.id} value={item.id} disabled={draft.components.some((row, i) => i !== index && row.item_id === item.id)}>{item.name} ({item.cuft} cu ft)</option>)}
          {part.item_id && !lookup.has(part.item_id) && <option value={part.item_id}>Unavailable item - choose a replacement</option>}
        </select></label>
        <label>Quantity<input required type="number" min="1" max="999" step="1" disabled={busy} value={part.quantity || ''} onChange={event => setDraft({...draft, components: draft.components.map((row, i) => i === index ? {...row, quantity: Number(event.target.value)} : row)})}/></label>
        <span>{((lookup.get(part.item_id)?.cuft || 0) * part.quantity).toLocaleString()} cu ft</span>
        <button type="button" className="slds-button" disabled={busy} aria-label={`Remove piece ${index + 1}`} onClick={() => setDraft({...draft, components: draft.components.filter((_, i) => i !== index)})}>Remove</button>
      </div>)}
      <div className="ic-transfer-actions">
        <button type="button" className="slds-button slds-button_neutral" disabled={busy || draft.components.length >= 100} onClick={() => setDraft({...draft, components: [...draft.components, {item_id: '', quantity: 1}]})}>Add piece</button>
        <strong>Total: {total(draft).toLocaleString()} cu ft</strong>
        <button type="button" className="slds-button" disabled={busy} onClick={() => setDraft(null)}>Cancel</button>
        <button className="slds-button slds-button_brand" disabled={busy || !draft.components.length}>{busy ? 'Saving...' : 'Save set'}</button>
      </div>
    </form>}
    {loading ? <p>Loading sets...</p> : sets.length === 0 ? <p>No sets yet. Add one using existing catalog items.</p> :
      <div className="ic-set-list">{sets.map(set => <article key={set.id}>
        <h3>{set.name}</h3>
        <ul>{set.components.map(part => <li key={part.item_id}>{part.quantity} &times; {lookup.get(part.item_id)?.name || 'Unavailable item'} <small>{lookup.get(part.item_id)?.cuft || 0} cu ft each</small></li>)}</ul>
        <strong>{total(set).toLocaleString()} cu ft</strong>
        <div className="ic-transfer-actions"><button className="slds-button" disabled={busy} onClick={() => setDraft({...set, components: set.components.map(part => ({...part}))})}>Edit</button><button className="slds-button" disabled={busy} onClick={() => void save(set)}>Delete</button></div>
      </article>)}</div>}
  </section>;
}
