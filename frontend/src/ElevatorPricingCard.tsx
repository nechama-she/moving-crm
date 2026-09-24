import './ShuttleCard.css';
type Service = { id?: string; name: string; rate_text: string; comments: string };
type Config = { enabled: boolean; threshold_cuft: string; lower_fee: string; upper_fee: string; pickup_discount_percent: string; delivery_discount_percent: string };
export const ELEVATOR_PREFIX = '__elevator_pricing__:';
export const isElevatorCard = (service: Service) => service.comments.startsWith(ELEVATOR_PREFIX);
export default function ElevatorPricingCard({ services, editing, onChange }: { services: Service[]; editing: boolean; onChange: (rows: Service[]) => void }) {
  const existing = services.find(isElevatorCard);
  const defaults: Config = { enabled: false, threshold_cuft: '500', lower_fee: '150', upper_fee: '250', pickup_discount_percent: '0', delivery_discount_percent: '0' };
  const config: Config = { ...defaults, ...(existing ? JSON.parse(existing.comments.slice(ELEVATOR_PREFIX.length)) : {}) };
  function update(patch: Partial<Config>) {
    const row = { ...existing, name: 'Elevator pricing', rate_text: '', comments: ELEVATOR_PREFIX + JSON.stringify({ ...config, ...patch }) };
    onChange(existing ? services.map(s => s === existing ? row : s) : [...services, row]);
  }
  return <div className="pickup-areas">
    <p>Charge for elevator use at each address, based on the shipment volume.</p>
    <label><input type="checkbox" checked={config.enabled} disabled={!editing} onChange={e => update({ enabled: e.target.checked })} /> Enable elevator pricing questions</label>
    <div className="shuttle-settings">{(['threshold_cuft','lower_fee','upper_fee','pickup_discount_percent','delivery_discount_percent'] as const).map(field => <article key={field}><label>
      <strong>{{ threshold_cuft:'Volume threshold (cu ft)', lower_fee:'Fee up to and including threshold ($)', upper_fee:'Fee above threshold ($)', pickup_discount_percent:'Default pickup discount (%)', delivery_discount_percent:'Default delivery discount (%)' }[field]}</strong>
      {editing ? <input type="number" min={field === 'threshold_cuft' ? 1 : 0} max={field.endsWith('_percent') ? 100 : undefined} step={field === 'threshold_cuft' ? '1' : '0.01'} value={config[field]} onChange={e => update({ [field]: e.target.value })} /> : <span>{config[field]}</span>}
    </label></article>)}</div>
    <p>Set a default discount to 100% to waive that address's elevator charge. The original charge, discount, and $0 total will still appear on the estimate.</p>
    <p>The fee applies separately at pickup and delivery when an elevator is used. The tier uses shipment volume, not minimum billable volume.</p>
  </div>;
}
