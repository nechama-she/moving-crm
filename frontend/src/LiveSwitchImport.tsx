import { useEffect, useRef, useState } from 'react';
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
      ? `LiveSwitch HTTP ${detail.status}\n${detail.body}`
      : typeof detail === 'string' ? detail : `HTTP ${response.status}\n${body}`);
  }
  return result;
}

export default function LiveSwitchImport({leadId,onImported}:{leadId:string;onImported:(file:EditableReportFile)=>void}) {
  const {token}=useAuth();
  const [files,setFiles]=useState<RemoteFile[] | null>(null);
  const [active,setActive]=useState('');
  const [error,setError]=useState('');
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
  async function importFile(file:RemoteFile,signal:AbortSignal) {
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
  return <div>
    <button type="button" className="slds-button" disabled={!!active} onClick={()=>void run('list',async signal=>{
      const result=await post(`${base}/liveswitch-files`,signal);setFiles(result.files);
    })}>{active==='list'?'Checking LiveSwitch...':'Import from LiveSwitch'}</button>
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
    {error && <pre role="alert" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:240,overflow:'auto'}}>{error}</pre>}
  </div>;
}
