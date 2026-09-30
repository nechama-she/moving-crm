export type PackingMaterialService = 'self' | 'packing' | 'materials';

const money = (value: number) => value.toLocaleString('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 2,
});

export default function PackingServiceSelect({
  label,
  value,
  packingPrice,
  materialsPrice,
  disabled = false,
  available = true,
  onChange,
}: {
  label: string;
  value: PackingMaterialService;
  packingPrice: number;
  materialsPrice: number;
  disabled?: boolean;
  available?: boolean;
  onChange: (service: PackingMaterialService) => void;
}) {
  return <select
    className="cm-material-service-select"
    aria-label={`Packing service for ${label}`}
    disabled={disabled || !available}
    value={available ? value : 'self'}
    onChange={event => onChange(event.target.value as PackingMaterialService)}
  >
    <option value="self">You pack it</option>
    {available && <option value="packing">Movers pack - {money(packingPrice)}</option>}
    {available && <option value="materials">Movers provide + pack - {money(materialsPrice)}</option>}
  </select>;
}
