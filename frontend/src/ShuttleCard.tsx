import { states } from './PickupAreasCard';
import './ShuttleCard.css';
type Service = { id?: string; name: string; rate_text: string; comments: string };
type Area = { state: string; zip_codes: string[] };
type Config = { enabled: boolean; rate: string; access_distance_ft: string; minimum_cubic_feet: string | null; areas: Area[] };
export const SHUTTLE_PREFIX = '__delivery_shuttle__:';
export const isShuttleCard = (service: Service) => service.comments.startsWith(SHUTTLE_PREFIX);
export default function ShuttleCard({ services, editing, onChange }: {
  services: Service[]; editing: boolean; onChange: (services: Service[]) => void;
}) {
  const existing = services.find(isShuttleCard);
  const config: Config = existing ? JSON.parse(existing.comments.slice(SHUTTLE_PREFIX.length)) : { enabled: false, rate: '', access_distance_ft: '500', minimum_cubic_feet: null, areas: [] };
  function update(patch: Partial<Config>) {
    const row = { ...existing, name: 'Delivery shuttle', rate_text: '', comments: SHUTTLE_PREFIX + JSON.stringify({ ...config, ...patch }) };
    onChange(existing ? services.map(s => s === existing ? row : s) : [...services, row]);
  }
  function areaChange(index: number, patch: Partial<Area>) {
    update({ areas: config.areas.map((area, i) => i === index ? { ...area, ...patch } : area) });
  }
  return <div className="pickup-areas">
    <p>Add shuttle service automatically for the delivery areas below. Elsewhere, ask the customer about semi-trailer access.</p>
    <label><input type="checkbox" checked={config.enabled} disabled={!editing} onChange={e => update({ enabled: e.target.checked })} /> Enable delivery shuttle</label>
    <div className="shuttle-settings">
      {(['rate', 'access_distance_ft', 'minimum_cubic_feet'] as const).map(field => <article key={field}>
        <label><strong>{{ rate: 'Rate per cu ft ($)', access_distance_ft: 'Maximum distance from delivery address (feet)', minimum_cubic_feet: 'Minimum billable cu ft' }[field]}</strong>
          {editing ? <input type="number" min={field === 'access_distance_ft' ? 1 : 0} step={field === 'rate' ? '0.01' : '1'} value={config[field] ?? ''} placeholder={field === 'minimum_cubic_feet' ? 'Use pricing book minimum' : 'Required'} onChange={e => update({ [field]: field === 'minimum_cubic_feet' && e.target.value === '' ? null : e.target.value })} /> : <span>{config[field] === '' ? 'Not configured' : config[field] ?? 'Use pricing book minimum'}</span>}
        </label>
      </article>)}
    </div>
    <h4>Automatic shuttle delivery areas</h4>
    <p>Leave ZIP codes blank for the whole state. Separate rules with commas: 13544, 111XX-12XXX. X matches any digit; ranges include both ends.</p>
    {config.areas.map((area, index) => <div className="pickup-area-row" key={index}>
      <label>State{editing ? <select value={area.state} onChange={e => areaChange(index, { state: e.target.value })}><option value="">Select state</option>{states.map(state => <option key={state}>{state}</option>)}</select> : <strong>{area.state}</strong>}</label>
      <label>ZIP codes or ranges (optional){editing ? <input value={area.zip_codes.join(',')} placeholder="Whole state, or 111XX-12XXX, 13544" onChange={e => areaChange(index, { zip_codes: e.target.value.split(',') })} /> : <span>{area.zip_codes.join(', ') || 'Whole state'}</span>}</label>
      {editing && <button type="button" className="slds-button text-danger" onClick={() => update({ areas: config.areas.filter((_, i) => i !== index) })}>Remove</button>}
    </div>)}
    {!config.areas.length && <p>No automatic areas configured. Customers will be asked about delivery access when shuttle is enabled.</p>}
    {editing && <button type="button" className="slds-button" onClick={() => update({ areas: [...config.areas, { state: '', zip_codes: [] }] })}>+ Add state</button>}
    <p><strong>Customer question:</strong> Can a semi-trailer truck reach and park in front of your delivery address, or within {config.access_distance_ft || '…'} feet of it?</p>
  </div>;
}
