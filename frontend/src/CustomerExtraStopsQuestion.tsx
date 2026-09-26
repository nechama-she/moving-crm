import {useState} from 'react';
import CustomerAddressInput from './CustomerAddressInput';
export type ExtraStopGroup={location:'pickup'|'delivery';origin:string;answer:boolean|null;free_miles:number;stop_fee:number;per_mile:number;stops:{id:string;address:string;miles:number|null;total:number|null}[]};
export type ExtraStopsOption={locations:ExtraStopGroup[]};
const money=(n:number)=>n.toLocaleString('en-US',{style:'currency',currency:'USD'});
export default function CustomerExtraStopsQuestion({group,apiKey,onChange,onIncomplete,missing}:{group:ExtraStopGroup;apiKey:string;onChange:(answer:boolean,stops:string[])=>void;onIncomplete:(incomplete:boolean)=>void;missing:boolean}){
 const [answer,setAnswer]=useState(group.answer);
 const [rows,setRows]=useState(()=>group.stops.map(row=>({id:row.id,address:row.address,confirmed:true})));
 function choose(value:boolean){setAnswer(value);if(value){if(!rows.length)setRows([{id:crypto.randomUUID(),address:'',confirmed:false}]);onIncomplete(!rows.length||rows.some(r=>!r.confirmed));onChange(true,rows.filter(r=>r.confirmed).map(r=>r.address));}else{setRows([]);onIncomplete(false);onChange(false,[]);}}
 function select(id:string,address:string){const next=rows.map(r=>r.id===id?{...r,address,confirmed:true}:r);setRows(next);onIncomplete(next.some(r=>!r.confirmed));onChange(true,next.filter(r=>r.confirmed).map(r=>r.address));}
 function remove(id:string){const next=rows.filter(r=>r.id!==id);setRows(next);if(!next.length)setAnswer(false);onIncomplete(next.some(r=>!r.confirmed));onChange(next.length>0,next.filter(r=>r.confirmed).map(r=>r.address));}
 return <section><h4>Do you need any additional {group.location} stops?</h4><p>Main {group.location}: {group.origin}</p>
 <div style={{display:'flex',gap:16}}>{[true,false].map(value=><label key={String(value)}><input type="radio" name={'extra-'+group.location} checked={answer===value} onChange={()=>choose(value)}/> {value?'Yes':'No'}</label>)}</div>
 <p>{group.free_miles>0?`Stops up to ${group.free_miles} miles away are free. Beyond that: `:''}{money(group.stop_fee)} per chargeable stop + {money(group.per_mile)} per mile{group.free_miles>0?` beyond ${group.free_miles} miles`:''}.</p>
 {answer && <><p>Select each address from the Google Maps suggestions.</p>{rows.map((row,index)=>{const saved=group.stops.find(r=>r.address===row.address);return <div key={row.id} style={{border:'1px solid #e5d8d5',borderRadius:10,padding:14,paddingRight:48,marginBottom:12,position:'relative'}}><CustomerAddressInput label={`Extra ${group.location} stop ${index+1}`} apiKey={apiKey} initialValue={row.address} disabled={false} error={missing&&!row.confirmed?'Select an address from the suggestions.':undefined} onChange={text=>{setRows(old=>old.map(r=>r.id===row.id?{...r,address:text,confirmed:false}:r));onIncomplete(true);}} onSelect={address=>select(row.id,address)}/>
 {row.confirmed&&saved&&<p>{saved.miles===null?'Mileage not calculated':`${saved.miles} driving miles from main ${group.location}`}<strong style={{float:'right'}}>{saved.total===null?'':saved.total===0?'Free':money(saved.total)}</strong></p>}
 <button type="button" aria-label={`Remove extra ${group.location} stop ${index+1}`} title="Remove stop" style={{position:'absolute',top:8,right:8,width:28,height:28,minHeight:28,padding:0,border:0,background:'transparent',color:'inherit',fontSize:20,cursor:'pointer'}} onClick={()=>remove(row.id)}>&times;</button></div>;})}<button type="button" className="cm-secondary-btn" onClick={()=>{setRows(old=>[...old,{id:crypto.randomUUID(),address:'',confirmed:false}]);onIncomplete(true);}}>+ Add another {group.location} stop</button></>}
 {missing&&<p className="cm-field-error" role="alert">Choose No, or add and select each additional stop address.</p>}</section>;
}
