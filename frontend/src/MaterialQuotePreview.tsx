import { useState } from 'react';
import { API_BASE } from './apiConfig';
import { authHeaders, useAuth } from './AuthContext';
import type { Material } from './LongDistanceMaterialsCard';
export default function MaterialQuotePreview({materials}:{materials:Material[]}) {
  const {token}=useAuth();
  const [type,setType]=useState('any');
  const [variant,setVariant]=useState('');
  const [protection,setProtection]=useState('fabric');
  const [volume,setVolume]=useState('');
  const [inches,setInches]=useState('');
  const [quantity,setQuantity]=useState(1);
  const [busy,setBusy]=useState(false);
  const [result,setResult]=useState('');
  async function calculate() {
    setBusy(true);setResult('');
    try {
      const response=await fetch(`${API_BASE}/api/pricing/materials/preview`,{method:'POST',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify({materials,item:{protection,item_type:type,variant,cubic_feet:volume||null,screen_inches:inches||null,quantity}})});
      const body=await response.json();
      if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Check material rules and rates for invalid values.');
      const money=(value:number)=>Number(value).toLocaleString('en-US',{style:'currency',currency:'USD'});
      setResult(body.status==='priced'?`${body.lines.map((line:{quantity:number;unit:string;name:string})=>`${line.quantity} ${line.unit}: ${line.name}`).join('\n')}\nPacking only: ${money(body.packing_only)}\nPacking and material: ${money(body.packing_and_material)}`:body.issues.join('\n'));
    }catch(error){setResult((error as Error).message);}finally{setBusy(false);}
  }
  return <details style={{marginTop:16}}><summary>Test material calculation</summary><div onChange={()=>setResult('')} style={{display:'flex',flexWrap:'wrap',gap:12,padding:'12px 0'}}>
    <label>Protection<select value={protection} onChange={e=>setProtection(e.target.value)}>{['fabric','fragile','both'].map(value=><option key={value}>{value}</option>)}</select></label>
    <label>Item type<input value={type} onChange={e=>setType(e.target.value)}/></label>
    <label>Size / variant<input value={variant} onChange={e=>setVariant(e.target.value)}/></label>
    <label>Cu ft per item<input type="number" min="0.01" value={volume} onChange={e=>setVolume(e.target.value)}/></label>
    <label>Screen inches<input type="number" min="0.01" value={inches} onChange={e=>setInches(e.target.value)}/></label>
    <label>Item quantity<input type="number" min="1" max="1000" step="1" value={quantity} onChange={e=>setQuantity(Number(e.target.value))}/></label>
    <button type="button" className="slds-button" disabled={busy} onClick={()=>void calculate()}>{busy?'Calculating...':'Calculate'}</button>
  </div>{result && <pre role="status" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{result}</pre>}</details>;
}
