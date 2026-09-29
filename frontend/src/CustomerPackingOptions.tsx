import CustomerMaterialItems from './CustomerMaterialItems';
import ConfiguredPackingItems from './ConfiguredPackingItems';
export type AdditionalMaterialItem = {label:string;inventory_id?:string;protection:'fabric'|'fragile'|'both';item_type:string;variant:string;cubic_feet:number|string|null;screen_inches:number|string|null;quantity:number;service:'self'|'packing'|'materials'};
export type PackingSelection = { mode: 'full' | 'partial' | 'none'; unpacking: boolean; item_ids: string[]; material_item_ids?: string[];additional_items?:Record<string,AdditionalMaterialItem>;has_additional_protection?:boolean|null };
export type PackingPackage = {
  cubic_feet: number;
  inventory_cubic_feet?: number;
  minimum_cubic_feet?: number;
  rates: Partial<Record<'full' | 'partial' | 'unpacking', { rate: number; total: number }>>;
  configured_materials?:boolean;
  items: { id: string; label: string; room?: string; packing_material?:'plastic'|'cardboard'; price: number; labor_price?: number; material_price?: number; requirement?:'required'|'optional'; material_name?:string; quantity?:number; available?:boolean }[];
  selection: PackingSelection;
  other_inventory?:(AdditionalMaterialItem & {id:string;name:string;room?:string})[];
  material_quotes?:{id:string;status:string;issues:string[];packing_only:number|null;packing_and_material:number|null}[];
};
const money = (amount: number) => amount.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
export default function CustomerPackingOptions({ config, selection, onChange, disabled, stage }: {
  config: PackingPackage; selection: PackingSelection; onChange: (value: PackingSelection) => void; disabled: boolean; stage?:'service'|'protection';
}) {
  const inventoryVolume = config.inventory_cubic_feet ?? config.cubic_feet;
  const minimumApplies = inventoryVolume < (config.minimum_cubic_feet ?? 0);
  const materials = selection.material_item_ids ?? selection.item_ids;
  const rooms = new Map<string, PackingPackage['items']>();
  for (const item of config.items) {
    const room = item.room?.trim() || 'Other items';
    if (!rooms.has(room)) rooms.set(room, []);
    rooms.get(room)!.push(item);
  }
  const extraTotal=selection.has_additional_protection === false ? 0 : (config.material_quotes||[]).reduce((sum,quote)=>{const service=selection.additional_items?.[quote.id]?.service;return sum+Number(service==='materials'?quote.packing_and_material||0:service==='packing'?quote.packing_only||0:0);},0);
  const total = selection.mode !== 'none' ? config.rates[selection.mode]?.total || 0 : extraTotal + config.items.filter(item => selection.item_ids.includes(item.id)).reduce((sum, item) => sum + (item.labor_price ?? item.price) + (materials.includes(item.id) ? item.material_price || 0 : 0), 0);
  return <div className="cm-packing-options">
    {stage !== 'protection' && <><div className="cm-packing-heading"><h4>Choose your packing service</h4><div className="cm-packing-volume"><span>{inventoryVolume.toLocaleString()} cu ft</span>{minimumApplies && <small>Minimum billable: {config.minimum_cubic_feet!.toLocaleString()} cu ft</small>}</div></div>
    <div className="cm-packing-choices">
      {(['full', 'partial', 'none'] as const).filter(mode => mode === 'none' || config.rates[mode]).map(mode => <label key={mode} className={`cm-packing-choice ${selection.mode === mode ? 'selected' : ''}`}>
        <input type="radio" name="packing-package" disabled={disabled} checked={selection.mode === mode} onChange={() => onChange({ ...selection, mode, item_ids: [], material_item_ids: [] })} />
        <span className="cm-packing-copy"><strong className="cm-packing-title"><span>{mode === 'full' ? 'Full packing' : mode === 'partial' ? 'Partial packing' : 'No packing'}</span><span className="cm-packing-inline-price">&middot; {mode === 'none' ? '$0' : <>{money(config.rates[mode]!.rate)} / cu ft &middot; {money(config.rates[mode]!.total)}</>}</span></strong>
        <small>{mode === 'full' ? 'All belongings, including personal-item boxes. Materials included.' : mode === 'partial' ? 'We box items that require it. Materials included; personal-item boxes excluded.' : (config.items.length ? 'Pack yourself, or choose individual items below.' : 'Pack your belongings yourself.')}</small></span>
      </label>)}
    </div>
    </>}
    {stage !== 'service' && selection.mode === 'none' && <>
    {config.configured_materials ? <>
    <ConfiguredPackingItems config={config} selection={selection} onChange={onChange} disabled={disabled} showOptional={selection.has_additional_protection === true}/>
    <fieldset className="cm-protection-confirmation">
      <legend>Do you have any other items you want us to pack?</legend>
      <label><input type="radio" name="additional-protection" disabled={disabled} checked={selection.has_additional_protection === false} onChange={() => onChange({...selection,has_additional_protection:false})}/> No, only the required items</label>
      <label><input type="radio" name="additional-protection" disabled={disabled} checked={selection.has_additional_protection === true} onChange={() => onChange({...selection,has_additional_protection:true})}/> Yes, I have more items</label>
    </fieldset>
    </> : <>
    <p>Fabric items must be covered with plastic. Fragile items must be boxed in cardboard.</p>
    {config.items.length > 0 && <section className="cm-packing-items">
      <h4>These items require protection</h4>
      <p className="cm-step-sub">Choose a service, or leave unchecked to pack it yourself.</p>
      <div className="cm-checklist">
        {[...rooms].map(([room, items]) => <section key={room} aria-label={room}>
          <h4 style={{margin:'16px 0 4px',fontSize:12,fontWeight:400,color:'var(--cm-text-muted)'}}>{room}</h4>
          {items.map(item => <section key={item.id} style={{display:'flex',flexDirection:'column',alignItems:'flex-start',gap:10,borderBottom:'1px solid #e5d8d5',padding:'12px 0'}}>
          <strong>{item.label}</strong>
          <span>Required material: <strong>{item.packing_material === 'plastic' ? 'Plastic' : 'Cardboard'}</strong></span>
          <div style={{display:'flex',flexWrap:'wrap',gap:'8px 14px',width:'100%'}}>
            {([false, true] as const).map(withMaterials => <label key={String(withMaterials)} style={{display:'inline-flex',alignItems:'center',gap:7,fontSize:13,cursor:'pointer'}}>
              <input type="checkbox" disabled={disabled} checked={selection.item_ids.includes(item.id) && materials.includes(item.id) === withMaterials} onChange={e => onChange({
                ...selection,
                item_ids: e.target.checked ? [...new Set([...selection.item_ids,item.id])] : selection.item_ids.filter(id => id !== item.id),
                material_item_ids: e.target.checked && withMaterials ? [...new Set([...materials,item.id])] : materials.filter(id => id !== item.id),
              })} />
              <span>{withMaterials ? 'Packing and material' : 'Packing only'} <strong>{money((item.labor_price ?? item.price) + (withMaterials ? item.material_price || 0 : 0))}</strong></span>
            </label>)}
          </div>
          </section>)}
        </section>)}
      </div>
    </section>}
    <fieldset className="cm-protection-confirmation">
      <legend>Do you have any other fabric or fragile items?</legend>
      <label><input type="radio" name="additional-protection" disabled={disabled} checked={selection.has_additional_protection === false} onChange={() => onChange({...selection,has_additional_protection:false})}/> No, I have no other fabric or fragile items</label>
      <label><input type="radio" name="additional-protection" disabled={disabled} checked={selection.has_additional_protection === true} onChange={() => onChange({...selection,has_additional_protection:true})}/> Yes, I have more items</label>
    </fieldset>
    {selection.has_additional_protection === true && <CustomerMaterialItems config={config} selection={selection} disabled={disabled} onChange={onChange}/>}
    </>}
    </>}
    <div className="cm-packing-total" aria-live="polite"><span>Packing total</span><strong>{money(total)}</strong></div>
  </div>;
}
