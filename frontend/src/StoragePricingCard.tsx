import './ShuttleCard.css';
type Service = { id?: string; name: string; rate_text: string; comments: string };
type Config = { enabled: boolean; free_days: string; period_days: string; rate_per_cuft: string; minimum_cubic_feet: string | null };
export const STORAGE_PREFIX = '__storage_periods__:';
export const isStorageCard = (s: Service) => s.comments.startsWith(STORAGE_PREFIX);
export default function StoragePricingCard({ services, editing, onChange }: { services: Service[]; editing: boolean; onChange: (rows: Service[]) => void }) {
  const existing = services.find(isStorageCard);
  const config: Config = existing ? JSON.parse(existing.comments.slice(STORAGE_PREFIX.length)) : { enabled: false, free_days: '30', period_days: '30', rate_per_cuft: '0.50', minimum_cubic_feet: null };
  function update(patch: Partial<Config>) {
    const row = { ...existing, name: 'Storage pricing', rate_text: '', comments: STORAGE_PREFIX + JSON.stringify({ ...config, ...patch }) };
    onChange(existing ? services.map(s => s === existing ? row : s) : [...services, row]);
  }
  return <div className="pickup-areas">
    <p>Ask customers for their earliest delivery date and calculate storage from the pickup date.</p>
    <label><input type="checkbox" checked={config.enabled} disabled={!editing} onChange={e => update({ enabled: e.target.checked })} /> Enable storage pricing question</label>
    <div className="shuttle-settings">{(['free_days','period_days','rate_per_cuft','minimum_cubic_feet'] as const).map(field => <article key={field}><label>
      <strong>{{ free_days: 'Free storage days', period_days: 'Additional billing period (days)', rate_per_cuft: 'Charge per cu ft per additional period ($)', minimum_cubic_feet: 'Minimum billable cu ft' }[field]}</strong>
      {editing ? <input type="number" min={field === 'period_days' ? 1 : 0} step={field === 'rate_per_cuft' ? '0.01' : '1'} value={config[field] ?? ''} placeholder={field === 'minimum_cubic_feet' ? 'Use pricing book minimum' : 'Required'} onChange={e => update({ [field]: field === 'minimum_cubic_feet' && !e.target.value ? null : e.target.value })} /> : <span>{config[field] ?? 'Use pricing book minimum'}</span>}
    </label></article>)}</div>
    <p>Each partial period after the free days counts as one full paid period. This card replaces imported storage choices for this pricing book.</p>
    <p><strong>Customer question:</strong> What is the earliest date you can receive your shipment?</p>
    <p>The first {config.free_days || '…'} days after pickup are free. After that, storage costs ${config.rate_per_cuft || '…'} per cu ft for each additional {config.period_days || '…'} days or part thereof.</p>
  </div>;
}
