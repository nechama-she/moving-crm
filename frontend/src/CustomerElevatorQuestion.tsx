import './CustomerStorageQuestion.css';
export type ElevatorLocation = { location:'pickup' | 'delivery'; address:string; revision:string; uses_elevator:boolean | null; discount_percent:number; question:string };
export type ElevatorOption = { threshold_cuft:number; lower_fee:number; upper_fee:number; cubic_feet:number; fee:number; locations:ElevatorLocation[] };
const money = (n:number) => n.toLocaleString('en-US',{style:'currency',currency:'USD'});
export default function CustomerElevatorQuestion({config,location,value,missing,onChange}:{config:ElevatorOption;location:ElevatorLocation;value:boolean|null;missing:boolean;onChange:(value:boolean)=>void}) {
  const subtotal = value ? config.fee : 0;
  const discount = Math.round(subtotal*location.discount_percent)/100;
  return <fieldset style={{border:missing ? '1px solid #d32f2f' : '1px solid #e5d8d5',borderRadius:12,padding:18}} aria-invalid={missing}>
    <legend>{location.location === 'pickup' ? 'Pickup' : 'Delivery'} address</legend>
    <p>{location.address}</p><h4>{location.question}</h4>
    <div style={{display:'flex',gap:12}}>{[true,false].map(answer => <label key={String(answer)} className="cm-secondary-btn" style={{display:'flex',alignItems:'center',gap:8}}><input type="radio" name={`elevator-${location.location}`} checked={value === answer} onChange={() => onChange(answer)} />{answer ? 'Yes' : 'No'}</label>)}</div>
    {missing && <p className="cm-field-error" role="alert">Choose Yes or No for this address.</p>}
    <p>{money(config.lower_fee)} for shipments up to {config.threshold_cuft} cu ft; {money(config.upper_fee)} above {config.threshold_cuft} cu ft.</p>
    {value !== null && <div className="cm-storage-summary">
      <dl><div><dt>Shipment volume</dt><dd>{config.cubic_feet} cu ft</dd></div><div><dt>Elevator use</dt><dd>{value ? 'Yes' : 'No'}</dd></div></dl>
      {discount > 0 && <p>Before discount: {money(subtotal)}. Discount ({location.discount_percent}%): -{money(discount)}</p>}
      <div className="cm-storage-summary-total"><span>Elevator total</span><strong>{money(subtotal-discount)}</strong></div>
    </div>}
  </fieldset>;
}
