import { useState } from 'react';
import type {PackingPackage, PackingSelection} from './CustomerPackingOptions';
import PackingServiceSelect, {type PackingMaterialService} from './PackingServiceSelect';

export default function ConfiguredPackingItems({config,selection,onChange,disabled,showRequired=true,showOptional=false}:{config:PackingPackage;selection:PackingSelection;onChange:(value:PackingSelection)=>void;disabled:boolean;showRequired?:boolean;showOptional?:boolean}) {
  const materials=selection.material_item_ids??selection.item_ids;
  const [selectedRooms,setSelectedRooms]=useState<Record<string,string>>({});
  function serviceFor(id:string):PackingMaterialService {
    return !selection.item_ids.includes(id)?'self':materials.includes(id)?'materials':'packing';
  }
  function selectService(id:string,service:PackingMaterialService) {
    onChange({...selection,
      item_ids:service==='self'?selection.item_ids.filter(value=>value!==id):[...new Set([...selection.item_ids,id])],
      material_item_ids:service==='materials'?[...new Set([...materials,id])]:materials.filter(value=>value!==id),
    });
  }
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
          {rooms.map(([room,items])=>{const count=new Set(items.map(item=>item.group_id||item.id)).size;return <button type="button" role="tab" key={room} aria-selected={room===selectedRoom} disabled={disabled} onClick={()=>setSelectedRooms(current=>({...current,[requirement]:room}))}>{room}<span title={`${count} inventory items`}>{count} items</span></button>;})}
        </div>
        <section role="tabpanel" aria-label={selectedRoom}>
          {[...roomItems.reduce((map,item)=>{
            const id=item.group_id||item.id;
            map.set(id,[...(map.get(id)||[]),item]);
            return map;
          },new Map<string,typeof roomItems>()).values()].map(group=><section key={group[0].group_id||group[0].id} style={{display:'grid',gap:8,borderBottom:'1px solid #e5d8d5',padding:'12px 0'}}>
          <strong>{group[0].label}</strong>
          {group.map(item=>{const materialLabel=`${item.material_name || (item.packing_material==='plastic'?'Plastic':'Cardboard')}${item.quantity!=null?` - ${item.quantity} per item`:''}`;return <div key={item.id} data-customer-action={`configured:${item.id}`} className="cm-material-service-row" style={{paddingTop:group.length>1?8:0,borderTop:group.length>1?'1px solid #eee5e2':'none'}}>
            <span>{materialLabel}</span>
            <PackingServiceSelect label={`${group[0].label}, ${materialLabel}`} value={serviceFor(item.id)} packingPrice={item.labor_price??item.price} materialsPrice={(item.labor_price??item.price)+(item.material_price||0)} available={item.available!==false} disabled={disabled} onChange={service=>selectService(item.id,service)}/>
            {item.available===false && <p role="status">Material pricing needs confirmation.</p>}
          </div>})}
        </section>)}
        </section>
      </section>;
    })}
  </>;
}
