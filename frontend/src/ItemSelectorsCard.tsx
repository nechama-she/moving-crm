import {useEffect, useState} from 'react';
import {API_BASE} from './apiConfig';
import {authHeaders, useAuth} from './AuthContext';
import './ItemMaterialsCard.css';

export type ItemSelector = {id:string; label:string; options:string[]; default?:string; prices?:(string|number|null)[]};
type Row = ItemSelector & {item_ids:string[]};
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
    const cleaned = rows.map(row => ({...row, label:row.label || 'Service', options:row.options.map(o => o.trim()), default:(row.default || row.options[0] || '').trim(), prices:row.options.map((_, i) => row.prices?.[i] === '' ? null : row.prices?.[i] ?? null)}));
    if (cleaned.some(row => row.prices.some(price => price !== null && (!Number.isFinite(Number(price)) || Number(price) < 0 || Number(price) > 1000000 || Math.abs(Number(price) * 100 - Math.round(Number(price) * 100)) > 0.000001)))) {
      setError('Enter a valid price with up to two decimal places, or leave it blank.'); return;
    }
    if (cleaned.some(row => !row.options.length || row.options.length > 50 || row.options.some(o => !o || o.length > 200) || new Set(row.options.map(o => o.toLowerCase())).size !== row.options.length || !row.options.includes(row.default || ''))) {
      setError('Enter 1–50 unique options and choose a default from those options.'); return;
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
  const current = rows.find(row => row.id === selected) || rows[0];
  const visibleServices = editing ? (current ? [current] : []) : rows;
  const update = (id:string, changes:Partial<Row>) => setRows(values => values.map(row => row.id === id ? {...row, ...changes} : row));
  return <section className="pricing-card pricing-section pricing-item-services">
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
      <p>Configure a service once, then attach it to any items in this pricing sheet. Changes apply to every attached item.</p>
      {!data && !error && <p>Loading...</p>}
      <fieldset disabled={busy || blocked} style={{border:0, padding:0, minWidth:0}}>
        {editing && <button type="button" className="slds-button" disabled={rows.length >= 1000} onClick={() => {const id = crypto.randomUUID(); setRows(values => [...values, {id, item_ids:[], label:'New service', options:['']}]); setSelected(id); setSearch('');}}>+ Configure service</button>}
        <div className={editing ? 'pricing-catalog-browser' : undefined}>
          {editing && <nav className="pricing-catalog-list" aria-label="Configured services">{rows.map(row => <button key={row.id} type="button" aria-current={row.id === current?.id ? 'true' : undefined} onClick={() => {setSelected(row.id); setSearch('');}}><span>{row.label}</span><small>{row.item_ids.length} items</small></button>)}</nav>}
          <div style={{minWidth:0}}>
            {!rows.length && <p>No services configured. Add a service to get started.</p>}
            {visibleServices.map(row => <section key={row.id} style={{padding:12}}>
              <div className="pricing-item-service-form">
                {editing ? <>
                  <label>Service name<input type="text" className="slds-input" maxLength={200} value={row.label} placeholder="e.g. TV unmounting" onChange={e => update(row.id, {label:e.target.value})}/></label>
                  <div className="pricing-service-option-heading"><strong>Options</strong><span>Price ($)<small>Per item · optional</small></span><span>Default</span><span /></div>
                  <div role="radiogroup" aria-label="Default option" className="pricing-service-options">
                    {row.options.map((option, index) => {
                      const defaultIndex = row.default ? row.options.indexOf(row.default) : 0;
                      return <div className="pricing-service-option-row" key={index}>
                        <input className="slds-input" type="text" maxLength={200} aria-label={`Option ${index + 1}`} placeholder="Enter option" value={option} onChange={e => update(row.id, {options:row.options.map((value, i) => i === index ? e.target.value : value), ...(defaultIndex === index ? {default:e.target.value} : {})})}/>
                        <input className="slds-input" type="number" min="0" max="1000000" step="0.01" aria-label={`Price for option ${index + 1}`} placeholder="No charge" value={row.prices?.[index] ?? ''} onChange={e => update(row.id, {prices:row.options.map((_, i) => i === index ? e.target.value : row.prices?.[i] ?? null)})}/>
                        <label className="pricing-service-default" title="Use as default"><input type="radio" name={`default-${row.id}`} aria-label={`Use ${option || `option ${index + 1}`} as default`} disabled={!option.trim()} checked={defaultIndex === index} onChange={() => update(row.id, {default:option})}/></label>
                        <button type="button" className="slds-button ld-box-icon" disabled={row.options.length === 1} aria-label={`Remove option ${index + 1}`} title="Remove option" onClick={() => {
                          const options = row.options.filter((_, i) => i !== index);
                          update(row.id, {options, prices:row.options.map((_, i) => row.prices?.[i] ?? null).filter((_, i) => i !== index), default:defaultIndex === index ? options[0] : row.default});
                        }}>&times;</button>
                      </div>;
                    })}
                  </div>
                  <button type="button" className="slds-button" disabled={row.options.length >= 50} onClick={() => update(row.id, {options:[...row.options, '']})}>+ Add option</button>
                  <button type="button" className="slds-button" onClick={() => setRows(values => values.filter(value => value.id !== row.id))}>Remove service</button>
                </> : <ul className="pricing-service-option-summary">{row.options.map((option, index) => <li key={option}><span>{option}</span><span>{row.prices?.[index] != null && row.prices[index] !== '' ? `$${Number(row.prices[index]).toFixed(2)}` : 'No charge'}</span>{option === (row.default || row.options[0]) && <small>Default</small>}</li>)}</ul>}
              </div>
              <strong>Attached items ({row.item_ids.length})</strong>
              {editing ? <>
                <div className="pricing-item-material-search"><input className="slds-input" type="search" aria-label="Search items to attach" placeholder="Search items to attach" value={search} onChange={e => setSearch(e.target.value)}/></div>
                <div className="pricing-service-attach-actions"><button type="button" className="slds-button" disabled={!matches.length} onClick={() => update(row.id, {item_ids:Array.from(new Set([...row.item_ids, ...matches.map(item => item.id)]))})}>Attach all matching</button><button type="button" className="slds-button" disabled={!matches.some(item => row.item_ids.includes(item.id))} onClick={() => update(row.id, {item_ids:row.item_ids.filter(id => !matches.some(item => item.id === id))})}>Detach matching</button></div>
                <div className="pricing-service-attachments">{matches.map(item => <label key={item.id}><input type="checkbox" checked={row.item_ids.includes(item.id)} onChange={e => update(row.id, {item_ids:e.target.checked ? [...row.item_ids,item.id] : row.item_ids.filter(id => id !== item.id)})}/><span>{item.name} · {item.cuft} cu ft</span></label>)}{!matches.length && <p>No matching items.</p>}</div>
              </> : <><strong>{row.label}</strong><p>{row.item_ids.map(id => data?.items.find(item => item.id === id)?.name || 'Unavailable item').join(', ') || 'No items attached'}</p></>}
            </section>)}
          </div>
        </div>
      </fieldset>
    </div>}
  </section>;
}
