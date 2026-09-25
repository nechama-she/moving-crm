import './ShuttleCard.css';
type Service={id?:string;name:string;rate_text:string;comments:string};
type Rate={free_miles:string;stop_fee:string;per_mile:string};
type Config={enabled:boolean;pickup:Rate;delivery:Rate};
export const EXTRA_STOPS_PREFIX='__extra_stops__:';
export const isExtraStopsCard=(s:Service)=>s.comments.startsWith(EXTRA_STOPS_PREFIX);
export default function ExtraStopsPricingCard({services,editing,onChange}:{services:Service[];editing:boolean;onChange:(s:Service[])=>void}){
 const existing=services.find(isExtraStopsCard);
 const config:Config=existing?JSON.parse(existing.comments.slice(EXTRA_STOPS_PREFIX.length)):{enabled:false,pickup:{free_miles:'10',stop_fee:'50',per_mile:'5'},delivery:{free_miles:'0',stop_fee:'50',per_mile:'5'}};
 function update(patch:Partial<Config>){const row={...existing,name:'Extra stops',rate_text:'',comments:EXTRA_STOPS_PREFIX+JSON.stringify({...config,...patch})};onChange(existing?services.map(s=>s===existing?row:s):[...services,row]);}
 return <div className="pickup-areas"><p>Driving miles are measured from the main address to each extra stop, separately for pickup and delivery.</p>
 <label><input type="checkbox" disabled={!editing} checked={config.enabled} onChange={e=>update({enabled:e.target.checked})}/> Enable extra-stop questions and pricing</label>
 {(['pickup','delivery'] as const).map(location=><section key={location}><h4>Extra {location} stops</h4><div className="shuttle-settings">{(['free_miles','stop_fee','per_mile'] as const).map(field=><article key={field}><label><strong>{{free_miles:'First how many miles are free?',stop_fee:'Fee per chargeable stop ($)',per_mile:'Price per mile beyond free miles ($)'}[field]}</strong>{editing?<input type="number" min="0" step="0.01" value={config[location][field]} onChange={e=>update({[location]:{...config[location],[field]:e.target.value}})}/>:<span>{config[location][field]}</span>}</label></article>)}</div></section>)}
 <p>Stops within a positive free-mile allowance are completely free. Above it, charge the stop fee plus mileage beyond the allowance. With zero free miles, the stop fee applies to every extra stop.</p></div>;
}
