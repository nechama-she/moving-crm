import { useState } from 'react';
import './LeadMeasurements.css';

export default function LeadMeasurements({volume,weight,editable,onSave}:{volume:number;weight:number;editable:boolean;onSave:(values:{volume:number;weight:number})=>Promise<void>}) {
  const [editing,setEditing]=useState(false),[cuft,setCuft]=useState(''),[lbs,setLbs]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  if(!editing)return <button className="measurement-value" disabled={!editable} title={editable?'Edit volume and weight':undefined} onClick={()=>{setCuft(String(volume));setLbs(String(weight));setError('');setEditing(true);}}>{volume.toLocaleString()} cu ft <span>/</span> {weight.toLocaleString()} lb {editable&&<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m16 3 5 5-12 12-6 1 1-6Z M13 6l5 5"/></svg>}</button>;
  return <form className="measurement-edit" onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{await onSave({volume:Number(cuft),weight:Number(lbs)});setEditing(false);}catch(err){setError((err as Error).message);}finally{setBusy(false);}}}>
    <div><label>Volume (cu ft)<input autoFocus required type="number" min="0" step="0.01" value={cuft} onChange={e=>setCuft(e.target.value)}/></label><label>Weight (lb)<input required type="number" min="0" step="0.01" value={lbs} onChange={e=>setLbs(e.target.value)}/></label></div>
    <footer><button type="button" disabled={busy} onClick={()=>setEditing(false)}>Cancel</button><button className="measurement-save" disabled={busy}>{busy?'Saving...':'Save'}</button></footer>{error&&<p role="alert">{error}</p>}
  </form>;
}
