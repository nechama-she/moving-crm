type Service = { id?: string; name: string; rate_text: string; comments: string };
type BoxItem = { id: string; name: string; price?: string; labor_price?: string; material_price?: string };
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
  return <div className="ld-packing-card">
    <p>Set packing and unpacking rates per cubic foot of the move.</p>
    <div className="pricing-services pricing-packing-rates">
      {([
        ['full', 'Full packing', 'Full packing service'],
        ['partial', 'Partial packing', 'Required-box items; all materials included. Excludes boxes of personal belongings.'],
        ['unpacking', 'Unpacking', 'Unpacking service'],
      ] as const).map(([key, title, description]) => <article key={key}>
        <div><strong>{title}</strong><small>{description}</small></div>
        {editing ? <span className="ld-packing-rate-input"><input type="number" min="0" step="0.01" aria-label={`${title} dollars per cubic foot`} placeholder="Not configured" value={config[key]} onChange={e => update({ [key]: e.target.value })} /><span>$/cu ft</span></span> : <b>{money(config[key])}{config[key] !== '' && ' / cu ft'}</b>}
      </article>)}
      <article><div><strong>No packing</strong><small>Customer packs their own items, with optional packing for individual items below.</small></div><b>No package charge</b></article>
    </div>
    <h4>Items that must be boxed</h4>
    <p>These items cannot be shipped with blanket wrapping alone. With no packing selected, the customer can pay us to pack individual items or pack them themselves. Boxing is required either way. Customers can select labor only, or labor and materials. Materials always include labor.</p>
    <div className="ld-box-table-wrap">
      <table className="slds-table slds-table_bordered ld-box-table" aria-label="Items that must be boxed">
        <thead><tr>
          <th scope="col">Item</th>
          <th scope="col" className="ld-box-price">Labor / item</th>
          <th scope="col" className="ld-box-price">Materials / item</th>
          {editing && <th scope="col" className="ld-box-action"><button type="button" className="slds-button ld-box-icon" aria-label="Add required-box item" title="Add item" onClick={() => update({ items: [...config.items, { id: crypto.randomUUID(), name: '', labor_price: '', material_price: '' }] })}>+</button></th>}
        </tr></thead>
        <tbody>
          {config.items.map((item, index) => <tr key={item.id}>
            <td>{editing ? <input className="slds-input" aria-label={`Item ${index + 1} name`} value={item.name} placeholder="Item name" onChange={e => update({ items: config.items.map(row => row.id === item.id ? { ...row, name: e.target.value } : row) })} /> : item.name}</td>
            {(['labor_price','material_price'] as const).map(field => <td key={field} className="ld-box-price">{editing ? <input className="slds-input" aria-label={`Item ${index + 1} ${field === 'labor_price' ? 'labor' : 'materials'} price`} type="number" min="0" step="0.01" value={item[field] ?? (field === 'labor_price' ? item.price ?? '' : '0')} placeholder="0.00" onChange={e => update({ items: config.items.map(row => row.id === item.id ? { ...row, labor_price: row.labor_price ?? row.price ?? '0', material_price: row.material_price ?? '0', [field]: e.target.value } : row) })} /> : money(item[field] ?? (field === 'labor_price' ? item.price ?? '0' : '0'))}</td>)}
            {editing && <td className="ld-box-action"><button type="button" className="slds-button ld-box-icon" aria-label={`Remove ${item.name || `item ${index + 1}`}`} title="Remove item" onClick={() => update({ items: config.items.filter(row => row.id !== item.id) })}>&times;</button></td>}
          </tr>)}
          {!config.items.length && <tr><td colSpan={editing ? 4 : 3} className="ld-box-empty">No required-box items configured.{editing && ' Use + to add an item.'}</td></tr>}
        </tbody>
      </table>
    </div>
  </div>;
}
