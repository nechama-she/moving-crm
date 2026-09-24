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
  return <div className="pickup-areas">
    <p>Charge for the walking distance between the parked truck and the entrance at pickup and delivery.</p>
    <label><input type="checkbox" checked={config.enabled} disabled={!editing} onChange={e => update({ enabled: e.target.checked })} /> Enable long carry pricing questions</label>
    <div className="shuttle-settings">{(['increment_feet','included_feet','rate_per_cuft','minimum_cubic_feet','pickup_discount_percent','delivery_discount_percent'] as const).map(field => <article key={field}><label>
      <strong>{{ increment_feet: 'Additional distance increment (feet)', included_feet: 'Included distance at each address (feet)', rate_per_cuft: 'Charge per cu ft per additional increment ($)', minimum_cubic_feet: 'Minimum billable cu ft', pickup_discount_percent: 'Default pickup discount (%)', delivery_discount_percent: 'Default delivery discount (%)' }[field]}</strong>
      {editing ? <input type="number" min={field === 'increment_feet' ? 1 : 0} max={field.endsWith('_percent') ? 100 : undefined} step={field === 'rate_per_cuft' || field.endsWith('_percent') ? '0.01' : '1'} value={config[field] ?? ''} placeholder={field === 'minimum_cubic_feet' ? 'Use pricing book minimum' : 'Required'} onChange={e => update({ [field]: field === 'minimum_cubic_feet' && !e.target.value ? null : e.target.value })} /> : <span>{config[field] ?? 'Use pricing book minimum'}</span>}
    </label></article>)}</div>
    <p>Set a default discount to 100% to waive that address's long carry charge. The original charge, discount, and $0 total will still appear on the estimate.</p>
    <p>The included distance applies separately at each address. Each additional started increment is charged in full.</p>
  </div>;
}
