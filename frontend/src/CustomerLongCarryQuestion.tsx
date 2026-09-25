import { useState } from 'react';
import './CustomerStorageQuestion.css';
import './CustomerLongCarryQuestion.css';
export type CarryLocation = { location: 'pickup' | 'delivery'; address: string; revision: string; distance_feet: number | null; unknown?: boolean; acknowledged?: boolean; discount_percent: number; question: string };
export type CarryOption = { included_feet: number; increment_feet: number; rate_per_cuft: number; cubic_feet: number; inventory_cubic_feet: number; minimum_cubic_feet: number; locations: CarryLocation[] };
const money = (value: number) => value.toLocaleString('en-US', { style:'currency', currency:'USD' });
export default function CustomerLongCarryQuestion({ config, location, value, missing, onChange, shuttleCharge }: { config: CarryOption; shuttleCharge?: number; location: CarryLocation; value: number | 'unknown' | null; missing: boolean; onChange: (value: number | 'unknown' | null) => void }) {
  const [answer, setAnswer] = useState<boolean | 'unknown' | null>(value === 'unknown' ? 'unknown' : value === null ? null : value > config.included_feet);
  const [overLimit, setOverLimit] = useState(typeof value === 'number' && value > 500 && value > config.included_feet);
  const [longRangeCount, setLongRangeCount] = useState(12);
  const ranges: { start: number; end: number }[] = [];
  for (let start = config.included_feet + 1; start <= (overLimit ? 100000 : 500);) {
    const bandEnd = config.included_feet + Math.ceil((start - config.included_feet) / config.increment_feet) * config.increment_feet;
    const end = Math.min(bandEnd, start <= 500 ? 500 : 100000);
    ranges.push({ start, end });
    start = end + 1;
  }
  const selected = typeof value !== 'number' ? undefined : ranges.find(range => value >= range.start && value <= range.end);
  const label = (range: { start: number; end: number }) => `${range.start.toLocaleString()}–${range.end.toLocaleString()} feet`;
  const choose = (yes: boolean) => { setAnswer(yes); setOverLimit(false); onChange(yes ? null : config.included_feet); };
  const extra = Math.max(0, (typeof value === 'number' ? value : 0) - config.included_feet);
  const increments = Math.ceil(extra / config.increment_feet);
  const subtotal = Math.round(increments * config.cubic_feet * config.rate_per_cuft * 100) / 100;
  const discount = Math.round(subtotal * location.discount_percent) / 100;
  function rangeTile(range: { start: number; end: number }) {
    const count = Math.ceil((range.end - config.included_feet) / config.increment_feet);
    const gross = Math.round(count * config.cubic_feet * config.rate_per_cuft * 100) / 100;
    const reduction = Math.round(gross * location.discount_percent) / 100;
    return <button type="button" key={range.end} className={`cm-carry-range${selected?.end === range.end ? ' is-selected' : ''}`} aria-pressed={selected?.end === range.end} onClick={() => { setOverLimit(range.start > 500); onChange(range.end); }}>
      <strong>{label(range)}</strong><span>{money(gross - reduction)} long carry</span>
      {reduction > 0 && <small><s>{money(gross)}</s> &middot; {location.discount_percent}% off</small>}
    </button>;
  }
  return <section aria-label="Long carry" style={{ border: missing ? '1px solid #d32f2f' : undefined, borderRadius:12, padding:missing ? 12 : undefined }}>
    <p>{location.address}</p>{shuttleCharge !== undefined && <p>A smaller truck is needed for delivery. Shuttle charge: <strong>{money(shuttleCharge)}</strong>.</p>}<h4>Can the {shuttleCharge !== undefined ? 'smaller moving truck' : 'moving truck'} reach and park next to your {location.location} address, within {config.included_feet} feet of the entrance?</h4>
    <p>Follow the walking route from where the truck can park to your entrance. The first {config.included_feet} feet are included at this address.</p>
    <div style={{ display:'flex', flexWrap:'wrap', gap:12 }}>
      {[false, true].map(yes => <label key={String(yes)} style={{ display:'flex', alignItems:'center', gap:8, padding:'12px 18px', border:'1px solid #d8cdca', borderRadius:8 }}>
        <input type="radio" name={`carry-answer-${location.location}`} checked={answer === yes} onChange={() => choose(yes)} />{yes ? 'No' : 'Yes'}
      </label>)}
      <label style={{ display:'flex', alignItems:'center', gap:8, padding:'12px 18px', border:'1px solid #d8cdca', borderRadius:8 }}><input type="radio" name={`carry-answer-${location.location}`} checked={answer === 'unknown'} onChange={() => { setAnswer('unknown'); onChange(null); }} />I don't know</label>
    </div>
    {answer === 'unknown' && <div className="cm-storage-summary">
      <p>If the truck parks more than {config.included_feet} feet from the entrance, a long-carry charge will apply. The actual walking distance determines the charge.</p>
      <p>First {config.included_feet} feet: included. Each additional {config.increment_feet} feet or part thereof: {money(config.rate_per_cuft)} per cu ft.</p>
      <p>At {config.cubic_feet} billable cu ft, each additional increment costs {money(config.cubic_feet * config.rate_per_cuft)} before discounts.{location.discount_percent > 0 ? ` Your ${location.discount_percent}% discount applies.` : ''}</p>
      <p>The final charge is pending confirmation of the distance.</p>
      <label><input type="checkbox" checked={value === 'unknown'} onChange={event => onChange(event.target.checked ? 'unknown' : null)} /> I understand that a long-carry charge will apply if the distance exceeds {config.included_feet} feet, at the rates shown above.</label>
    </div>}
    {answer === true && <div style={{ marginTop:16 }}>
      <div role="group" aria-label="Choose the distance range" aria-invalid={missing}>
        <p className="cm-carry-range-label">Choose the distance range</p>
        <div className="cm-carry-ranges">{ranges.filter(range => range.end <= 500).map(range => rangeTile(range))}</div>
        <button type="button" className={`cm-carry-over${overLimit ? ' is-selected' : ''}`} aria-expanded={overLimit} onClick={() => { setOverLimit(!overLimit); onChange(null); }}>Over {Math.max(500, config.included_feet)} feet <span aria-hidden="true">{overLimit ? '\u2212' : '+'}</span></button>
        {overLimit && <div className="cm-carry-longer">
          <p className="cm-carry-range-label">Choose the longer distance range</p>
          <div className="cm-carry-ranges">{ranges.filter(range => range.start > 500).slice(0, Math.max(longRangeCount, ranges.filter(range => range.start > 500).findIndex(range => range.end === selected?.end) + 1)).map(range => rangeTile(range))}</div>
          {longRangeCount < ranges.filter(range => range.start > 500).length && <button type="button" className="cm-carry-over" onClick={() => setLongRangeCount(count => count + 12)}>Show longer distances</button>}
        </div>}
      </div>
    </div>}
    {missing && <p className="cm-field-error" role="alert">Choose an answer, select a range if No, or acknowledge the charge if you don't know.</p>}
    <p>Each additional {config.increment_feet} feet, or part thereof, costs {money(config.rate_per_cuft)} per cu ft.</p>
    {typeof value === 'number' && <section className="cm-storage-summary" aria-label="Long carry cost breakdown">
      <dl><div><dt>Carrying distance</dt><dd>{selected ? label(selected) : `Up to ${config.included_feet} feet`}</dd></div><div><dt>Included</dt><dd>{config.included_feet} ft</dd></div><div><dt>Billable increments</dt><dd>{increments}</dd></div></dl>
      {increments > 0 && <div className="cm-storage-summary-basis"><p>{increments} &times; {config.cubic_feet} cu ft &times; {money(config.rate_per_cuft)}</p>{config.minimum_cubic_feet > config.inventory_cubic_feet && <p>Your inventory is {config.inventory_cubic_feet} cu ft. Minimum billable: {config.minimum_cubic_feet} cu ft.</p>}</div>}
      {discount > 0 && <p>Before discount: {money(subtotal)}. Discount ({location.discount_percent}%): -{money(discount)}</p>}
      <div className="cm-storage-summary-total"><span>Long carry charge</span><strong>{money(subtotal-discount)}</strong></div>
      {shuttleCharge !== undefined && <div className="cm-storage-summary-total"><span>Delivery shuttle + long carry</span><strong>{money(shuttleCharge + subtotal - discount)}</strong></div>}
    </section>}
  </section>;
}
