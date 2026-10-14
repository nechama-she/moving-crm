import './ShuttleCard.css';
type Service = { id?: string; name: string; rate_text: string; comments: string };
type Config = { enabled: boolean; steps_per_flight: string; free_flights: string; rate_per_cuft: string; minimum_cubic_feet: string | null; pickup_discount_percent: string; delivery_discount_percent: string };
export const STAIRS_PREFIX = '__stairs_pricing__:';
export const isStairsCard = (service: Service) => service.comments.startsWith(STAIRS_PREFIX);
export default function StairsPricingCard({ services, editing, onChange }: { services: Service[]; editing: boolean; onChange: (rows: Service[]) => void }) {
  const existing = services.find(isStairsCard);
  const defaults: Config = { enabled: false, steps_per_flight: '13', free_flights: '1', rate_per_cuft: '0.20', minimum_cubic_feet: null, pickup_discount_percent: '0', delivery_discount_percent: '0' };
  const config: Config = { ...defaults, ...(existing ? JSON.parse(existing.comments.slice(STAIRS_PREFIX.length)) : {}) };
  function update(patch: Partial<Config>) {
    const row = { ...existing, name: 'Stairs pricing', rate_text: '', comments: STAIRS_PREFIX + JSON.stringify({ ...config, ...patch }) };
    onChange(existing ? services.map(s => s === existing ? row : s) : [...services, row]);
  }
  return <div className="pickup-areas">
    <p>Charge for outdoor and shared-building stairs at pickup and delivery. Stairs inside the customer's house or apartment are excluded.</p>
    <label><input type="checkbox" checked={config.enabled} disabled={!editing} onChange={e => update({ enabled: e.target.checked })} /> Enable stairs pricing questions</label>
    <div className="shuttle-settings">{(['steps_per_flight','free_flights','rate_per_cuft','minimum_cubic_feet','pickup_discount_percent','delivery_discount_percent'] as const).map(field => <article key={field}><label>
      <strong>{{ steps_per_flight: 'Steps per flight (up to)', free_flights: 'Free flights at each address', rate_per_cuft: 'Charge per cu ft per additional flight ($)', minimum_cubic_feet: 'Minimum billable cu ft', pickup_discount_percent: 'Default pickup discount (%)', delivery_discount_percent: 'Default delivery discount (%)' }[field]}</strong>
      {editing ? <input type="number" min={field === 'steps_per_flight' ? 1 : 0} max={field.endsWith('_percent') ? 100 : undefined} step={field === 'rate_per_cuft' || field.endsWith('_percent') ? '0.01' : '1'} value={config[field] ?? ''} placeholder={field === 'minimum_cubic_feet' ? 'Use pricing book minimum' : 'Required'} onChange={e => update({ [field]: field === 'minimum_cubic_feet' && !e.target.value ? null : e.target.value })} /> : <span>{config[field] ?? 'Use pricing book minimum'}</span>}
    </label></article>)}</div>
    <p>Set a default discount to 100% to waive that address's stairs charge. The original charge, discount, and $0 total will still appear on the estimate.</p>
    <p>The free-flight allowance applies separately at pickup and delivery. This card replaces imported stairs service choices.</p>
    <p><strong>Customer question at each address:</strong> How many flights of outdoor or shared-building stairs will the movers need to use?</p>
    <p>Up to {config.steps_per_flight || '…'} steps counts as one flight. Do not include stairs inside your house or apartment.</p>
  </div>;
}
