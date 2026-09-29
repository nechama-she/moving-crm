import { useState } from 'react';
import type {PackingPackage, PackingSelection} from './CustomerPackingOptions';

export default function ConfiguredPackingItems({config,selection,onChange,disabled,showRequired=true,showOptional=false}:{config:PackingPackage;selection:PackingSelection;onChange:(value:PackingSelection)=>void;disabled:boolean;showRequired?:boolean;showOptional?:boolean}) {
  const materials=selection.material_item_ids??selection.item_ids;
  const [selectedRooms,setSelectedRooms]=useState<Record<string,string>>({});
  const money=(value:number)=>value.toLocaleString('en-US',{style:'currency',currency:'USD'});
  if(!config.items.length)return null;
  return <>
    {([...(showRequired?['required'] as const:[]),...(showOptional?['optional'] as const:[])] as const).map(requirement=>{
      const items=config.items.filter(item=>(item.requirement||'required')===requirement);
      if(!items.length)return null;
      const rooms=[...items.reduce((map,item)=>{
        const room=item.room?.trim()||'Other items';
        map.set(room,[...(map.get(room)||[]),item]);
        return map;
      },new Map<string,typeof items>()).entries()];
      const selectedRoom=rooms.some(([room])=>room===selectedRooms[requirement])?selectedRooms[requirement]:rooms[0][0];
      const roomItems=rooms.find(([room])=>room===selectedRoom)![1];
      return <section key={requirement} className="cm-packing-items">
        <h4>{requirement==='required'?'Required packing':'Additional packing options'}</h4>
        <div className="cm-packing-room-tabs" role="tablist" aria-label={`${requirement==='required'?'Required packing':'Additional packing'} rooms`}>
          {rooms.map(([room,items])=><button type="button" role="tab" key={room} aria-selected={room===selectedRoom} disabled={disabled} onClick={()=>setSelectedRooms(current=>({...current,[requirement]:room}))}>{room}<span>{items.length}</span></button>)}
        </div>
        <section role="tabpanel" aria-label={selectedRoom}>
          {[...roomItems.reduce((map,item)=>{
            const id=item.group_id||item.id;
            map.set(id,[...(map.get(id)||[]),item]);
            return map;
          },new Map<string,typeof roomItems>()).values()].map(group=><section key={group[0].group_id||group[0].id} style={{display:'grid',gap:8,borderBottom:'1px solid #e5d8d5',padding:'12px 0'}}>
          <strong>{group[0].label}</strong>
          {group.map(item=><div key={item.id} data-customer-action={`configured:${item.id}`} style={{display:'grid',gap:8,paddingTop:group.length>1?8:0,borderTop:group.length>1?'1px solid #eee5e2':'none'}}>
            <span>{item.material_name || (item.packing_material==='plastic'?'Plastic':'Cardboard')}{item.quantity!=null?` - ${item.quantity} per item`:''}</span>
            <div style={{display:'flex',flexWrap:'wrap',gap:'8px 14px'}}>
            <label style={{display:'inline-flex',alignItems:'center',gap:7,fontSize:13}}>
              <input type="checkbox" disabled={disabled} checked={!selection.item_ids.includes(item.id)}
                onChange={()=>onChange({...selection,item_ids:selection.item_ids.filter(id=>id!==item.id),material_item_ids:materials.filter(id=>id!==item.id)})}/>
              <span>Pack myself</span>
            </label>
            {item.available!==false && ([false,true] as const).map(withMaterials=><label key={String(withMaterials)} style={{display:'inline-flex',alignItems:'center',gap:7,fontSize:13}}>
              <input type="checkbox" disabled={disabled} checked={selection.item_ids.includes(item.id) && materials.includes(item.id)===withMaterials}
                onChange={e=>onChange({...selection,
                  item_ids:e.target.checked?[...new Set([...selection.item_ids,item.id])]:selection.item_ids.filter(id=>id!==item.id),
                  material_item_ids:e.target.checked && withMaterials?[...new Set([...materials,item.id])]:materials.filter(id=>id!==item.id)})}/>
              <span>{withMaterials?'Packing and material':'Packing only'} <strong>{money((item.labor_price??item.price)+(withMaterials?item.material_price||0:0))}</strong></span>
            </label>)}
            </div>
            {item.available===false && <p role="status">Material pricing needs confirmation.</p>}
          </div>)}
        </section>)}
        </section>
      </section>;
    })}
  </>;
}
