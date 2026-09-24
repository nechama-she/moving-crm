import DeliveryDateCalendar, { storagePeriods } from './DeliveryDateCalendar';
export type StorageOption = { question: string; pickup_date: string; available_date: string; valid: boolean; free_days: number; period_days: number; rate_per_cuft: number; cubic_feet: number; inventory_cubic_feet: number; minimum_cubic_feet: number; paid_periods: number; billed_days: number; elapsed_days: number | null; total: number };
const money = (value: number) => value.toLocaleString('en-US',{style:'currency',currency:'USD'});
export default function CustomerStorageQuestion({ config, value, missing, onChange }: { config: StorageOption; value: string; missing: boolean; onChange: (date: string) => void }) {
  const valid = Boolean(value && config.pickup_date && value >= config.pickup_date);
  const calculated = valid ? storagePeriods(config.pickup_date,value,config.free_days,config.period_days) : null;
  const total = calculated ? Math.round(calculated.periods * config.cubic_feet * config.rate_per_cuft * 100)/100 : 0;
  return <section aria-label="Delivery date and storage" aria-invalid={missing} style={{border:missing ? '1px solid #d32f2f' : undefined,borderRadius:12,padding:missing ? 12 : undefined}}>
    <h4>{config.question}</h4>
    <p>Your first <strong>{config.free_days} days</strong> after pickup are free. After that, storage costs <strong>{money(config.rate_per_cuft)} per cu ft</strong> for each additional <strong>{config.period_days} days or part thereof</strong>.</p>
    {config.pickup_date ? <DeliveryDateCalendar key={config.pickup_date} value={value} minDate={config.pickup_date} freeDays={config.free_days} onChange={onChange} /> : <p>Confirm your pickup date before choosing your earliest delivery date.</p>}
    {missing && <p className="cm-field-error" role="alert">Choose a date on or after pickup.</p>}
    {calculated && <div className="cm-packing-total">
      <p>{calculated.elapsed} days after pickup · {calculated.periods} paid {config.period_days}-day period{calculated.periods === 1 ? '' : 's'}</p>
      {calculated.periods > 0 && <p>{config.cubic_feet} billable cu ft × {money(config.rate_per_cuft)} × {calculated.periods} period{calculated.periods === 1 ? '' : 's'}</p>}
      {config.minimum_cubic_feet > config.inventory_cubic_feet && <p>Inventory: {config.inventory_cubic_feet} cu ft · Minimum billable: {config.minimum_cubic_feet} cu ft</p>}
      <strong>Storage charge: {money(total)}</strong>
    </div>}
  </section>;
}
