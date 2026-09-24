import './CustomerStorageQuestion.css';
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
    {calculated && <section className="cm-storage-summary" aria-label="Storage cost breakdown">
      <h4>Your storage estimate</h4>
      <dl>
        <div><dt>Pickup to earliest delivery</dt><dd>{calculated.elapsed} days</dd></div>
        <div><dt>Free storage allowance</dt><dd>{config.free_days} days</dd></div>
        <div><dt>Days beyond the free allowance</dt><dd>{Math.max(0, calculated.elapsed - config.free_days)} days</dd></div>
        {calculated.periods > 0 && <div><dt>Charged as</dt><dd>{calculated.periods} &times; {config.period_days}-day period{calculated.periods === 1 ? '' : 's'}</dd></div>}
      </dl>
      {calculated.periods > 0 ? <div className="cm-storage-summary-basis">
        <p>{config.cubic_feet} cu ft &times; {money(config.rate_per_cuft)} &times; {calculated.periods} period{calculated.periods === 1 ? '' : 's'}</p>
        {config.minimum_cubic_feet > config.inventory_cubic_feet && <p>Your inventory is {config.inventory_cubic_feet} cu ft. The minimum billable volume is {config.minimum_cubic_feet} cu ft.</p>}
        <p>Each started {config.period_days}-day period is charged in full.</p>
      </div> : <p className="cm-storage-summary-free">Your selected date is within the free storage allowance.</p>}
      <div className="cm-storage-summary-total"><span>Storage total</span><strong>{money(total)}</strong></div>
    </section>}
  </section>;
}
