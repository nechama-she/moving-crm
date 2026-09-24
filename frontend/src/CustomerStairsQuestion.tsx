import './CustomerStairsQuestion.css';
export type StairsLocation = { location: 'pickup' | 'delivery'; address: string; revision: string; flights: number | null; paid_flights: number; subtotal: number; discount_amount: number; discount_percent: number; total: number; question: string };
export type StairsOption = { steps_per_flight: number; free_flights: number; rate_per_cuft: number; cubic_feet: number; inventory_cubic_feet: number; minimum_cubic_feet: number; locations: StairsLocation[]; total: number };
const money = (n: number) => n.toLocaleString('en-US',{style:'currency',currency:'USD'});
export default function CustomerStairsQuestion({ config, location, value, missing, onChange }: {
  config: StairsOption; location: StairsLocation; value: number | null; missing: boolean; onChange: (flights: number | null) => void;
}) {
  const paid = value === null ? 0 : Math.max(0,value-config.free_flights);
  const subtotal = Math.round(paid*config.cubic_feet*config.rate_per_cuft*100)/100;
  const discount = Math.round(subtotal*location.discount_percent)/100;
  return <section className={`cm-stairs-question ${missing ? 'missing' : ''}`} aria-invalid={missing}>
    <span className="cm-eyebrow">{location.location === 'pickup' ? 'PICKUP ADDRESS' : 'DELIVERY ADDRESS'}</span>
    <p className="cm-stairs-address">{location.address}</p>
    <h4>{location.question}</h4>
    <p>Up to <strong>{config.steps_per_flight} steps counts as one flight</strong>. Count only stairs the movers will use between the truck and your home's entrance.</p>
    <p><strong>Do not include stairs inside your house or apartment.</strong> If an elevator replaces the stairs, count only the flights still needed.</p>
    <label className="cm-stairs-label" htmlFor={`stairs-${location.location}`}>Number of flights</label>
    <div className="cm-stairs-counter">
      <button type="button" aria-label="Decrease flights" disabled={value === null || value === 0} onClick={() => onChange(Math.max(0,(value || 0)-1))}>−</button>
      <input id={`stairs-${location.location}`} type="number" inputMode="numeric" min="0" max="1000" step="1" value={value ?? ''} placeholder="Choose" onChange={e => { const raw=e.target.value; const n=Number(raw); if (raw === '') onChange(null); else if (Number.isInteger(n) && n>=0 && n<=1000) onChange(n); }} />
      <button type="button" aria-label="Increase flights" disabled={value === 1000} onClick={() => onChange((value || 0)+1)}>+</button>
      <button type="button" className="cm-stairs-none" aria-pressed={value === 0} onClick={() => onChange(0)}>No stairs</button>
    </div>
    {missing && <p className="cm-field-error" role="alert">Enter the number of flights, or choose No stairs.</p>}
    <p>{config.free_flights} flight{config.free_flights === 1 ? '' : 's'} included at this address. Each additional flight costs {money(config.rate_per_cuft)} per cu ft.</p>
    {value !== null && <div className="cm-stairs-total">
      <span>{paid} paid flight{paid === 1 ? '' : 's'} × {config.cubic_feet} billable cu ft × {money(config.rate_per_cuft)}</span>
      {discount > 0 && <span>Before discount: {money(subtotal)}; Discount ({location.discount_percent}%): -{money(discount)}</span>}
      <strong>{location.location === 'pickup' ? 'Pickup' : 'Delivery'} stairs: {money(subtotal-discount)}</strong>
      {config.minimum_cubic_feet > config.inventory_cubic_feet && <small>Inventory: {config.inventory_cubic_feet} cu ft · Minimum billable: {config.minimum_cubic_feet} cu ft</small>}
    </div>}
  </section>;
}
