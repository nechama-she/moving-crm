import { useState } from 'react';
type Rule = {title: string; type: 'amount' | 'percent' | 'rate'; value: number};
type Charge = {id: string; name: string; total: number; transportation: boolean; discount?: Rule};
export default function RepDiscounts({base, headers, onSaved}: {base: string; headers: Record<string,string>; onSaved: () => Promise<unknown>}) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<{presets: Rule[]; charges: Charge[]}>({presets: [], charges: []});
  const [id, setId] = useState('');
  const [rule, setRule] = useState<Rule>({title: 'Rep discount', type: 'amount', value: 0});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const charge = options.charges.find(c => c.id === id);
  async function load() {
    const response = await fetch(base + '/rep-discounts', {headers, cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not load discounts.');
    setOptions(data);
    return data as typeof options;
  }
  function choose(c: Charge) { setId(c.id); setRule(c.discount || {title: 'Rep discount', type: 'amount', value: 0}); }
  async function save(remove = false) {
    setBusy(true); setError('');
    try {
      const response = await fetch(base + '/rep-discounts', {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: JSON.stringify({...rule, charge_id: id, remove})});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the discount values.');
      await onSaved();
      const next = await load();
      const selected = next.charges.find(c => c.id === id);
      if (selected) choose(selected);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="cm-rep-discounts">
    <button type="button" className="cm-secondary-btn" disabled={busy} aria-expanded={open} onClick={async () => {
      if (open) {setOpen(false); return;}
      setBusy(true); setError('');
      try { const data = await load(); if (data.charges[0]) choose(data.charges[0]); setOpen(true); }
      catch(e) {setError((e as Error).message);} finally {setBusy(false);}
    }}>Rep discounts</button>
    {open && <section className="cm-rep-discount-editor" aria-label="Rep discounts">
      <strong>Discounts & fee adjustments</strong>
      <p>Transportation discounts apply to the base charge only. Select a fee to reduce or waive it separately.</p>
      <label>Charge<select value={id} disabled={busy} onChange={e => {const c = options.charges.find(c => c.id === e.target.value); if(c) choose(c);}}>{options.charges.map(c => <option key={c.id} value={c.id}>{c.name} - ${c.total.toFixed(2)}</option>)}</select></label>
      {charge?.transportation && <label>Price sheet discount<select value="" disabled={busy} onChange={e => setRule(options.presets[Number(e.target.value)])}><option value="" disabled>Choose a named discount, or enter a rep discount below</option>{options.presets.map((r,i) => <option key={i} value={i}>{r.title}</option>)}</select></label>}
      <label>Discount name<input disabled={busy} maxLength={120} value={rule.title} onChange={e => setRule({...rule,title:e.target.value})}/></label>
      <div className="cm-rep-discount-fields">
        <label>Type<select disabled={busy} value={rule.type} onChange={e => setRule({...rule,type:e.target.value as Rule['type']})}><option value="amount">Amount off ($)</option><option value="percent">Percent off (%)</option>{charge?.transportation && <option value="rate">Reduced cu-ft rate</option>}</select></label>
        <label>{rule.type === 'rate' ? 'New rate ($/cu ft)' : rule.type === 'percent' ? 'Percentage' : 'Amount off ($)'}<input disabled={busy} type="number" min="0" max={rule.type === 'percent' ? 100 : undefined} step="0.01" value={rule.value} onChange={e => setRule({...rule,value:Number(e.target.value)})}/></label>
      </div>
      <div className="cm-rep-discount-actions">
        {charge && !charge.transportation && <button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => setRule({title:'Fee waived',type:'percent',value:100})}>Waive fee</button>}
        {charge?.discount && <button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => void save(true)}>Remove discount</button>}
        <button type="button" className="cm-primary" disabled={busy || !id || !rule.title.trim()} onClick={() => void save()}>{busy ? 'Saving...' : 'Apply discount'}</button>
      </div>
    </section>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
