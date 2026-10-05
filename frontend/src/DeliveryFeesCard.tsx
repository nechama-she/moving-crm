import { states } from './PickupAreasCard';
import './ShuttleCard.css';
type Service = { id?: string; name: string; rate_text: string; comments: string };
type Rule = { state: string; zip_codes: string[]; origin_zip: string; rate_per_mile: string };
type Config = { enabled: boolean; rules: Rule[] };
export const DELIVERY_FEE_PREFIX = '__delivery_mileage__:';
export const ORIGIN_FEE_PREFIX = '__origin_mileage__:';
export const isOriginFeesCard = (s: Service) => s.comments.startsWith(ORIGIN_FEE_PREFIX);
export const isDeliveryFeesCard = (s: Service) => s.comments.startsWith(DELIVERY_FEE_PREFIX);
export default function DeliveryFeesCard({ services, editing, onChange, origin = false }: {
  origin?: boolean; services: Service[]; editing: boolean; onChange: (services: Service[]) => void;
}) {
  const prefix = origin ? ORIGIN_FEE_PREFIX : DELIVERY_FEE_PREFIX;
  const endpoint = origin ? 'pickup' : 'delivery';
  const label = origin ? 'Pickup' : 'Delivery';
  const feeLabel = origin ? 'origin' : 'destination';
  const existing = services.find(origin ? isOriginFeesCard : isDeliveryFeesCard);
  const config: Config = existing ? JSON.parse(existing.comments.slice(prefix.length)) : { enabled: false, rules: [] };
  function update(patch: Partial<Config>) {
    const row = { ...existing, name: origin ? 'Origin fees' : 'Destination fees', rate_text: '', comments: prefix + JSON.stringify({ ...config, ...patch }) };
    onChange(existing ? services.map(s => s === existing ? row : s) : [...services, row]);
  }
  function change(index: number, patch: Partial<Rule>) {
    update({ rules: config.rules.map((r, i) => i === index ? { ...r, ...patch } : r) });
  }
  return <div className="pickup-areas">
    <p>For matching {endpoint} addresses, calculate the fee using Google Maps driving miles from the ZIP you choose below to the customer's {endpoint} address.</p>
    <label><input type="checkbox" checked={config.enabled} disabled={!editing} onChange={e => update({ enabled: e.target.checked })} /> Enable {feeLabel} fees</label>
    <p>Leave {endpoint} ZIP codes blank for the whole state, or combine ZIPs and ranges: 111XX–12XXX, 13544. The narrowest matching ZIP rule wins; equally specific matches use the first row.</p>
    {config.rules.map((rule, index) => <section key={index} className="delivery-fee-rule">
      <div className="pickup-area-row">
        <label>{label} state{editing ? <select value={rule.state} onChange={e => change(index, { state: e.target.value })}><option value="">Select state</option>{states.map(state => <option key={state}>{state}</option>)}</select> : <strong>{rule.state}</strong>}</label>
        <label>{label} ZIPs or ranges (optional){editing ? <input value={rule.zip_codes.join(',')} placeholder="Whole state, or 111XX–12XXX, 13544" onChange={e => change(index, { zip_codes: e.target.value.split(',') })} /> : <span>{rule.zip_codes.join(', ') || 'Whole state'}</span>}</label>
        {editing && <button type="button" className="slds-button text-danger" onClick={() => update({ rules: config.rules.filter((_, i) => i !== index) })}>Remove</button>}
      </div>
      <div className="pickup-area-row">
        <label>Calculate mileage from ZIP{editing ? <input inputMode="numeric" maxLength={5} value={rule.origin_zip} placeholder="e.g. 20815" onChange={e => change(index, { origin_zip: e.target.value })} /> : <strong>{rule.origin_zip}</strong>}<small>Measure driving miles from this ZIP to the customer's {endpoint} address.</small></label>
        <label>Rate per driving mile ($){editing ? <input type="number" min="0" step="0.01" value={rule.rate_per_mile} placeholder="e.g. 5.00" onChange={e => change(index, { rate_per_mile: e.target.value })} /> : <strong>${Number(rule.rate_per_mile).toFixed(2)} / mile</strong>}</label>
      </div>
    </section>)}
    {!config.rules.length && <p>No {feeLabel} fees configured.</p>}
    {editing && <button type="button" className="slds-button" onClick={() => update({ rules: [...config.rules, { state: '', zip_codes: [], origin_zip: '', rate_per_mile: '' }] })}>+ Add {endpoint} area</button>}
    <p>Mileage is one-way, rounded to two decimals. Google uses the mapped location of the ZIP you choose. A full {endpoint} address gives a more precise endpoint than a {endpoint} ZIP alone.</p>
  </div>;
}
