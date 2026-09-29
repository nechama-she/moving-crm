import { useState } from 'react';
import type { AdditionalMaterialItem, PackingPackage, PackingSelection } from './CustomerPackingOptions';
const money=(value:number|null)=>Number(value||0).toLocaleString('en-US',{style:'currency',currency:'USD'});
export default function CustomerMaterialItems({config,selection,onChange,disabled}:{config:PackingPackage;selection:PackingSelection;onChange:(value:PackingSelection)=>void;disabled:boolean}) {
  const [search,setSearch]=useState('');
  const items=selection.additional_items||{};
  const available=(config.other_inventory||[]).filter(row=>!items[row.id] && !Object.values(items).some(item=>item.inventory_id===row.id));
  const searchWords=search.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const shown=available.filter(row=>searchWords.every(word=>`${row.room||''} ${row.label}`.toLowerCase().includes(word)));
  function save(id:string,item:AdditionalMaterialItem|null) {
    const next={...items};
    if(item)next[id]=item;else delete next[id];
    onChange({...selection,additional_items:next});
  }
  return <section className="cm-packing-items">
    <h4>Additional fabric or fragile items</h4>
    {Object.entries(items).map(([id,item])=>{
      const quote=config.material_quotes?.find(row=>row.id===id);
      return <section key={id} data-customer-action={`additional:${id}`} style={{borderBottom:'1px solid #e5d8d5',padding:'12px 0',display:'grid',gap:10}}>
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12}}>
          <strong>{item.label}</strong>
          <button type="button" className="cm-secondary-btn" aria-label={`Remove ${item.label}`} title="Remove item" disabled={disabled} onClick={()=>save(id,null)}>&times;</button>
        </div>
        <div role="group" aria-label={`Protection for ${item.label}`} style={{display:'flex',flexWrap:'wrap',gap:'8px 16px'}}>
          {(['fabric','fragile'] as const).map(type=><label key={type} style={{display:'inline-flex',alignItems:'center',gap:6,fontSize:13}}>
            <input type="checkbox" checked={item.protection===type || item.protection==='both'} disabled={disabled}
              onChange={e=>save(id,{...item,protection:e.target.checked?'both':type==='fabric'?'fragile':'fabric',service:'self'})}/>
            {type==='fabric'?'Fabric':'Fragile'}
          </label>)}
        </div>
        <span>Required material: <strong>{item.protection==='fabric'?'Plastic':item.protection==='fragile'?'Cardboard':'Plastic and cardboard'}</strong></span>
        <div style={{display:'flex',flexWrap:'wrap',gap:'8px 14px'}}>{(['packing','materials'] as const).map(service=><label key={service} style={{display:'inline-flex',alignItems:'center',gap:7,fontSize:13}}>
          <input type="checkbox" disabled={disabled || quote?.status!=='priced'} checked={item.service===service} onChange={e=>save(id,{...item,service:e.target.checked?service:'self'})}/>
          <span>{service==='packing'?'Packing only':'Packing and material'} {quote?.status==='priced' && <strong>{money(service==='packing'?quote.packing_only:quote.packing_and_material)}</strong>}</span>
        </label>)}</div>
        {quote?.status!=='priced' && <p role="status">{quote?'Packing price unavailable: the moving team needs to confirm the material for this item.':'Calculating packing prices...'}</p>}
      </section>;
    })}
    <div style={{padding:'12px 0'}}>
      <input type="search" aria-label="Search inventory items to pack" placeholder="Search items" value={search} onChange={e=>setSearch(e.target.value)} style={{width:'100%',boxSizing:'border-box'}}/>
      <div style={{maxHeight:260,overflowY:'auto',marginTop:8}}>
        {shown.map(row=><div key={row.id} data-customer-action={`additional:${row.id}`} style={{display:'flex',flexWrap:'wrap',alignItems:'center',gap:12,padding:'12px 0',borderBottom:'1px solid #e5d8d5'}}>
          <span style={{flex:'1 1 140px'}}>{row.room && <small style={{display:'block'}}>{row.room}</small>}{row.label}</span>
          {(['fabric','fragile'] as const).map(protection=><label key={protection}><input type="checkbox" aria-label={`${row.label}: ${protection}`} disabled={disabled} checked={false} onChange={()=>save(row.id,{...row,protection,service:'self'})}/> {protection==='fabric'?'Fabric':'Fragile'}</label>)}
        </div>)}
        {!shown.length && <p>{available.length?'No matching items.':'All remaining inventory items have been added.'}</p>}
      </div>
    </div>
  </section>;
}
