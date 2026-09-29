import type {PackingPackage, PackingSelection} from './CustomerPackingOptions';

export default function ConfiguredPackingItems({config,selection,onChange,disabled,showOptional=false}:{config:PackingPackage;selection:PackingSelection;onChange:(value:PackingSelection)=>void;disabled:boolean;showOptional?:boolean}) {
  const materials=selection.material_item_ids??selection.item_ids;
  const money=(value:number)=>value.toLocaleString('en-US',{style:'currency',currency:'USD'});
  return <>
    <p className="cm-step-sub">Choose a service, or leave unchecked to pack it yourself.</p>
    {(['required',...(showOptional?['optional'] as const:[])] as const).map(requirement=>{
      const items=config.items.filter(item=>(item.requirement||'required')===requirement);
      if(!items.length)return null;
      return <section key={requirement} className="cm-packing-items">
        <h4>{requirement==='required'?'Required packing':'Additional packing options'}</h4>
        {items.map(item=><section key={item.id} style={{display:'grid',gap:8,borderBottom:'1px solid #e5d8d5',padding:'12px 0'}}>
          {item.room && <small>{item.room}</small>}
          <strong>{item.label}</strong>
          <span>{item.material_name || (item.packing_material==='plastic'?'Plastic':'Cardboard')}{item.quantity!=null?` - ${item.quantity} per item`:''}</span>
          {item.available===false?<p role="status">Material pricing needs confirmation.</p>:<div style={{display:'flex',flexWrap:'wrap',gap:'8px 14px'}}>
            {([false,true] as const).map(withMaterials=><label key={String(withMaterials)} style={{display:'inline-flex',alignItems:'center',gap:7,fontSize:13}}>
              <input type="checkbox" disabled={disabled} checked={selection.item_ids.includes(item.id) && materials.includes(item.id)===withMaterials}
                onChange={e=>onChange({...selection,
                  item_ids:e.target.checked?[...new Set([...selection.item_ids,item.id])]:selection.item_ids.filter(id=>id!==item.id),
                  material_item_ids:e.target.checked && withMaterials?[...new Set([...materials,item.id])]:materials.filter(id=>id!==item.id)})}/>
              <span>{withMaterials?'Packing and material':'Packing only'} <strong>{money((item.labor_price??item.price)+(withMaterials?item.material_price||0:0))}</strong></span>
            </label>)}
          </div>}
        </section>)}
      </section>;
    })}
    {!config.items.length && <p>No packing materials configured for your inventory items.</p>}
  </>;
}
