import CustomerMaterialItems from './CustomerMaterialItems';
import ConfiguredPackingItems from './ConfiguredPackingItems';
import PackingServiceSelect, {type PackingMaterialService} from './PackingServiceSelect';
import {useEffect,useState} from 'react';
export type AdditionalMaterialItem = {label:string;inventory_id?:string;protection:'fabric'|'fragile'|'both';item_type:string;variant:string;cubic_feet:number|string|null;screen_inches:number|string|null;quantity:number;service:'self'|'packing'|'materials'};
export type PackingSelection = { mode: 'full' | 'partial' | 'none'; unpacking: boolean; item_ids: string[]; material_item_ids?: string[];additional_items?:Record<string,AdditionalMaterialItem>;has_additional_protection?:boolean|null;box_quantities?:Record<string,number> };
export type PackingPackage = {
  cubic_feet: number;
  inventory_cubic_feet?: number;
  minimum_cubic_feet?: number;
  rates: Partial<Record<'full' | 'partial' | 'unpacking', { rate: number; total: number }>>;
  configured_materials?:boolean;
  items: { id: string; group_id?:string; label: string; room?: string; packing_material?:'plastic'|'cardboard'; price: number; labor_price?: number; material_price?: number; requirement?:'required'|'optional'; material_name?:string; materials?:{id:string;name:string;quantity:number}[]; quantity?:number; available?:boolean }[];
  box_items?:{id:string;label:string;room?:string;quantity:number;material_name:string;available:boolean;labor_price:number;material_price:number}[];
  selection: PackingSelection;
  other_inventory?:(AdditionalMaterialItem & {id:string;name:string;room?:string})[];
  material_quotes?:{id:string;status:string;issues:string[];packing_only:number|null;packing_and_material:number|null}[];
};
const money = (amount: number) => amount.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
export default function CustomerPackingOptions({ config, selection, onChange, disabled, stage }: {
  config: PackingPackage; selection: PackingSelection; onChange: (value: PackingSelection) => void; disabled: boolean; stage?:'service'|'boxes'|'protection';
}) {
  const inventoryVolume = config.inventory_cubic_feet ?? config.cubic_feet;
  const minimumApplies = inventoryVolume < (config.minimum_cubic_feet ?? 0);
  const materials = selection.material_item_ids ?? selection.item_ids;
  const boxes=config.box_items||[];
  const boxQuantities=selection.box_quantities||{};
  const moverBoxCount=boxes.reduce((sum,item)=>sum+(boxQuantities[item.id]||0),0);
  const allBoxCount=boxes.reduce((sum,item)=>sum+item.quantity,0);
  const savedBoxChoice=moverBoxCount===0?'self':moverBoxCount===allBoxCount?'movers':'custom';
  const [boxChoice,setBoxChoice]=useState<'self'|'movers'|'custom'>(savedBoxChoice);
  useEffect(()=>setBoxChoice(current=>current==='custom'?'custom':savedBoxChoice),[savedBoxChoice]);
  const rooms = new Map<string, PackingPackage['items']>();
  for (const item of config.items) {
    const room = item.room?.trim() || 'Other items';
    if (!rooms.has(room)) rooms.set(room, []);
    rooms.get(room)!.push(item);
  }
  const extraTotal=selection.has_additional_protection === false ? 0 : (config.material_quotes||[]).reduce((sum,quote)=>{const service=selection.additional_items?.[quote.id]?.service;return sum+Number(service==='materials'?quote.packing_and_material||0:service==='packing'?quote.packing_only||0:0);},0);
  const boxTotal=selection.mode==='full'?0:boxes.reduce((sum,item)=>sum+(boxQuantities[item.id]||0)*(item.labor_price+item.material_price),0);
  const total = (selection.mode !== 'none' ? config.rates[selection.mode]?.total || 0 : extraTotal + config.items.filter(item => selection.item_ids.includes(item.id)).reduce((sum, item) => sum + (item.labor_price ?? item.price) + (materials.includes(item.id) ? item.material_price || 0 : 0), 0))+boxTotal;
  const setBoxCounts=(counts:Record<string,number>)=>onChange({...selection,box_quantities:counts});
  const materialService=(id:string):PackingMaterialService=>!selection.item_ids.includes(id)?'self':materials.includes(id)?'materials':'packing';
  const setMaterialService=(id:string,service:PackingMaterialService)=>onChange({...selection,
    item_ids:service==='self'?selection.item_ids.filter(value=>value!==id):[...new Set([...selection.item_ids,id])],
    material_item_ids:service==='materials'?[...new Set([...materials,id])]:materials.filter(value=>value!==id),
  });
  const boxRooms=[...boxes.reduce((map,item)=>{const room=item.room?.trim()||'Other items';map.set(room,[...(map.get(room)||[]),item]);return map;},new Map<string,typeof boxes>()).entries()];
  return <div className="cm-packing-options">
    {stage === 'service' && <><div className="cm-packing-heading"><h4>Choose your packing service</h4><div className="cm-packing-volume"><span>{inventoryVolume.toLocaleString()} cu ft</span>{minimumApplies && <small>Minimum billable: {config.minimum_cubic_feet!.toLocaleString()} cu ft</small>}</div></div>
    <div className="cm-packing-choices" data-customer-action="packing-service">
      {(['full', 'partial', 'none'] as const).filter(mode => mode === 'none' || config.rates[mode]).map(mode => <label key={mode} className={`cm-packing-choice ${selection.mode === mode ? 'selected' : ''}`}>
        <input type="radio" name="packing-package" disabled={disabled} checked={selection.mode === mode} onChange={() => onChange({ ...selection, mode, item_ids: [], material_item_ids: [] })} />
        <span className="cm-packing-copy"><strong className="cm-packing-title"><span>{mode === 'full' ? 'Full packing' : mode === 'partial' ? 'Partial packing' : 'No packing'}</span><span className="cm-packing-inline-price">&middot; {mode === 'none' ? '$0' : <>{money(config.rates[mode]!.rate)} / cu ft &middot; {money(config.rates[mode]!.total)}</>}</span></strong>
        <small>{mode === 'full' ? 'All belongings, including personal-item boxes. Materials included.' : mode === 'partial' ? 'We box items that require it. Materials included; personal-item boxes excluded.' : (config.items.length ? 'Pack yourself, or choose individual items below.' : 'Pack your belongings yourself.')}</small></span>
      </label>)}
    </div>
    </>}
    {stage === 'boxes' && boxes.length>0 && (selection.mode==='full' ? <p>Box packing is included with full packing.</p> : <section className="cm-box-packing">
      <h4>Who will pack your boxes?</h4>
      <p>Your inventory includes <strong>{allBoxCount} boxes</strong>. These quantities reserve truck space; packing is included only when selected here.</p>
      <div className="cm-box-packing-modes">
        <label><input type="radio" name="box-packing" checked={boxChoice==='self'} disabled={disabled} onChange={()=>{setBoxChoice('self');setBoxCounts({});}}/> I will pack all</label>
        <label><input type="radio" name="box-packing" checked={boxChoice==='movers'} disabled={disabled||boxes.some(item=>!item.available)} onChange={()=>{setBoxChoice('movers');setBoxCounts(Object.fromEntries(boxes.map(item=>[item.id,item.quantity])));}}/> Movers pack all</label>
        <label><input type="radio" name="box-packing" checked={boxChoice==='custom'} disabled={disabled} onChange={()=>{setBoxChoice('custom');setBoxCounts({});}}/> Choose by box type</label>
      </div>
      {boxChoice==='custom' && <div className="cm-box-packing-list">
        <div className="cm-box-packing-head"><span>Box type</span><span>Total</span><span>Movers pack</span><span>You pack</span></div>
        {boxRooms.map(([room,items])=><section className="cm-box-room" key={room}><h5>{room}</h5>{items.map(item=>{const movers=boxQuantities[item.id]||0;return <div className="cm-box-packing-row" key={item.id} data-customer-action={`box:${item.id}`}>
          <span><strong>{item.label}</strong>{item.available?<small>{money(item.labor_price+item.material_price)} each</small>:<small>Pricing unavailable</small>}</span>
          <span>{item.quantity}</span>
          <input aria-label={`Boxes packed by movers for ${item.label}`} type="number" min="0" max={item.quantity} step="1" disabled={disabled||!item.available} value={movers} onChange={event=>{const quantity=Math.max(0,Math.min(item.quantity,Number.parseInt(event.target.value||'0',10)||0));setBoxCounts({...boxQuantities,[item.id]:quantity});}}/>
          <span>{item.quantity-movers}</span>
        </div>})}</section>)}
      </div>}
    </section>)}
    {stage === 'protection' && selection.mode === 'none' && <>
    {config.configured_materials ? <>
    <ConfiguredPackingItems config={config} selection={selection} onChange={onChange} disabled={disabled}/>
    <fieldset className="cm-protection-confirmation" data-customer-action="additional-protection">
      <legend>Do you have any other fragile or fabric items?</legend>
      <label><input type="radio" name="additional-protection" disabled={disabled} checked={selection.has_additional_protection === false} onChange={() => onChange({...selection,has_additional_protection:false})}/> No, only the required items</label>
      <label><input type="radio" name="additional-protection" disabled={disabled} checked={selection.has_additional_protection === true} onChange={() => onChange({...selection,has_additional_protection:true})}/> Yes, I have more items</label>
    </fieldset>
    {selection.has_additional_protection === true && <ConfiguredPackingItems config={config} selection={selection} onChange={onChange} disabled={disabled} showRequired={false} showOptional/>}
    </> : <>
    {config.items.length > 0 && <section className="cm-packing-items">
      <h4>These items require protection</h4>
      <div className="cm-checklist">
        {[...rooms].map(([room, items]) => <section key={room} aria-label={room}>
          <h4 style={{margin:'16px 0 4px',fontSize:12,fontWeight:400,color:'var(--cm-text-muted)'}}>{room}</h4>
          {items.map(item => <section key={item.id} data-customer-action={`protection:${item.id}`} style={{display:'flex',flexDirection:'column',alignItems:'flex-start',gap:10,borderBottom:'1px solid #e5d8d5',padding:'12px 0'}}>
          <strong>{item.label}</strong>
          <span>Required material: <strong>{item.packing_material === 'plastic' ? 'Plastic' : 'Cardboard'}</strong></span>
          <PackingServiceSelect label={item.label} value={materialService(item.id)} packingPrice={item.labor_price??item.price} materialsPrice={(item.labor_price??item.price)+(item.material_price||0)} disabled={disabled} onChange={service=>setMaterialService(item.id,service)}/>
          </section>)}
        </section>)}
      </div>
    </section>}
    <fieldset className="cm-protection-confirmation" data-customer-action="additional-protection">
      <legend>Do you have any other fragile or fabric items?</legend>
      <label><input type="radio" name="additional-protection" disabled={disabled} checked={selection.has_additional_protection === false} onChange={() => onChange({...selection,has_additional_protection:false})}/> No, I have no other fabric or fragile items</label>
      <label><input type="radio" name="additional-protection" disabled={disabled} checked={selection.has_additional_protection === true} onChange={() => onChange({...selection,has_additional_protection:true})}/> Yes, I have more items</label>
    </fieldset>
    {selection.has_additional_protection === true && <CustomerMaterialItems config={config} selection={selection} disabled={disabled} onChange={onChange}/>}
    </>}
    </>}
    <div className="cm-packing-total" aria-live="polite"><span>Packing total</span><strong>{money(total)}</strong></div>
  </div>;
}
