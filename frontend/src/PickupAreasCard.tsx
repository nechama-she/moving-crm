import './PickupAreasCard.css';

export type PickupArea = { state: string; zip_codes: string[] };
export const states = 'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split(' ');

export default function PickupAreasCard({ areas, editing, onChange }: {
  areas: PickupArea[]; editing: boolean; onChange: (areas: PickupArea[]) => void;
}) {
  const update = (index: number, patch: Partial<PickupArea>) => onChange(areas.map((area, i) => i === index ? { ...area, ...patch } : area));
  return <div className="pickup-areas">
    <p className="pickup-areas-help">Choose where this pricing book accepts pickups. Leave ZIP codes blank to cover the whole state.</p>
    {areas.map((area, index) => <div className="pickup-area-row" key={index}>
      {editing ? <>
        <label>State<select aria-label={`Pickup state ${index + 1}`} value={area.state} onChange={event => update(index, { state: event.target.value, zip_codes: [] })}>
          <option value="">Select state</option>
          {states.map(state => <option key={state} value={state} disabled={areas.some((row, i) => i !== index && row.state === state)}>{state}</option>)}
        </select></label>
        <label>ZIP codes <span className="pickup-optional">(optional)</span><input aria-label={`Pickup ZIP codes ${index + 1}`} value={area.zip_codes.join(',')} placeholder="All ZIP codes, or enter 20850, 20852" onChange={event => update(index, { zip_codes: event.target.value.split(',') })} /></label>
        <button type="button" className="slds-button text-danger" onClick={() => onChange(areas.filter((_, i) => i !== index))}>Remove</button>
      </> : <>
        <strong className="pickup-state">{area.state}</strong>
        <div className="pickup-zip-list">{area.zip_codes.length ? area.zip_codes.map(zip => <span key={zip} className="pickup-zip">{zip}</span>) : <span className="pickup-whole-state">Whole state</span>}</div>
      </>}
    </div>)}
    {!areas.length && <p>No pickup areas configured.</p>}
    {editing && <button type="button" className="slds-button" disabled={areas.length >= states.length} onClick={() => onChange([...areas, { state: '', zip_codes: [] }])}>+ Add state</button>}
  </div>;
}
