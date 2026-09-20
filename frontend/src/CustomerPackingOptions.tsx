export type PackingSelection = { mode: 'full' | 'partial' | 'none'; unpacking: boolean; item_ids: string[] };
export type PackingPackage = {
  cubic_feet: number;
  rates: Partial<Record<'full' | 'partial' | 'unpacking', { rate: number; total: number }>>;
  items: { id: string; label: string; price: number }[];
  selection: PackingSelection;
};
const money = (amount: number) => amount.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
export default function CustomerPackingOptions({ config, selection, onChange, disabled }: {
  config: PackingPackage; selection: PackingSelection; onChange: (value: PackingSelection) => void; disabled: boolean;
}) {
  const total = (selection.mode !== 'none' ? config.rates[selection.mode]?.total || 0 : config.items.filter(item => selection.item_ids.includes(item.id)).reduce((sum, item) => sum + item.price, 0)) + (selection.unpacking ? config.rates.unpacking?.total || 0 : 0);
  return <>
    <h4>How would you like your move packed?</h4>
    <p className="cm-step-sub">Packing and unpacking rates are based on {config.cubic_feet.toLocaleString()} cu ft.</p>
    <div className="cm-options-grid">
      {(['full', 'partial', 'none'] as const).filter(mode => mode === 'none' || config.rates[mode]).map(mode => <label key={mode} className={`cm-option-card ${selection.mode === mode ? 'selected' : ''}`}>
        <input type="radio" name="packing-package" disabled={disabled} checked={selection.mode === mode} onChange={() => onChange({ ...selection, mode, item_ids: [] })} />
        <strong>{mode === 'full' ? 'Full packing' : mode === 'partial' ? 'Partial packing' : 'No packing'}</strong>
        <small>{mode === 'full' ? 'We pack your belongings, including boxes of personal items. Packing materials included.' : mode === 'partial' ? 'We pack items that cannot go on the truck without a box. All required materials included at no extra charge. Excludes packing boxes of personal belongings.' : 'You pack your belongings. You can choose individual items for us to pack below.'}</small>
        {mode !== 'none' && <strong>{money(config.rates[mode]!.rate)} / cu ft ? {money(config.rates[mode]!.total)}</strong>}
      </label>)}
    </div>
    {selection.mode === 'none' && <>
      <h4>These items must be boxed</h4>
      <p className="cm-step-sub">Blanket wrapping alone is not sufficient. Select any items you want us to pack, or leave all unchecked and pack them yourself. Every item listed must be properly boxed before loading.</p>
      <div className="cm-checklist">
        {config.items.map(item => <label key={item.id} className="cm-check-item">
          <input type="checkbox" disabled={disabled} checked={selection.item_ids.includes(item.id)} onChange={e => onChange({ ...selection, item_ids: e.target.checked ? [...selection.item_ids, item.id] : selection.item_ids.filter(id => id !== item.id) })} />
          <span>{item.label} ? {money(item.price)}<small style={{ display: 'block' }}>Box and packing materials included. Must be boxed even if packed by owner.</small></span>
        </label>)}
      </div>
      {!config.items.length && <p>No required-box items have been identified in your current inventory.</p>}
    </>}
    {config.rates.unpacking && <label className="cm-check-item">
      <input type="checkbox" disabled={disabled} checked={selection.unpacking} onChange={e => onChange({ ...selection, unpacking: e.target.checked })} />
      <span>Add unpacking ? {money(config.rates.unpacking.rate)} / cu ft ? {money(config.rates.unpacking.total)}<small style={{ display: 'block' }}>Available with any packing choice.</small></span>
    </label>}
    <p><strong>Packing and unpacking total: {money(total)}</strong></p>
  </>;
}
