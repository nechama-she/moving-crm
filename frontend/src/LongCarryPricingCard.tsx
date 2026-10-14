import './ShuttleCard.css';
type Service = { id?: string; name: string; rate_text: string; comments: string };
type Config = { enabled: boolean; increment_feet: string; included_feet: string; rate_per_cuft: string; minimum_cubic_feet: string | null; pickup_discount_percent: string; delivery_discount_percent: string };
export const LONG_CARRY_PREFIX = '__long_carry_pricing__:';
export const isLongCarryCard = (service: Service) => service.comments.startsWith(LONG_CARRY_PREFIX);
export default function LongCarryPricingCard({ services, editing, onChange }: { services: Service[]; editing: boolean; onChange: (rows: Service[]) => void }) {
  const existing = services.find(isLongCarryCard);
  const defaults: Config = { enabled: false, increment_feet: '75', included_feet: '75', rate_per_cuft: '0.20', minimum_cubic_feet: null, pickup_discount_percent: '0', delivery_discount_percent: '0' };
  const config: Config = { ...defaults, ...(existing ? JSON.parse(existing.comments.slice(LONG_CARRY_PREFIX.length)) : {}) };
  function update(patch: Partial<Config>) {
    const row = { ...existing, name: 'Long carry pricing', rate_text: '', comments: LONG_CARRY_PREFIX + JSON.stringify({ ...config, ...patch }) };
    onChange(existing ? services.map(s => s === existing ? row : s) : [...services, row]);
  }
  const included = Number(config.included_feet), extra = Number(config.increment_feet), rate = Number(config.rate_per_cuft);
  const valid = String(config.included_feet) !== '' && String(config.increment_feet) !== '' && String(config.rate_per_cuft) !== '' && Number.isInteger(included) && included >= 0 && Number.isInteger(extra) && extra > 0 && Number.isFinite(rate) && rate >= 0;
  const money = (amount: number) => amount.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  return <div className="pickup-areas">
    <p>Charge for the walking distance between the parked truck and the entrance at pickup and delivery.</p>
    <label><input type="checkbox" checked={config.enabled} disabled={!editing} onChange={e => update({ enabled: e.target.checked })} /> Enable long carry pricing questions</label>
    <div className="shuttle-settings">{(['included_feet','increment_feet','rate_per_cuft','minimum_cubic_feet','pickup_discount_percent','delivery_discount_percent'] as const).map(field => <article key={field}><label>
      <strong>{{ increment_feet: 'Then charge for every extra (feet)', included_feet: 'First how many feet are free?', rate_per_cuft: 'Price per cu ft for each extra distance ($)', minimum_cubic_feet: 'Minimum billable cu ft', pickup_discount_percent: 'Default pickup discount (%)', delivery_discount_percent: 'Default delivery discount (%)' }[field]}</strong>
      {editing ? <input type="number" min={field === 'increment_feet' ? 1 : 0} max={field.endsWith('_percent') ? 100 : undefined} step={field === 'rate_per_cuft' || field.endsWith('_percent') ? '0.01' : '1'} value={config[field] ?? ''} placeholder={field === 'minimum_cubic_feet' ? 'Use pricing book minimum' : 'Required'} onChange={e => update({ [field]: field === 'minimum_cubic_feet' && !e.target.value ? null : e.target.value })} /> : <span>{config[field] ?? 'Use pricing book minimum'}</span>}
    </label></article>)}</div>
    {valid && <section style={{marginTop:16,padding:16,border:'1px solid #d5e2f0',borderRadius:8,background:'#f7f9fc'}} aria-label="Long carry pricing example">
      <strong>How this price works</strong>
      <p>The first {included} feet are free. After that, charge {money(rate)} per cu ft for every extra {extra} feet. A shorter extra distance is charged the same.</p>
      <table className="slds-table" style={{width:'100%'}}><thead><tr><th style={{textAlign:'left'}}>Total carrying distance</th><th style={{textAlign:'right'}}>Charge per cu ft</th></tr></thead>
        <tbody><tr><td>0&ndash;{included} feet</td><td style={{textAlign:'right'}}>Free</td></tr>
        {[1,2,3].map(n => <tr key={n}><td>{included + extra * (n-1) + 1}&ndash;{included + extra * n} feet</td><td style={{textAlign:'right'}}>{money(rate*n)}</td></tr>)}</tbody>
      </table>
      <p style={{marginBottom:0}}>Calculated separately at pickup and delivery, before any discount.</p>
    </section>}
    <p>Set a default discount to 100% to waive that address's long carry charge. The original charge, discount, and $0 total will still appear on the estimate.</p>

  </div>;
}
