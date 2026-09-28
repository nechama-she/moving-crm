import { useState } from 'react';
import type { AdditionalMaterialItem, PackingPackage, PackingSelection } from './CustomerPackingOptions';
const money=(value:number|null)=>Number(value||0).toLocaleString('en-US',{style:'currency',currency:'USD'});
export default function CustomerMaterialItems({config,selection,onChange,disabled}:{config:PackingPackage;selection:PackingSelection;onChange:(value:PackingSelection)=>void;disabled:boolean}) {
  const [draft,setDraft]=useState<AdditionalMaterialItem|null>(null);
  const [editing,setEditing]=useState('');
  const [inventory,setInventory]=useState('');
  const items=selection.additional_items||{};
  function save(id:string,item:AdditionalMaterialItem|null) {
    const next={...items};
    if(item)next[id]=item;else delete next[id];
    onChange({...selection,additional_items:next});
  }
  return <section className="cm-packing-items">
    <h4>Other fabric or fragile items</h4>
    <p>Fabric must be protected with plastic or cardboard. Fragile items must be boxed.</p>
    {Object.entries(items).map(([id,item])=>{
      const quote=config.material_quotes?.find(row=>row.id===id);
      return <section key={id} style={{borderBottom:'1px solid #e5d8d5',padding:'12px 0',display:'grid',gap:10}}>
        <strong>{item.label}{item.quantity>1?` (${item.quantity} items)`:''}</strong>
        <span>{item.protection==='both'?'Fabric and fragile':item.protection==='fabric'?'Fabric':'Fragile'}</span>
        {quote?.status==='priced'?<div style={{display:'flex',flexWrap:'wrap',gap:'8px 14px'}}>{(['packing','materials'] as const).map(service=><label key={service} style={{display:'inline-flex',alignItems:'center',gap:7,fontSize:13}}>
          <input type="checkbox" disabled={disabled} checked={item.service===service} onChange={e=>save(id,{...item,service:e.target.checked?service:'self'})}/>
          <span>{service==='packing'?'Packing only':'Packing and material'} <strong>{money(service==='packing'?quote.packing_only:quote.packing_and_material)}</strong></span>
        </label>)}</div>:<p role="status">{quote?'Your item is saved. The moving team needs to confirm suitable materials and pricing.':'Calculating materials...'}</p>}
        <div style={{display:'flex',gap:12}}><button type="button" className="cm-secondary-btn" disabled={disabled} onClick={()=>{setEditing(id);setDraft({...item,service:'self'});}}>Edit item</button><button type="button" className="cm-secondary-btn" disabled={disabled} onClick={()=>save(id,null)}>Remove</button></div>
      </section>;
    })}
    {!draft?<button type="button" className="cm-secondary-btn" disabled={disabled} onClick={()=>{setEditing(crypto.randomUUID());setInventory('');setDraft({label:'',protection:'fabric',item_type:'any',variant:'',cubic_feet:null,screen_inches:null,quantity:1,service:'self'});}}>+ Add item needing protection</button>:<fieldset disabled={disabled} style={{border:0,padding:'16px 0',display:'grid',gap:12}}>
      <label>Inventory item<select value={inventory} onChange={e=>{setInventory(e.target.value);const row=config.other_inventory?.[Number(e.target.value)];if(e.target.value!=='' && row)setDraft({...draft,label:row.name,quantity:row.quantity||1});}}><option value="">Other item</option>{config.other_inventory?.map((row,index)=><option key={index} value={index}>{row.room?`${row.room}: `:''}{row.name}</option>)}</select></label>
      <label>Item name<input value={draft.label} maxLength={200} onChange={e=>setDraft({...draft,label:e.target.value})}/></label>
      <label>Protection<select value={draft.protection} onChange={e=>setDraft({...draft,protection:e.target.value as AdditionalMaterialItem['protection']})}><option value="fabric">Fabric</option><option value="fragile">Fragile</option><option value="both">Fabric and fragile</option></select></label>
      <label>Item type<select value={draft.item_type} onChange={e=>setDraft({...draft,item_type:e.target.value,variant:''})}>{[['any','Other'],['books','Books'],['dishes','Dishes'],['picture','Picture'],['mirror','Mirror'],['wardrobe','Wardrobe'],['sofa','Sofa'],['mattress','Mattress'],['tv','TV'],['bed_frame','Fabric bed frame']].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
      {draft.item_type==='mattress' && <label>Mattress size<select value={draft.variant} onChange={e=>setDraft({...draft,variant:e.target.value})}><option value="">Choose size</option>{['twin','full','queen','king'].map(value=><option key={value}>{value}</option>)}</select></label>}
      <label>Quantity<input type="number" min="1" max="1000" step="1" value={draft.quantity} onChange={e=>setDraft({...draft,quantity:Number(e.target.value)})}/></label>
      <label>Size per item (cu ft, if known)<input type="number" min="0.01" step="0.01" value={draft.cubic_feet??''} onChange={e=>setDraft({...draft,cubic_feet:e.target.value||null})}/></label>
      {draft.item_type==='tv' && <label>Screen size (inches)<input type="number" min="1" value={draft.screen_inches??''} onChange={e=>setDraft({...draft,screen_inches:e.target.value||null})}/></label>}
      <div style={{display:'flex',gap:12}}><button type="button" className="cm-primary-btn" disabled={!draft.label.trim()||!Number.isInteger(draft.quantity)||draft.quantity<1||draft.quantity>1000} onClick={()=>{save(editing,draft);setDraft(null);}}>Calculate materials</button><button type="button" className="cm-secondary-btn" onClick={()=>setDraft(null)}>Cancel</button></div>
    </fieldset>}
  </section>;
}
