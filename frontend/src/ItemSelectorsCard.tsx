import {useEffect, useState} from 'react';
import {API_BASE} from './apiConfig';
import {authHeaders, useAuth} from './AuthContext';
import './ItemMaterialsCard.css';

export type ItemSelector = {id:string; label:string; options:string[]};
type Row = ItemSelector & {item_id:string};
type Setup = {rows:Row[]; items:{id:string; name:string; cuft:number}[]};

export default function ItemSelectorsCard({planId, blocked}:{planId:string; blocked:boolean}) {
  const {token, user} = useAuth();
  const [data, setData] = useState<Setup|null>(null), [rows, setRows] = useState<Row[]>([]);
  const [open, setOpen] = useState(false), [editing, setEditing] = useState(false), [busy, setBusy] = useState(false);
  const [search, setSearch] = useState(''), [selected, setSelected] = useState(''), [error, setError] = useState('');
  const endpoint = `${API_BASE}/api/pricing/${encodeURIComponent(planId)}/item-selectors`;
  useEffect(() => {
    const controller = new AbortController();
    fetch(endpoint, {headers:authHeaders(token), signal:controller.signal})
      .then(async response => {if (!response.ok) throw new Error('Could not load item services.'); return response.json();})
      .then(body => {setData(body); setRows(body.rows);})
      .catch(e => {if (e.name !== 'AbortError') setError(e.message);});
    return () => controller.abort();
  }, [endpoint, token]);
  async function save() {
    const cleaned = rows.map(row => ({...row, label:row.label.trim(), options:row.options.map(o => o.trim()).filter(Boolean)}));
    if (cleaned.some(row => !row.label || !row.options.length || row.options.length > 50 || row.options.some(o => o.length > 200) || new Set(row.options.map(o => o.toLowerCase())).size !== row.options.length) || new Set(cleaned.map(row => `${row.item_id}:${row.label.toLowerCase()}`)).size !== cleaned.length) {
      setError('Use unique service names per item and 1–50 unique options, up to 200 characters each.'); return;
    }
    if (busy) return;
    setBusy(true); setError('');
    try {
      const response = await fetch(endpoint, {method:'PUT', headers:{...authHeaders(token), 'Content-Type':'application/json'}, body:JSON.stringify({rows:cleaned})});
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Check the service names and options.');
      setData(body); setRows(body.rows); setEditing(false);
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  const matches = (data?.items || []).filter(item => search.toLowerCase().trim().split(/\s+/).every(word => item.name.toLowerCase().includes(word)));
  const current = matches.find(item => item.id === selected) || matches[0];
  const itemIds = editing ? (current ? [current.id] : []) : Array.from(new Set(rows.map(row => row.item_id)));
  const update = (id:string, changes:Partial<Row>) => setRows(values => values.map(row => row.id === id ? {...row, ...changes} : row));
  return <section className="pricing-card pricing-section">
    <div className="pricing-section-heading">
      <button type="button" className="slds-button pricing-section-title" onClick={() => setOpen(!open)}><span><strong>Item services</strong><small>{rows.length}</small></span></button>
      {user?.role === 'admin' && <div className="pricing-section-actions">
        {editing ? <>
          <button type="button" className="slds-button" disabled={busy} onClick={() => {setRows(data?.rows || []); setEditing(false); setError('');}}>Cancel changes</button>
          <button type="button" className="slds-button" disabled={busy || blocked} onClick={() => void save()}>{busy ? 'Saving...' : 'Save changes'}</button>
        </> : <button type="button" className="slds-button" disabled={!data || blocked} onClick={() => {setEditing(true); setOpen(true);}}>Edit</button>}
      </div>}
    </div>
    {error && <p role="alert">{error}</p>}
    {open && <div className="pricing-section-body">
      <p>Choose an item and define the options shown on its inventory rows for this pricing sheet.</p>
      {!data && !error && <p>Loading...</p>}
      <fieldset disabled={busy || blocked} style={{border:0, padding:0, minWidth:0}}>
        {editing && <input className="slds-input" type="search" aria-label="Search service items" placeholder="Search items" value={search} onChange={e => setSearch(e.target.value)}/>}
        <div className={editing ? 'pricing-catalog-browser' : undefined}>
          {editing && <nav className="pricing-catalog-list" aria-label="Service items">{matches.map(item => <button key={item.id} type="button" aria-current={item.id === current?.id ? 'true' : undefined} onClick={() => setSelected(item.id)}><span>{item.name} · {item.cuft} cu ft</span><small>{rows.filter(row => row.item_id === item.id).length || ''}</small></button>)}{!matches.length && <p>No matching items.</p>}</nav>}
          <div style={{minWidth:0}}>
            {!itemIds.length && !editing && <p>No item services configured.</p>}
            {itemIds.map(itemId => <section key={itemId} style={{padding:12}}>
              <strong>{data?.items.find(item => item.id === itemId)?.name || 'Unavailable item'}</strong>
              {rows.filter(row => row.item_id === itemId).map(row => <div key={row.id} style={{margin:'12px 0'}}>
                {editing ? <>
                  <label>Service name<input className="slds-input" maxLength={200} value={row.label} placeholder="Unmounting" onChange={e => update(row.id, {label:e.target.value})}/></label>
                  <label>Options (one per line)<textarea className="slds-textarea" rows={3} value={row.options.join('\n')} placeholder={'Owner Unmounts\nMovers Unmount'} onChange={e => update(row.id, {options:e.target.value.split('\n')})}/></label>
                  <button type="button" className="slds-button" onClick={() => setRows(values => values.filter(value => value.id !== row.id))}>Remove service</button>
                </> : <><strong>{row.label}</strong><div>{row.options.join(' / ')}</div></>}
              </div>)}
              {editing && <button type="button" className="slds-button" disabled={rows.filter(row => row.item_id === itemId).length >= 30 || rows.length >= 1000} onClick={() => setRows(values => [...values, {id:crypto.randomUUID(), item_id:itemId, label:'', options:['']}])}>Add service</button>}
            </section>)}
          </div>
        </div>
      </fieldset>
    </div>}
  </section>;
}
