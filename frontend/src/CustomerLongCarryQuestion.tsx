import './CustomerStorageQuestion.css';
export type CarryLocation = { location: 'pickup' | 'delivery'; address: string; revision: string; distance_feet: number | null; discount_percent: number; question: string };
export type CarryOption = { included_feet: number; increment_feet: number; rate_per_cuft: number; cubic_feet: number; inventory_cubic_feet: number; minimum_cubic_feet: number; locations: CarryLocation[] };
const money = (value: number) => value.toLocaleString('en-US', { style:'currency', currency:'USD' });
export default function CustomerLongCarryQuestion({ config, location, value, missing, onChange }: { config: CarryOption; location: CarryLocation; value: number | null; missing: boolean; onChange: (value: number | null) => void }) {
  const extra = Math.max(0, (value ?? 0) - config.included_feet);
  const increments = Math.ceil(extra / config.increment_feet);
  const subtotal = Math.round(increments * config.cubic_feet * config.rate_per_cuft * 100) / 100;
  const discount = Math.round(subtotal * location.discount_percent) / 100;
  return <section aria-label="Long carry" style={{ border: missing ? '1px solid #d32f2f' : undefined, borderRadius:12, padding:missing ? 12 : undefined }}>
    <p>{location.address}</p><h4>{location.question}</h4>
    <p>Follow the walking route from where the truck can park to your entrance. The first {config.included_feet} feet are included at this address.</p>
    <label htmlFor={`carry-${location.location}`}>Estimated distance in feet</label>
    <input id={`carry-${location.location}`} type="number" min="0" max="100000" step="1" inputMode="numeric" placeholder="Enter distance" value={value ?? ''} aria-invalid={missing} style={{ display:'block', padding:12, marginTop:8, width:180, maxWidth:'100%', border:'1px solid #d8cdca', borderRadius:8, font:'inherit' }} onChange={e => { const n=Number(e.target.value); if(e.target.value==='') onChange(null); else if(Number.isInteger(n) && n>=0 && n<=100000) onChange(n); }} />
    {missing && <p className="cm-field-error" role="alert">Enter the carrying distance for this address.</p>}
    <p>Each additional {config.increment_feet} feet, or part thereof, costs {money(config.rate_per_cuft)} per cu ft.</p>
    {value !== null && <section className="cm-storage-summary" aria-label="Long carry cost breakdown">
      <dl><div><dt>Carrying distance</dt><dd>{value} ft</dd></div><div><dt>Included</dt><dd>{config.included_feet} ft</dd></div><div><dt>Additional distance</dt><dd>{extra} ft</dd></div><div><dt>Billable increments</dt><dd>{increments}</dd></div></dl>
      {increments > 0 && <div className="cm-storage-summary-basis"><p>{increments} &times; {config.cubic_feet} cu ft &times; {money(config.rate_per_cuft)}</p>{config.minimum_cubic_feet > config.inventory_cubic_feet && <p>Your inventory is {config.inventory_cubic_feet} cu ft. Minimum billable: {config.minimum_cubic_feet} cu ft.</p>}</div>}
      {discount > 0 && <p>Before discount: {money(subtotal)}. Discount ({location.discount_percent}%): -{money(discount)}</p>}
      <div className="cm-storage-summary-total"><span>Long carry total</span><strong>{money(subtotal-discount)}</strong></div>
    </section>}
  </section>;
}
