import "./LeadMeasurements.css";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Meeting={id:string;status:string;availability:string;timezone:string;scheduled_at:string|null;assigned_to:string};
type Page={url:string;revoked:boolean;company_id:string;job_id:string;price:string;cuft:string;published:boolean;pending_uploads:number;requests:Meeting[]};
type SyncStatus={files:{id:string;name:string;status:string;error:string}[];pending:number;active:number;synced:number;failed:number};
export default function CustomerPageControls({leadId}:{leadId:string}){
 const {token,user}=useAuth();const [data,setData]=useState<Page>(),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
 const base=`${API_BASE}/api/leads/${leadId}/customer-page`;
 const [syncInfo,setSyncInfo]=useState<SyncStatus>(),[syncError,setSyncError]=useState('');
 const hasPage=!!data;
 const load=useCallback(async()=>{const r=await fetch(base,{headers:authHeaders(token)});if(r.status===404||r.status===403)return;if(!r.ok)throw new Error('Could not load customer page');const d=await r.json();setData(d);},[base,token]);
 useEffect(()=>{void load().catch(e=>setMessage(e.message));},[load]);
 useEffect(()=>{
  setSyncInfo(undefined);setSyncError('');
  if(!hasPage)return;
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
  async function poll(){
   try{
	const r=await fetch(base+'/sync-status',{headers:authHeaders(token),signal:controller.signal,cache:'no-store'});
	if(!r.ok)throw new Error('Could not refresh file sync status. Reconnecting...');
	const status:SyncStatus=await r.json();
	if(!controller.signal.aborted){setSyncInfo(status);setSyncError('');}
   }catch(e){if(!controller.signal.aborted)setSyncError((e as Error).message);}
   finally{if(!controller.signal.aborted)timer=setTimeout(()=>void poll(),4000);}
  }
  void poll();
  return ()=>{controller.abort();clearTimeout(timer);};
 },[base,token,hasPage]);

 async function save(publish=false,revoke?:boolean){setBusy(true);setMessage('');try{const body:Record<string,unknown>={publish};if(revoke!==undefined)body.revoke=revoke;const r=await fetch(base,{method:'PATCH',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:'Check price and cubic feet');await load();setMessage(publish?'Estimate published to customer page.':'Saved.');}catch(e){setMessage((e as Error).message);}finally{setBusy(false);}}
 async function sync(){setBusy(true);setMessage('');try{const r=await fetch(base+'/sync-files',{method:'POST',headers:authHeaders(token)});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not queue files');setSyncInfo(d);setSyncError('');}catch(e){setMessage((e as Error).message);}finally{setBusy(false);}}
 if(!data)return null;
 return <section className="customer-page-controls" style={{background:'#fff',border:'1px solid #d8dde6',borderRadius:8,padding:18,marginBottom:18}}><h3 style={{margin:'0 0 12px',color:'#032d60'}}>Customer page</h3><div style={{display:'flex',gap:10,flexWrap:'wrap'}}><a href={data.url} target="_blank" rel="noopener noreferrer">Open customer page</a><button onClick={()=>void navigator.clipboard.writeText(data.url).then(()=>setMessage('Link copied.')).catch(()=>setMessage('Could not copy link.'))}>Copy link</button><button disabled={busy} onClick={()=>void save(false,!data.revoked)}>{data.revoked?'Restore access':'Revoke access'}</button></div>
 <button disabled={busy} onClick={()=>void save(true)}>Publish estimate from lead</button><p style={{fontSize:12,color:'#64748b'}}>{data.published?'Customer sees the last published estimate.':'Customer sees: We are preparing your estimate.'}</p>
 <p role="status">{syncInfo?syncInfo.active?`${syncInfo.synced} files synced; ${syncInfo.active} queued or uploading in the background. You can leave this page.`:syncInfo.failed?`${syncInfo.synced} files synced; ${syncInfo.failed} failed. Retry below.`:syncInfo.pending?`${syncInfo.pending} customer files awaiting LiveSwitch sync.`:syncInfo.synced?'All customer files synced to LiveSwitch.':'No customer files to sync.':`${data.pending_uploads} customer files awaiting LiveSwitch sync.`}</p>
 <button disabled={busy||!!syncInfo?.active||!(syncInfo?.pending??data.pending_uploads)} onClick={()=>void sync()}>{syncInfo?.active?'Syncing in background...':syncInfo?.failed?'Retry failed / pending files':'Sync customer files to LiveSwitch'}</button>
 {syncInfo?.files.filter(f=>f.status==='failed').map(f=><details key={f.id} style={{color:'#ba0517',marginTop:8,overflowWrap:'anywhere'}}><summary>{f.name} - View sync error</summary>{f.error}</details>)}
 {syncError&&<p role="alert">{syncError}</p>}
 {data.requests.map(r=><p key={r.id}>Video walkthrough: <strong>{r.status}</strong>{r.scheduled_at?` · ${new Date(r.scheduled_at).toLocaleString()}`:''}</p>)}{user?.role==='admin'&&<Link to="/walkthrough-requests">Manage live call requests</Link>}<p role="status">{message}</p></section>;
}
