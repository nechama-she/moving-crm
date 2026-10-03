import {useEffect, useRef, useState} from 'react';
import {API_BASE} from './apiConfig';
import {authHeaders, useAuth} from './AuthContext';
import './ItemMaterialsCard.css';
type Row={item_id:string;material_id:string;requirement:'required'|'optional';quantity:string|number};
type DefaultRow={material_id:string;requirement:'required'|'optional';quantity:string|number};
type Setup={rows:Row[];defaults:DefaultRow[];items:{id:string;name:string}[];materials:{id:string;name:string}[];protection_review?:{item_id:string;name:string;reason:string}[]};

export default function ItemMaterialsCard({planId,blocked}:{planId:string;blocked:boolean}) {
  const {token,user}=useAuth();
  const [open,setOpen]=useState(false),[editing,setEditing]=useState(false),[busy,setBusy]=useState(false);
  const [data,setData]=useState<Setup|null>(null),[rows,setRows]=useState<Row[]>([]),[defaults,setDefaults]=useState<DefaultRow[]>([]);
  const [search,setSearch]=useState(''),[selected,setSelected]=useState(''),[error,setError]=useState('');
  const form=useRef<HTMLFormElement>(null);
  useEffect(()=>{
    const controller=new AbortController();
    fetch(`${API_BASE}/api/pricing/${encodeURIComponent(planId)}/item-materials`,{headers:authHeaders(token),signal:controller.signal})
      .then(async r=>{if(!r.ok)throw new Error('Could not load item materials.');return r.json();})
      .then(body=>{setData(body);setRows(body.rows);setDefaults(body.defaults||[]);})
      .catch(e=>{if(e.name!=='AbortError')setError(e.message);});
    return ()=>controller.abort();
  },[planId,token]);
  async function save() {
    if(busy)return;
    const invalid=[...rows,...defaults].find(row=>!row.material_id || !Number.isFinite(Number(row.quantity)) || Number(row.quantity)<=0 || Number(row.quantity)>10000);
    if(invalid){setSearch('');if('item_id' in invalid)setSelected(String(invalid.item_id));setError('Choose a material and a valid quantity for this item.');return;}
    if(!form.current?.reportValidity())return;
    setBusy(true);setError('');
    try {
      const response=await fetch(`${API_BASE}/api/pricing/${encodeURIComponent(planId)}/item-materials`,{method:'PUT',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify({rows,defaults})});
      const body=await response.json();
      if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Check the materials and quantities.');
      setData(body);setRows(body.rows);setDefaults(body.defaults||[]);setEditing(false);setSelected('');
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  const words=search.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const matches=(data?.items||[]).filter(item=>words.every(word=>item.name.toLowerCase().includes(word)));
  const current=matches.find(item=>item.id===selected)||matches[0];
  const position=matches.findIndex(item=>item.id===current?.id);
  const ids=editing?(current?[current.id]:[]):Array.from(new Set(rows.map(row=>row.item_id)));
  const update=(index:number,patch:Partial<Row>)=>setRows(rows.map((row,i)=>i===index?{...row,...patch}:row));
  const updateDefault=(index:number,patch:Partial<DefaultRow>)=>setDefaults(defaults.map((row,i)=>i===index?{...row,...patch}:row));
  return <section className="pricing-card pricing-section">
    <div className="pricing-section-heading">
      <button type="button" className="slds-button pricing-section-title" onClick={()=>setOpen(!open)}><span><strong>Item packing materials</strong><small>{new Set(rows.map(row=>row.item_id)).size}</small></span></button>
      <div className="pricing-section-actions">
        {user?.role==='admin' && (editing?<>
          <button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={busy} onClick={()=>{setRows(data?.rows||[]);setDefaults(data?.defaults||[]);setSelected('');setEditing(false);setError('');}}>Cancel changes</button>
          <button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={busy || blocked} onClick={()=>void save()}>{busy?'Saving...':'Save changes'}</button>
        </>:<button type="button" className="slds-button pricing-section-action" aria-label="Edit item packing materials" title="Edit" disabled={!data || blocked} onClick={()=>{setEditing(true);setOpen(true);}}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m16 3 5 5L8 21H3v-5L16 3Z" /><path d="m13 6 5 5" /></svg></button>)}
        <button type="button" className="slds-button pricing-section-toggle" aria-label={open?'Collapse item packing materials':'Expand item packing materials'} onClick={()=>setOpen(!open)}>{open?'\u2212':'+'}</button>
      </div>
    </div>
    {open && <div className="pricing-section-body">
      {error && <p role="alert">{error}</p>}
      {!!data?.protection_review?.length && <details><summary>{data.protection_review.length} items need packing material review</summary><ul>{data.protection_review.map(item=><li key={item.item_id}><strong>{item.name}</strong>: {item.reason}</li>)}</ul></details>}
      {!data && !error && <p role="status">Loading...</p>}
      {data && <form ref={form} onSubmit={e=>{e.preventDefault();void save();}}>
        <fieldset disabled={busy || blocked} style={{border:0,padding:0,minWidth:0}}>
          <section className="pricing-default-materials">
            <div className="pricing-default-materials-title"><div><strong>Default materials</strong><small>Used only when an inventory item has no item-specific materials.</small></div></div>
            <div className="pricing-item-material-groups">
              {(['required','optional'] as const).map(requirement=><div key={requirement}>
                <div className="pricing-item-material-heading"><span>{requirement==='required'?'Required materials':'Optional materials'}</span>
                  {editing && <button type="button" className="slds-button ld-box-icon" title="Add default material" aria-label={`Add default ${requirement} material`} disabled={!data.materials.length} onClick={()=>setDefaults([...defaults,{material_id:'',requirement,quantity:1}])}>+</button>}
                </div>
                {defaults.map((row,index)=>row.requirement===requirement && <div className="pricing-item-material-row" key={index}>
                  {editing?<>
                    <select required className="slds-select" aria-label={`Default ${requirement} material`} value={row.material_id} onChange={e=>updateDefault(index,{material_id:e.target.value})}>
                      <option value="">Select material</option>
                      {row.material_id && !data.materials.some(material=>material.id===row.material_id) && <option value={row.material_id}>Unavailable material (saved)</option>}
                      {data.materials.map(material=><option key={material.id} value={material.id} disabled={defaults.some((entry,i)=>i!==index && entry.material_id===material.id)}>{material.name}</option>)}
                    </select>
                    <input required className="slds-input" type="number" min="0.01" max="10000" step="0.01" aria-label="Default quantity per item" title="Quantity per item" value={row.quantity} onChange={e=>updateDefault(index,{quantity:e.target.value})}/>
                    <button type="button" className="slds-button ld-box-icon" title="Remove default material" aria-label="Remove default material" onClick={()=>setDefaults(defaults.filter((_,i)=>i!==index))}>&times;</button>
                  </>:<><span>{data.materials.find(material=>material.id===row.material_id)?.name || 'Unavailable material (saved)'}</span><span>{row.quantity} / item</span></>}
                </div>)}
                {!defaults.some(row=>row.requirement===requirement) && <small>None</small>}
              </div>)}
            </div>
          </section>
          {editing && <div className="pricing-item-material-search">
            <input className="slds-input" type="search" placeholder="Search catalog items" aria-label="Search catalog items" value={search} onChange={e=>setSearch(e.target.value)}/>
            <div className="pricing-catalog-navigation">
              <button type="button" className="slds-button ld-box-icon" aria-label="Previous catalog item" title="Previous item" disabled={position<=0} onClick={()=>setSelected(matches[position-1].id)}>&larr;</button>
              <span>{current?position+1:0} of {matches.length}</span>
              <button type="button" className="slds-button ld-box-icon" aria-label="Next catalog item" title="Next item" disabled={position<0 || position>=matches.length-1} onClick={()=>setSelected(matches[position+1].id)}>&rarr;</button>
            </div>
          </div>}
          <div className={editing?'pricing-catalog-browser':undefined}>
          {editing && <nav className="pricing-catalog-list" aria-label="Catalog items">
            {matches.map(item=><button type="button" key={item.id} aria-current={current?.id===item.id?'true':undefined} onClick={()=>setSelected(item.id)}>
              <span>{item.name}</span><small>{rows.filter(row=>row.item_id===item.id).length || ''}</small>
            </button>)}
            {!matches.length && <p>No matching items.</p>}
          </nav>}
          <div style={{minWidth:0}}>
          {!ids.length && !editing && <p>No item materials configured.</p>}
          {ids.map(id=><div key={id} style={{borderTop:'1px solid #dddbda',padding:'16px 0'}}>
            <strong>{data.items.find(item=>item.id===id)?.name || 'Unavailable catalog item'}</strong>
            <div className="pricing-item-material-groups">
              {(['required','optional'] as const).map(requirement=><div key={requirement}>
                <div className="pricing-item-material-heading"><span>{requirement==='required'?'Required materials':'Optional materials'}</span>
                  {editing && <button type="button" className="slds-button ld-box-icon" title="Add material" aria-label={`Add ${requirement} material`} disabled={!data.materials.length} onClick={()=>setRows([...rows,{item_id:id,material_id:'',requirement,quantity:1}])}>+</button>}
                </div>
                {rows.map((row,index)=>row.item_id===id && row.requirement===requirement && <div className="pricing-item-material-row" key={index}>
                  {editing?<>
                    <select required className="slds-select" aria-label={`${requirement} material`} value={row.material_id} onChange={e=>update(index,{material_id:e.target.value})}>
                      <option value="">Select material</option>
                      {row.material_id && !data.materials.some(material=>material.id===row.material_id) && <option value={row.material_id}>Unavailable material (saved)</option>}
                      {data.materials.map(material=><option key={material.id} value={material.id} disabled={rows.some((entry,i)=>i!==index && entry.item_id===id && entry.material_id===material.id)}>{material.name}</option>)}
                    </select>
                    <input required className="slds-input" type="number" min="0.01" max="10000" step="0.01" aria-label="Quantity per item" title="Quantity per item" value={row.quantity} onChange={e=>update(index,{quantity:e.target.value})}/>
                    <button type="button" className="slds-button ld-box-icon" title="Remove material" aria-label="Remove material" onClick={()=>setRows(rows.filter((_,i)=>i!==index))}>&times;</button>
                  </>:<><span>{data.materials.find(material=>material.id===row.material_id)?.name || 'Unavailable material (saved)'}</span><span>{row.quantity} / item</span></>}
                </div>)}
                {!rows.some(row=>row.item_id===id && row.requirement===requirement) && <small>None</small>}
              </div>)}
            </div>
          </div>)}
          </div>
          </div>
        </fieldset>
      </form>}
    </div>}
  </section>;
}
