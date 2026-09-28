import { PACKING_CARD_PREFIX, isPackingCard } from './LongDistancePackingCard';

type Service = { id?: string; name: string; rate_text: string; comments: string };
type Material = { id: string; name: string; material_price: string; packing_price: string; unpacking_price: string };
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
  return saved ?? rows.map(([name,material,packing,unpacking],index)=>({id:`material-${index+1}`,name,
    material_price:String(material),packing_price:String(packing),unpacking_price:String(unpacking)}));
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
  return <div className="ld-box-table-wrap"><table className="slds-table slds-table_bordered ld-box-table" style={{minWidth:800}} aria-label="Materials rates">
    <thead><tr><th scope="col">Description</th>{labels.map(label=><th scope="col" className="ld-box-price" key={label}>{label} / unit</th>)}
      {editing && <th scope="col" className="ld-box-action"><button type="button" className="slds-button ld-box-icon" title="Add material" aria-label="Add material" onClick={()=>update([...materials,{id:crypto.randomUUID(),name:'',material_price:'0',packing_price:'0',unpacking_price:'0'}])}>+</button></th>}
    </tr></thead><tbody>{materials.map((item,index)=><tr key={item.id}>
      <td>{editing?<input className="slds-input" aria-label={`Material ${index+1} description`} value={item.name} onChange={e=>update(materials.map(row=>row.id===item.id?{...row,name:e.target.value}:row))}/>:item.name}</td>
      {fields.map((field,column)=><td key={field} className="ld-box-price">{editing?<input className="slds-input" type="number" min="0" step="0.01" aria-label={`${item.name || `Material ${index+1}`} ${labels[column]} rate`} value={item[field]} onChange={e=>update(materials.map(row=>row.id===item.id?{...row,[field]:e.target.value}:row))}/>:Number(item[field]).toLocaleString('en-US',{style:'currency',currency:'USD'})}</td>)}
      {editing && <td><button type="button" className="slds-button ld-box-icon" title="Remove material" aria-label={`Remove ${item.name || 'material'}`} onClick={()=>update(materials.filter(row=>row.id!==item.id))}>&times;</button></td>}
    </tr>)}</tbody></table></div>;
}
