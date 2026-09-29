import {useEffect, useRef, useState} from 'react';
import {API_BASE} from './apiConfig';
import {authHeaders, useAuth} from './AuthContext';
import './ItemMaterialsCard.css';
type Row={item_id:string;material_id:string;requirement:'required'|'optional';quantity:string|number};
type Setup={rows:Row[];items:{id:string;name:string}[];materials:{id:string;name:string}[]};

export default function ItemMaterialsCard({planId,blocked}:{planId:string;blocked:boolean}) {
  const {token,user}=useAuth();
  const [open,setOpen]=useState(false),[editing,setEditing]=useState(false),[busy,setBusy]=useState(false);
  const [data,setData]=useState<Setup|null>(null),[rows,setRows]=useState<Row[]>([]);
  const [search,setSearch]=useState(''),[selected,setSelected]=useState(''),[error,setError]=useState('');
  const form=useRef<HTMLFormElement>(null);
  useEffect(()=>{
    const controller=new AbortController();
    fetch(`${API_BASE}/api/pricing/${encodeURIComponent(planId)}/item-materials`,{headers:authHeaders(token),signal:controller.signal})
      .then(async r=>{if(!r.ok)throw new Error('Could not load item materials.');return r.json();})
      .then(body=>{setData(body);setRows(body.rows);})
      .catch(e=>{if(e.name!=='AbortError')setError(e.message);});
    return ()=>controller.abort();
  },[planId,token]);
  async function save() {
    if(busy || !form.current?.reportValidity())return;
    setBusy(true);setError('');
    try {
      const response=await fetch(`${API_BASE}/api/pricing/${encodeURIComponent(planId)}/item-materials`,{method:'PUT',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify({rows})});
      const body=await response.json();
      if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Check the materials and quantities.');
      setData(body);setRows(body.rows);setEditing(false);setSelected('');
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  const ids=Array.from(new Set([...rows.map(row=>row.item_id),...(selected?[selected]:[])]));
  const words=search.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const update=(index:number,patch:Partial<Row>)=>setRows(rows.map((row,i)=>i===index?{...row,...patch}:row));
  return <section className="pricing-card pricing-section">
    <div className="pricing-section-heading">
      <button type="button" className="slds-button pricing-section-title" onClick={()=>setOpen(!open)}><span><strong>Item packing materials</strong><small>{new Set(rows.map(row=>row.item_id)).size}</small></span></button>
      <div className="pricing-section-actions">
        {user?.role==='admin' && (editing?<>
          <button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={busy} onClick={()=>{setRows(data?.rows||[]);setSelected('');setEditing(false);setError('');}}>Cancel changes</button>
          <button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={busy || blocked} onClick={()=>void save()}>{busy?'Saving...':'Save changes'}</button>
        </>:<button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={!data || blocked} onClick={()=>{setEditing(true);setOpen(true);}}>Edit</button>)}
        <button type="button" className="slds-button pricing-section-toggle" aria-label={open?'Collapse item packing materials':'Expand item packing materials'} onClick={()=>setOpen(!open)}>{open?'-':'+'}</button>
      </div>
    </div>
    {open && <div className="pricing-section-body">
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p role="status">Loading...</p>}
      {data && <form ref={form} onSubmit={e=>{e.preventDefault();void save();}}>
        <fieldset disabled={busy || blocked} style={{border:0,padding:0,minWidth:0}}>
          {editing && <div className="pricing-item-material-search">
            <input className="slds-input" type="search" placeholder="Search catalog items" aria-label="Search catalog items" value={search} onChange={e=>setSearch(e.target.value)}/>
            <select className="slds-select" aria-label="Add catalog item" value={selected} onChange={e=>setSelected(e.target.value)}>
              <option value="">Choose an item</option>{data.items.filter(item=>words.every(word=>item.name.toLowerCase().includes(word))).map(item=><option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </div>}
          {!ids.length && <p>No item materials configured.</p>}
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
        </fieldset>
      </form>}
    </div>}
  </section>;
}
