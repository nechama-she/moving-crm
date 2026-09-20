type Service = { id?: string; name: string; rate_text: string; comments: string };
type BoxItem = { id: string; name: string; price: string };
type Config = { full: string; partial: string; unpacking: string; items: BoxItem[] };
export const PACKING_CARD_PREFIX = "__ld_packing__:";
export const isPackingCard = (service: Service) => service.comments.startsWith(PACKING_CARD_PREFIX);
export default function LongDistancePackingCard({ services, editing, onChange }: {
  services: Service[]; editing: boolean; onChange: (services: Service[]) => void;
}) {
  const existing = services.find(isPackingCard);
  const config: Config = existing ? JSON.parse(existing.comments.slice(PACKING_CARD_PREFIX.length)) : { full: "", partial: "", unpacking: "", items: [] };
  function update(patch: Partial<Config>) {
    const next = { ...config, ...patch };
    const row = { ...existing, name: "Long-distance packing", rate_text: "", comments: PACKING_CARD_PREFIX + JSON.stringify(next) };
    onChange(existing ? services.map(service => service === existing ? row : service) : [...services, row]);
  }
  const money = (value: string) => value === "" ? "Not configured" : Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  return <section className="pricing-card ld-packing-card">
    <span className="eyebrow">Long distance</span>
    <h3>Packing</h3>
    <p>Set packing and unpacking rates per cubic foot of the move.</p>
    <div className="ld-packing-rates">
      {([
        ['full', 'Full packing', 'Full packing service'],
        ['partial', 'Partial packing', 'Required-box items; all materials included. Excludes boxes of personal belongings.'],
        ['unpacking', 'Unpacking', 'Unpacking service'],
      ] as const).map(([key, title, description]) => <label key={key}>
        <strong>{title}</strong><small>{description}</small>
        {editing ? <span className="ld-packing-rate-input"><input type="number" min="0" step="0.01" aria-label={`${title} dollars per cubic foot`} placeholder="Not configured" value={config[key]} onChange={e => update({ [key]: e.target.value })} /><span>$/cu ft</span></span> : <b>{money(config[key])}{config[key] !== '' && ' / cu ft'}</b>}
      </label>)}
      <div><strong>No packing</strong><small>Customer packs their own items, with optional packing for individual items below.</small><b>No package charge</b></div>
    </div>
    <h4>Items that must be boxed</h4>
    <p>These items cannot be shipped with blanket wrapping alone. With no packing selected, the customer can pay us to pack individual items or pack them themselves. Boxing is required either way.</p>
    <div className="ld-box-items">
      {config.items.map(item => <div className="ld-box-item" key={item.id}>
        {editing ? <>
          <label>Item<input value={item.name} placeholder="Item name" onChange={e => update({ items: config.items.map(row => row.id === item.id ? { ...row, name: e.target.value } : row) })} /></label>
          <label>Packing price per item<input type="number" min="0" step="0.01" value={item.price} placeholder="0.00" onChange={e => update({ items: config.items.map(row => row.id === item.id ? { ...row, price: e.target.value } : row) })} /></label>
          <button type="button" className="slds-button text-danger" onClick={() => update({ items: config.items.filter(row => row.id !== item.id) })}>Remove</button>
        </> : <><strong>{item.name}</strong><span>{money(item.price)} / item</span><small>Must be boxed</small></>}
      </div>)}
      {!config.items.length && <p>No required-box items configured.</p>}
      {editing && <button type="button" className="slds-button" onClick={() => update({ items: [...config.items, { id: crypto.randomUUID(), name: '', price: '' }] })}>+ Add required-box item</button>}
    </div>
  </section>;
}
