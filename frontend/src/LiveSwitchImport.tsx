import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { API_BASE } from './apiConfig';
import { authHeaders, useAuth } from './AuthContext';
import type { EditableReportFile } from './ReportFileList';

type RemoteFile = {id:string; request_id:string; name:string; url:string; status:string};

async function readResult(response: Response) {
  const body = await response.text();
  let result;
  try { result = JSON.parse(body); } catch { result = null; }
  if (!response.ok) {
    const detail = result?.detail;
    throw new Error(detail?.provider === 'LiveSwitch'
      ? `LiveSwitch HTTP ${detail.status}\n${detail.body}${detail.diagnostics ? '\n\nCredential diagnostics\n'+JSON.stringify(detail.diagnostics,null,2) : ''}`
      : typeof detail === 'string' ? detail : `HTTP ${response.status}\n${body}`);
  }
  return result;
}

export default function LiveSwitchImport({leadId,onImported,leadingAction}:{leadId:string;onImported:(file:EditableReportFile)=>void;leadingAction?:ReactNode}) {
  const {token}=useAuth();
  const [files,setFiles]=useState<RemoteFile[] | null>(null);
  const [active,setActive]=useState('');
  const [error,setError]=useState('');
  const [supportTrace,setSupportTrace]=useState('');
  const operation=useRef<AbortController | null>(null);
  useEffect(()=>()=>operation.current?.abort(),[]);
  const base=`${API_BASE}/api/leads/${leadId}/customer-page`;
  const uploads=`${API_BASE}/api/liveswitch/leads/${leadId}`;
  async function post(url:string,signal:AbortSignal,body?:unknown) {
    return readResult(await fetch(url,{method:'POST',headers:{...authHeaders(token),'Content-Type':'application/json'},
      body:body===undefined?undefined:JSON.stringify(body),signal}));
  }
  async function run(id:string,action:(signal:AbortSignal)=>Promise<void>) {
    if(operation.current)return;
    const controller=new AbortController();operation.current=controller;
    setActive(id);setError('');
    try { await action(controller.signal); }
    catch(error) { if(!controller.signal.aborted)setError((error as Error).message); }
    finally { operation.current=null;if(!controller.signal.aborted)setActive(''); }
  }
  async function freshFiles(signal:AbortSignal):Promise<RemoteFile[]> {
    const popup=window.open('about:blank','_blank','popup,width=650,height=780');
    if(!popup)throw new Error('Allow pop-ups to sign in to LiveSwitch.');
    popup.document.body.textContent='Opening a fresh LiveSwitch login...';
    setSupportTrace('');
    try {
      const result=await post(`${base}/liveswitch-import-login`,signal);
      return await new Promise<RemoteFile[]>((resolve,reject)=>{
        const expectedOrigin=new URL(API_BASE || window.location.origin,window.location.origin).origin;
        const cleanup=()=>{window.removeEventListener('message',receive);signal.removeEventListener('abort',abort);clearInterval(timer);};
        const abort=()=>{cleanup();popup.close();reject(new DOMException('Import cancelled','AbortError'));};
        const receive=(event:MessageEvent)=>{
          if(event.source!==popup || event.origin!==expectedOrigin || event.data?.type!=='liveswitch-import-result')return;
          cleanup();popup.close();setSupportTrace(JSON.stringify(event.data.trace,null,2));
          if(event.data.error)reject(new Error(typeof event.data.error==='string'?event.data.error:JSON.stringify(event.data.error,null,2)));
          else resolve(event.data.files);
        };
        const started=Date.now();
        const timer=setInterval(()=>{if(popup.closed || Date.now()-started>15*60*1000){cleanup();popup.close();reject(new Error('LiveSwitch login was closed or timed out.'));}},500);
        window.addEventListener('message',receive);signal.addEventListener('abort',abort,{once:true});
        if(signal.aborted){abort();return;}
        popup.location.replace(result.authorization_url);
      });
    }catch(error){popup.close();throw error;}
  }
  async function importFile(file:RemoteFile,signal:AbortSignal) {
    const refreshed=(await freshFiles(signal)).find(row=>row.id===file.id);
    if(!refreshed)throw new Error('This recording is no longer missing or available.');
    file=refreshed;
    const url=new URL(file.url);
    if(url.protocol!=='https:')throw new Error('LiveSwitch did not provide an HTTPS video download URL.');
    const response=await fetch(url,{signal,credentials:'omit',referrerPolicy:'no-referrer'});
    if(!response.ok)throw new Error(`LiveSwitch download HTTP ${response.status}\n${await response.text()}`);
    const content=await response.blob();
    if(!content.size || !content.type.startsWith('video/'))throw new Error(`LiveSwitch returned ${content.type || 'an unknown file type'}, not a downloadable video.`);
    const extension=content.type==='video/webm'?'.webm':content.type==='video/quicktime'?'.mov':'.mp4';
    const metadata={request_id:file.request_id,name:file.name.replace(/\.mp4$/,extension),size:content.size,content_type:content.type};
    const prepared=await post(`${uploads}/prepare-upload`,signal,metadata);
    if(!prepared.completed) {
      const form=new FormData();
      for(const [key,value] of Object.entries(prepared.upload.fields))form.append(key,String(value));
      form.append('file',content,metadata.name);
      const uploaded=await fetch(prepared.upload.url,{method:'POST',body:form,signal});
      if(!uploaded.ok)throw new Error(`CRM storage HTTP ${uploaded.status}\n${await uploaded.text()}`);
      await post(`${uploads}/finish-upload`,signal,metadata);
    }
    onImported({id:file.request_id,name:metadata.name,size:content.size,content_type:content.type});
    setFiles(current=>current?.filter(row=>row.id!==file.id) ?? []);
  }
  let errorMessage=error.split('\n')[0];
  let technicalDetails=error;
  if(error.includes('\n')) {
    try {
      const body=JSON.parse(error.slice(error.indexOf('\n')+1).split('\n\nCredential diagnostics\n')[0]);
      const descriptions=body.errors?.map((item:{description?:string})=>item.description).filter(Boolean);
      if(descriptions?.length)errorMessage=descriptions.join(' ');
      technicalDetails=error.split('\n')[0]+'\n'+JSON.stringify(body,null,2)
        +(error.includes('\n\nCredential diagnostics\n') ? '\n\nCredential diagnostics\n'+error.split('\n\nCredential diagnostics\n')[1] : '');
    }catch { /* Non-JSON provider errors remain available unchanged. */ }
  }
  return <div>
    <div style={{display:'flex',gap:8,flexWrap:'wrap',alignItems:'center',margin:'8px 0'}}>
    {leadingAction}
    <button type="button" className="slds-button" disabled={!!active} onClick={()=>void run('list',async signal=>{
      setFiles(await freshFiles(signal));
    })}>{active==='list'?'Checking LiveSwitch...':'Import from LiveSwitch'}</button>
    </div>
    {files && <div aria-label="Missing LiveSwitch files">
      {!files.length && <p role="status">No missing LiveSwitch videos.</p>}
      {files.map(file=><div key={file.id} style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap',marginTop:8}}>
        <span style={{overflowWrap:'anywhere',minWidth:0,flex:'1 1 180px'}}>{file.name}</span>
        <button type="button" className="slds-button" disabled={!!active || file.status!=='Completed' || !file.url}
          onClick={()=>void run(file.id,signal=>importFile(file,signal))}>
          {active===file.id?'Importing...':file.status!=='Completed'?file.status:!file.url?'Download unavailable':'Import'}
        </button>
      </div>)}
    </div>}
    {error && <div style={{borderLeft:'3px solid #b42318',padding:'8px 12px',margin:'12px 0',background:'#fff5f4'}}>
      <p role="alert" style={{margin:'0 0 8px',overflowWrap:'anywhere',color:'#8a2018'}}>{errorMessage}</p>
      <details><summary style={{cursor:'pointer'}}>Technical details</summary>
        <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:240,overflow:'auto',fontSize:12}}>{technicalDetails}</pre>
      </details>
    </div>}
    {supportTrace && <details><summary>Support trace (credentials redacted)</summary>
      <button type="button" className="slds-button" onClick={()=>void navigator.clipboard.writeText(supportTrace).catch(()=>setError('Could not copy the trace.'))}>Copy support trace</button>
      <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:320,overflow:'auto'}}>{supportTrace}</pre>
    </details>}
  </div>;
}
