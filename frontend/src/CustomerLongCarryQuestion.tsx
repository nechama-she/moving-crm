import { useState } from 'react';
import './CustomerStorageQuestion.css';
export type CarryLocation = { location: 'pickup' | 'delivery'; address: string; revision: string; distance_feet: number | null; unknown?: boolean; acknowledged?: boolean; discount_percent: number; question: string };
export type CarryOption = { included_feet: number; increment_feet: number; rate_per_cuft: number; cubic_feet: number; inventory_cubic_feet: number; minimum_cubic_feet: number; locations: CarryLocation[] };
const money = (value: number) => value.toLocaleString('en-US', { style:'currency', currency:'USD' });
export default function CustomerLongCarryQuestion({ config, location, value, missing, onChange, shuttleCharge }: { config: CarryOption; shuttleCharge?: number; location: CarryLocation; value: number | 'unknown' | null; missing: boolean; onChange: (value: number | 'unknown' | null) => void }) {
  const [answer, setAnswer] = useState<boolean | 'unknown' | null>(value === 'unknown' ? 'unknown' : value === null ? null : value > config.included_feet);
  const [overLimit, setOverLimit] = useState(typeof value === 'number' && value > 500 && value > config.included_feet);
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
      <label htmlFor={`carry-${location.location}`}>Choose the distance range</label>
      <select id={`carry-${location.location}`} value={overLimit ? 'over' : selected?.end ?? ''} aria-invalid={missing} style={{ display:'block', width:'100%', marginTop:8 }} onChange={event => {
        if (event.target.value === 'over') { setOverLimit(true); onChange(null); }
        else { setOverLimit(false); onChange(event.target.value ? Number(event.target.value) : null); }
      }}>
        <option value="">Select a range</option>
        {ranges.filter(range => range.end <= 500).map(range => <option key={range.end} value={range.end}>{label(range)}</option>)}
        <option value="over">Over {Math.max(500, config.included_feet)} feet</option>
      </select>
      {overLimit && <><label htmlFor={`carry-more-${location.location}`} style={{ display:'block', marginTop:12 }}>Choose the longer distance range</label>
        <select id={`carry-more-${location.location}`} value={selected?.end ?? ''} style={{ width:'100%', marginTop:8 }} onChange={event => onChange(event.target.value ? Number(event.target.value) : null)}>
          <option value="">Select a range</option>
          {ranges.filter(range => range.start > 500).map(range => <option key={range.end} value={range.end}>{label(range)}</option>)}
        </select></>}
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
