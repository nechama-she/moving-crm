import { useState } from 'react';
import type { DiscountResult } from './RepDiscounts';

// The rep's discount on one tab of the fees, with the amount it takes off the tab's total now.
export type SectionDiscountRule = {title: string; type: 'amount' | 'percent'; value: number; amount: number};

// Rep only: one discount on a tab's total, apart from the discounts on its lines.
export default function SectionDiscount({base, headers, onSaved, tab, tabName, current}: {base: string; headers: Record<string, string>; onSaved: (result: DiscountResult) => void; tab: string; tabName: string; current?: SectionDiscountRule}) {
  const [open, setOpen] = useState(false);
  const [rule, setRule] = useState<{title: string; type: 'amount' | 'percent'; value: number}>({title: 'Discount', type: 'amount', value: 0});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save(remove = false) {
    setBusy(true); setError('');
    try {
      const response = await fetch(base + '/section-discounts', {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: JSON.stringify({...rule, tab, remove})});
      const data = await response.json().catch(() => null);
      if (!response.ok || !data) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not save the discount. Your entries are still here. Please try again.');
      onSaved(data);
      setOpen(false);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="cm-rep-discounts" onKeyDown={event => { if (event.key === 'Escape' && !busy) { event.stopPropagation(); setOpen(false); } }}>
    <button type="button" className="cm-charge-edit cm-discount-pencil" aria-label={`Discount for ${tabName}`} title="Add or edit discount" disabled={busy} aria-expanded={open} onClick={() => {
      if (!open) setRule(current ? {title: current.title, type: current.type, value: current.value} : {title: 'Discount', type: 'amount', value: 0});
      setError(''); setOpen(!open);
    }}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m16 3 5 5L8 21H3v-5L16 3Z M13 6l5 5"/></svg></button>
    {open && <section className="cm-rep-discount-editor" aria-label={`Discount for ${tabName}`}>
      <strong>{tabName}</strong>
      <label>Discount name<input disabled={busy} maxLength={120} value={rule.title} onChange={e => setRule({...rule, title: e.target.value})}/></label>
      <div className="cm-rep-discount-fields">
        <label>Type<select disabled={busy} value={rule.type} onChange={e => setRule({...rule, type: e.target.value as 'amount' | 'percent', value: 0})}><option value="amount">Amount off ($)</option><option value="percent">Percent off (%)</option></select></label>
        <label>{rule.type === 'percent' ? 'Percentage' : 'Amount off ($)'}<input disabled={busy} type="number" min="0" max={rule.type === 'percent' ? 100 : undefined} step="0.01" value={rule.value} onChange={e => setRule({...rule, value: Number(e.target.value)})}/></label>
      </div>
      <div className="cm-rep-discount-actions">
        {current && <button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => void save(true)}>Remove discount</button>}
        <button type="button" className="cm-estimate-action" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
        <button type="button" className="cm-primary" disabled={busy || !rule.title.trim()} onClick={() => void save()}>{busy ? 'Saving...' : 'Save'}</button>
      </div>
    </section>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
