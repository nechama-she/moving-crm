import { useState } from 'react';
type Rule = {title: string; type: 'amount' | 'percent' | 'rate' | 'total'; value: number};
type Charge = {id: string; name: string; total: number; transportation: boolean; discount?: Rule};
async function discountResponse(response: Response, fallback: string) {
  const data = await response.json().catch(() => null);
  if (!response.ok || !data) throw new Error(typeof data?.detail === 'string' ? data.detail : fallback);
  return data;
}
export default function RepDiscounts({base, headers, onSaved, chargeId, chargeName}: {base: string; headers: Record<string,string>; onSaved: () => Promise<unknown>; chargeId: string; chargeName: string}) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<{presets: Rule[]; charges: Charge[]}>({presets: [], charges: []});
  const [id, setId] = useState('');
  const [rule, setRule] = useState<Rule>({title: 'Discount', type: 'amount', value: 0});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const charge = options.charges.find(c => c.id === id);
  async function load() {
    const response = await fetch(base + '/rep-discounts', {headers, cache: 'no-store'});
    const data = await discountResponse(response, 'Could not load discounts. Please try again.');
    setOptions(data);
    return data as typeof options;
  }
  function choose(c: Charge) { setId(c.id); setRule(c.discount ? {...c.discount, title: c.discount.title === 'Rep discount' ? 'Discount' : c.discount.title} : {title: 'Discount', type: 'total', value: c.total}); }
  async function save(remove = false) {
    setBusy(true); setError('');
    try {
      const response = await fetch(base + '/rep-discounts', {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: JSON.stringify({...rule, charge_id: id, remove})});
      await discountResponse(response, 'Could not save the discount. Your entries are still here. Please try again.');
      await onSaved();
      const next = await load();
      const selected = next.charges.find(c => c.id === id);
      if (selected) choose(selected);
      setOpen(false);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="cm-rep-discounts" onKeyDown={event => { if (event.key === 'Escape' && !busy) { event.stopPropagation(); setOpen(false); } }}>
    <button type="button" className="cm-charge-edit cm-discount-pencil" aria-label={`Adjust ${chargeName} price`} title="Add or edit discount" disabled={busy} aria-expanded={open} onClick={async () => {
      if (open) {setOpen(false); return;}
      setBusy(true); setError('');
      try { const data = await load(); const selected = data.charges.find(c => c.id === chargeId); if (!selected) throw new Error('This charge has changed. Refresh the estimate.'); choose(selected); setOpen(true); }
      catch(e) {setError((e as Error).message);} finally {setBusy(false);}
    }}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m16 3 5 5L8 21H3v-5L16 3Z M13 6l5 5"/></svg></button>
    {open && <section className="cm-rep-discount-editor" aria-label={`Discount for ${chargeName}`}>
      <strong>{chargeName}</strong>
      {charge?.transportation && <label>Price sheet discount<select value="" disabled={busy} onChange={e => setRule(options.presets[Number(e.target.value)])}><option value="" disabled>Choose a named discount or customize below</option>{options.presets.map((r,i) => <option key={i} value={i}>{r.title}</option>)}</select></label>}
      <label>Discount name<input disabled={busy} maxLength={120} value={rule.title} onChange={e => setRule({...rule,title:e.target.value})}/></label>
      <div className="cm-rep-discount-fields">
        <label>Type<select disabled={busy} value={rule.type} onChange={e => setRule({...rule,type:e.target.value as Rule['type'], value: e.target.value === 'total' ? charge?.total || 0 : 0})}><option value="total">New total ($)</option><option value="amount">Amount off ($)</option><option value="percent">Percent off (%)</option>{charge?.transportation && <option value="rate">Reduced cu-ft rate</option>}</select></label>
        <label>{rule.type === 'total' ? 'New total ($)' : rule.type === 'rate' ? 'New rate ($/cu ft)' : rule.type === 'percent' ? 'Percentage' : 'Amount off ($)'}<input disabled={busy} type="number" min="0" max={rule.type === 'percent' ? 100 : undefined} step="0.01" value={rule.value} onChange={e => setRule({...rule,value:Number(e.target.value)})}/></label>
      </div>
      <div className="cm-rep-discount-actions">
        {charge && !charge.transportation && <button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => setRule({title:'Fee waived',type:'percent',value:100})}>Waive fee</button>}
        {charge?.discount && <button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => void save(true)}>Remove discount</button>}
        <button type="button" className="cm-estimate-action" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
        <button type="button" className="cm-primary" disabled={busy || !id || !rule.title.trim()} onClick={() => void save()}>{busy ? 'Saving...' : 'Save'}</button>
      </div>
    </section>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
