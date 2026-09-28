import { PACKING_CARD_PREFIX, isPackingCard } from './LongDistancePackingCard';
import { defaultMaterialRule, defaultBoxCapacity, emptyRule } from './materialRules';
import type { MaterialRule } from './materialRules';

type Service = { id?: string; name: string; rate_text: string; comments: string };
export type Material = { id: string; name: string; material_price: string; packing_price: string; unpacking_price: string; rule?:MaterialRule|null; box_capacity_cuft?:number|null; capacity?:number|null; capacity_unit?:'cuft'|'inches'|'sheets'|'feet'|'items'|'mattress_size';mattress_size?:string|null;capacity_kind?:'up_to'|'over' };
function capacityFields(item:Material):Material {
  if(item.capacity_unit==='mattress_size')return item;
  if(item.capacity==null && item.rule?.item_type==='mattress' && ['twin','full','queen','king'].includes(item.rule.variant))return {...item,capacity:null,capacity_unit:'mattress_size',mattress_size:item.rule.variant};
  if(item.capacity!==undefined)return item;
  if(item.name==='Packing Paper (100): 100 Sheets')return {...item,capacity:100,capacity_unit:'sheets',capacity_kind:'up_to'};
  if(item.name==='Packing Paper (200): 200 Sheets')return {...item,capacity:200,capacity_unit:'sheets',capacity_kind:'up_to'};
  const rule=item.rule;
  if(rule && rule.measure!=='none')return {...item,capacity:rule.maximum??rule.minimum,capacity_unit:rule.measure==='screen_inches'?'inches':'cuft',capacity_kind:rule.maximum!==null?'up_to':'over'};
  return {...item,capacity:item.box_capacity_cuft??null,capacity_unit:'cuft',capacity_kind:'up_to'};
}
const rows: [string, number, number, number][] = [
  ['Book Box: 2 CU',9,5,15], ['Small Box: 2 Cuft',10,6,15],
  ['Medium Box: 3.0 Cuft',12,8,15], ['Large Box: 5 Cuft',12,8,15],
  ['Dish Box: 6.0 Cuft',18,21,15], ['Mattress Bag (twin)',18,12,15],
  ['Mattress Bag (Full)',20,12,15], ['Mattress Bag (Queen)',26,12,15],
  ['Mattress Bag (King)',26,12,15], ['Picture Box Standard 3.0cf: 3 CU',12,12,15],
  ['Picture Box Large 6.0cf: 6 cuft',16,14,15], ['Mirror Box: 6 cuft',20,15,15],
  ['Packing Paper (100): 100 Sheets',30,20,15], ['Packing Paper (200): 200 Sheets',60,40,30],
  ['Bubble Wrap Per foot',2,1.5,1.5], ['Shrink Wrap (per item) Over 25 cubic foot',18,12,15],
  ['Shrink Wrap (per item) under 25 cubic foot',10,12,15], ['Tape',3,0,0],
  ['Moving Blanket (sale)',25,0,0], ['TV Box up to 61 inches: 10 cuft',32,20,15],
  ['TV box 61 inches and up: 15 cuft',65,20,15], ['Carton Crate Large',66,35,15],
  ['Bubble Corrugated Wrap (per item)',24,12,15], ['Wardrobe Box: 16 cuft',22,12,15],
  ['China Cabinet: 65 cuft',66,35,15], ['Curio cabinet: 45 cuft',66,35,15],
  ['Sofa cover',26,12,15], ['Glass top (small/Medium): 5',32,20,15],
  ['Glass top large: 12',66,35,15], ['Special pack Fabric bed frame',26,12,15],
];
export function materialRows(services: Service[]): Material[] {
  const card = services.find(isPackingCard);
  const saved = card ? JSON.parse(card.comments.slice(PACKING_CARD_PREFIX.length)).materials : undefined;
  const defaults=rows.map(([name,material,packing,unpacking],index)=>({id:`material-${index+1}`,name,
    material_price:String(material),packing_price:String(packing),unpacking_price:String(unpacking),rule:defaultMaterialRule(index),box_capacity_cuft:defaultBoxCapacity(index)}));
  return (saved ? saved.map((item:Material)=>{
    const original=defaults.find(row=>row.id===item.id && row.name===item.name);
    const capacity=item.box_capacity_cuft??original?.box_capacity_cuft??null;
    return {...item,box_capacity_cuft:capacity,rule:item.rule??original?.rule??(capacity?{...emptyRule(),protection:'fragile'}:null)};
  }) : defaults).map(capacityFields);
}
export function withMaterials(services: Service[], materials = materialRows(services)): Service[] {
  const existing = services.find(isPackingCard);
  const config = existing ? JSON.parse(existing.comments.slice(PACKING_CARD_PREFIX.length)) : {full:'',partial:'',unpacking:'',items:[]};
  const row = {...existing,name:existing?.name ?? 'Long-distance packing',rate_text:existing?.rate_text ?? '',
    comments:PACKING_CARD_PREFIX+JSON.stringify({...config,materials})};
  return existing ? services.map(service=>service===existing?row:service) : [...services,row];
}
export default function LongDistanceMaterialsCard({services,editing,onChange}: {
  services:Service[]; editing:boolean; onChange:(services:Service[])=>void;
}) {
  const materials=materialRows(services);
  const update=(next:Material[])=>onChange(withMaterials(services,next));
  const fields=['material_price','packing_price','unpacking_price'] as const;
  const labels=['Materials','Packing','Unpacking'];
  return <><div className="ld-box-table-wrap"><table className="slds-table slds-table_bordered ld-box-table" style={{minWidth:1050}} aria-label="Materials rates">
    <thead><tr><th scope="col">Description</th><th scope="col" style={{width:210}}>Capacity / size</th>{labels.map(label=><th scope="col" className="ld-box-price" key={label}>{label} / unit</th>)}
      {editing && <th scope="col" className="ld-box-action"><button type="button" className="slds-button ld-box-icon" title="Add material" aria-label="Add material" onClick={()=>update([...materials,{id:crypto.randomUUID(),name:'',material_price:'0',packing_price:'0',unpacking_price:'0'}])}>+</button></th>}
    </tr></thead><tbody>{materials.map((item,index)=><tr key={item.id}>
      <td>{editing?<input className="slds-input" aria-label={`Material ${index+1} description`} value={item.name} onChange={e=>update(materials.map(row=>row.id===item.id?{...row,name:e.target.value}:row))}/>:item.name}</td>
      <td>{editing?<div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:6}}>
        {item.capacity_unit==='mattress_size'?<select aria-label={`${item.name} mattress size`} value={item.mattress_size??''} onChange={e=>update(materials.map(row=>row.id===item.id?{...row,mattress_size:e.target.value}:row))}><option value="">Choose size</option>{['twin','full','queen','king'].map(size=><option key={size} value={size}>{size[0].toUpperCase()+size.slice(1)}</option>)}</select>:<input type="number" min="0.01" step="0.01" aria-label={`${item.name} capacity`} value={item.capacity??''} onChange={e=>update(materials.map(row=>row.id===item.id?{...row,capacity:e.target.value===''?null:Number(e.target.value)}:row))}/>}
        <select aria-label={`${item.name} capacity unit`} value={item.capacity_unit??'cuft'} onChange={e=>update(materials.map(row=>row.id===item.id?{...row,capacity_unit:e.target.value as Material['capacity_unit'],capacity:null,rule:null}:row))}>{[['cuft','cu ft'],['inches','inches'],['sheets','sheets'],['feet','feet'],['items','items'],['mattress_size','mattress size']].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select>
      </div>:item.capacity_unit==='mattress_size'?`${item.mattress_size || ''} mattress`:item.capacity!=null?`${item.capacity} ${item.capacity_unit==='cuft'?'cu ft':item.capacity_unit}`:'Not specified'}</td>
      {fields.map((field,column)=><td key={field} className="ld-box-price">{editing?<input className="slds-input" type="number" min="0" step="0.01" aria-label={`${item.name || `Material ${index+1}`} ${labels[column]} rate`} value={item[field]} onChange={e=>update(materials.map(row=>row.id===item.id?{...row,[field]:e.target.value}:row))}/>:Number(item[field]).toLocaleString('en-US',{style:'currency',currency:'USD'})}</td>)}
      {editing && <td><button type="button" className="slds-button ld-box-icon" title="Remove material" aria-label={`Remove ${item.name || 'material'}`} onClick={()=>update(materials.filter(row=>row.id!==item.id))}>&times;</button></td>}
    </tr>)}</tbody></table></div></>;
}
