import './ShuttleCard.css';
type Service = { id?: string; name: string; rate_text: string; comments: string };
type Config = { enabled: boolean; tiers: { up_to_cuft: string | number | null; fee: string | number }[]; pickup_discount_percent: string; delivery_discount_percent: string };
export const ELEVATOR_PREFIX = '__elevator_pricing__:';
export const isElevatorCard = (service: Service) => service.comments.startsWith(ELEVATOR_PREFIX);
export default function ElevatorPricingCard({ services, editing, onChange }: { services: Service[]; editing: boolean; onChange: (rows: Service[]) => void }) {
  const existing = services.find(isElevatorCard);
  const defaults: Config = { enabled: false, tiers: [{up_to_cuft:500,fee:150},{up_to_cuft:null,fee:250}], pickup_discount_percent: '0', delivery_discount_percent: '0' };
  const saved = existing ? JSON.parse(existing.comments.slice(ELEVATOR_PREFIX.length)) : {};
  const config: Config = { ...defaults, ...saved, tiers: saved.tiers ?? (saved.threshold_cuft != null ? [{up_to_cuft:saved.threshold_cuft,fee:saved.lower_fee},{up_to_cuft:null,fee:saved.upper_fee}] : defaults.tiers) };
  const updateTier = (index:number, patch:Partial<Config['tiers'][number]>) => update({tiers:config.tiers.map((tier,i) => i === index ? {...tier,...patch} : tier)});
  function update(patch: Partial<Config>) {
    const row = { ...existing, name: 'Elevator pricing', rate_text: '', comments: ELEVATOR_PREFIX + JSON.stringify({ ...config, ...patch }) };
    onChange(existing ? services.map(s => s === existing ? row : s) : [...services, row]);
  }
  return <div className="pickup-areas">
    <p>Charge for elevator use at each address, based on the shipment volume.</p>
    <label><input type="checkbox" checked={config.enabled} disabled={!editing} onChange={e => update({ enabled: e.target.checked })} /> Enable elevator pricing questions</label>
    <div style={{overflowX:'auto',marginTop:16}}><table className="slds-table slds-table_bordered" aria-label="Elevator volume tiers">
      <thead><tr><th>Shipment volume (cu ft)</th><th>Fee per address ($)</th>{editing && <th>Actions</th>}</tr></thead>
      <tbody>{config.tiers.map((tier,index) => <tr key={index}>
        <td>{tier.up_to_cuft === null ? (index ? `Above ${config.tiers[index-1].up_to_cuft || 'previous threshold'}` : 'All volumes') : <label style={{display:'flex',alignItems:'center',gap:8}}>Up to {editing ? <input className="slds-input" style={{maxWidth:160}} aria-label={`Tier ${index+1} upper volume`} type="number" min="1" step="1" value={tier.up_to_cuft} onChange={e => updateTier(index,{up_to_cuft:e.target.value})} /> : tier.up_to_cuft}</label>}</td>
        <td>{editing ? <input className="slds-input" style={{maxWidth:160}} aria-label={`Tier ${index+1} fee`} type="number" min="0" step="0.01" value={tier.fee} onChange={e => updateTier(index,{fee:e.target.value})} /> : `$${Number(tier.fee).toFixed(2)}`}</td>
        {editing && <td>{tier.up_to_cuft !== null && <button type="button" className="slds-button" onClick={() => update({tiers:config.tiers.filter((_,i) => i!==index)})}>Remove</button>}</td>}
      </tr>)}</tbody>
    </table></div>
    {editing && <button type="button" className="slds-button" style={{marginTop:12}} onClick={() => update({tiers:[...config.tiers.slice(0,-1),{up_to_cuft:'',fee:''},config.tiers[config.tiers.length-1]]})}>+ Add threshold</button>}
    <p>Enter thresholds in increasing order. Each fee covers volumes above the preceding threshold, up to and including its limit.</p>
    <div className="shuttle-settings">{(['pickup_discount_percent','delivery_discount_percent'] as const).map(field => <article key={field}><label>
      <strong>{field === 'pickup_discount_percent' ? 'Default pickup discount (%)' : 'Default delivery discount (%)'}</strong>
      {editing ? <input type="number" min="0" max="100" step="0.01" value={config[field]} onChange={e => update({ [field]: e.target.value })} /> : <span>{config[field]}</span>}
    </label></article>)}</div>
    <p>Set a default discount to 100% to waive that address's elevator charge. The original charge, discount, and $0 total will still appear on the estimate.</p>
    <p>The fee applies separately at pickup and delivery when an elevator is used. The tier uses shipment volume, not minimum billable volume.</p>
  </div>;
}
