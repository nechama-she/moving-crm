export type PackingSelection = { mode: 'full' | 'partial' | 'none'; unpacking: boolean; item_ids: string[]; material_item_ids?: string[] };
export type PackingPackage = {
  cubic_feet: number;
  inventory_cubic_feet?: number;
  minimum_cubic_feet?: number;
  rates: Partial<Record<'full' | 'partial' | 'unpacking', { rate: number; total: number }>>;
  items: { id: string; label: string; price: number; labor_price?: number; material_price?: number }[];
  selection: PackingSelection;
};
const money = (amount: number) => amount.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
export default function CustomerPackingOptions({ config, selection, onChange, disabled }: {
  config: PackingPackage; selection: PackingSelection; onChange: (value: PackingSelection) => void; disabled: boolean;
}) {
  const inventoryVolume = config.inventory_cubic_feet ?? config.cubic_feet;
  const minimumApplies = inventoryVolume < (config.minimum_cubic_feet ?? 0);
  const materials = selection.material_item_ids ?? selection.item_ids;
  const total = (selection.mode !== 'none' ? config.rates[selection.mode]?.total || 0 : config.items.filter(item => selection.item_ids.includes(item.id)).reduce((sum, item) => sum + (item.labor_price ?? item.price) + (materials.includes(item.id) ? item.material_price || 0 : 0), 0)) + (selection.unpacking ? config.rates.unpacking?.total || 0 : 0);
  return <div className="cm-packing-options">
    <div className="cm-packing-heading"><h4>Choose your packing service</h4><div className="cm-packing-volume"><span>{inventoryVolume.toLocaleString()} cu ft</span>{minimumApplies && <small>Minimum billable: {config.minimum_cubic_feet!.toLocaleString()} cu ft</small>}</div></div>
    <div className="cm-packing-choices">
      {(['full', 'partial', 'none'] as const).filter(mode => mode === 'none' || config.rates[mode]).map(mode => <label key={mode} className={`cm-packing-choice ${selection.mode === mode ? 'selected' : ''}`}>
        <input type="radio" name="packing-package" disabled={disabled} checked={selection.mode === mode} onChange={() => onChange({ ...selection, mode, item_ids: [], material_item_ids: [] })} />
        <span className="cm-packing-copy"><strong className="cm-packing-title"><span>{mode === 'full' ? 'Full packing' : mode === 'partial' ? 'Partial packing' : 'No packing'}</span><span className="cm-packing-inline-price">&middot; {mode === 'none' ? '$0' : <>{money(config.rates[mode]!.rate)} / cu ft &middot; {money(config.rates[mode]!.total)}</>}</span></strong>
        <small>{mode === 'full' ? 'All belongings, including personal-item boxes. Materials included.' : mode === 'partial' ? 'We box items that require it. Materials included; personal-item boxes excluded.' : (config.items.length ? 'Pack yourself, or choose individual items below.' : 'Pack your belongings yourself.')}</small></span>
      </label>)}
    </div>
    {selection.mode === 'none' && config.items.length > 0 && <section className="cm-packing-items">
      <h4>These items must be boxed</h4>
      <p className="cm-step-sub">Choose a service, or leave unchecked to pack it yourself.</p>
      <div className="cm-checklist">
        {config.items.map(item => <section key={item.id} style={{display:'flex',flexDirection:'column',alignItems:'flex-start',gap:10,borderBottom:'1px solid #e5d8d5',padding:'12px 0'}}>
          <strong>{item.label}</strong>
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
      </div>
    </section>}
    {config.rates.unpacking && <section className="cm-unpacking-addon" aria-labelledby="cm-unpacking-heading">
      <h4 id="cm-unpacking-heading">Optional add-on</h4>
      <label className="cm-unpacking-control">
        <input type="checkbox" disabled={disabled} checked={selection.unpacking} onChange={e => onChange({ ...selection, unpacking: e.target.checked })} />
        <span className="cm-packing-copy">
          <strong className="cm-packing-title"><span>Add unpacking</span><span className="cm-packing-inline-price">&middot; {money(config.rates.unpacking.rate)} / cu ft &middot; {money(config.rates.unpacking.total)}</span></strong>
          <small>A separate service for your move. Available with full, partial, or no packing.</small>
        </span>
      </label>
    </section>}
    <div className="cm-packing-total" aria-live="polite"><span>Packing &amp; unpacking total</span><strong>{money(total)}</strong></div>
  </div>;
}
