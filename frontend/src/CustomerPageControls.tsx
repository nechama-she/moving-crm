import ReportFileGallery from "./ReportFileGallery";
import LiveSwitchImport from './LiveSwitchImport';
import type { EditableReportFile } from "./ReportFileList";
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { API_BASE } from './apiConfig';
import { authHeaders, useAuth } from './AuthContext';
// Share simultaneous reads across links/meeting sections; never retain old data.
const pendingPageReads = new Map<string, Promise<unknown>>();
function readPage(url:string, token:string | null) {
 const key=JSON.stringify([url,token]);
 const existing=pendingPageReads.get(key);
 if(existing)return existing;
 const task=fetch(url,{headers:authHeaders(token)}).then(async response=>response.ok?response.json():null).finally(()=>pendingPageReads.delete(key));
 pendingPageReads.set(key,task);
 return task;
}
type Page={url:string;rep_url?:string;revoked:boolean;requests:{id:string;status:string;scheduled_at:string;rep_name:string;availability:string}[]};
function ActionIcon({kind}:{kind:'copy'|'sms'|'revoke'|'restore'}){return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">{kind==='copy'?<><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/></>:kind==='sms'?<path d="M4 3h16v13H9l-5 5V3Z M8 7h8M8 11h6"/>:kind==='restore'?<><path d="M3 10a9 9 0 1 1 2 8M3 4v6h6"/><path d="m9 13 2 2 4-4"/></>:<><circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/></>}</svg>}
export default function CustomerPageControls({leadId,section='meeting',onFilesBusyChange,onSelectionChange,refreshRevision=0,disabled=false}:{leadId:string;section?:'links'|'files'|'meeting';onFilesBusyChange?:(busy:boolean)=>void;onSelectionChange?:(ids:string[])=>void;refreshRevision?:number;disabled?:boolean}){
 const {token}=useAuth();const [data,setData]=useState<Page>(),[files,setFiles]=useState<EditableReportFile[]>([]),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
 const [selectedIds,setSelectedIds]=useState<string[]>([]);
 const [importFiles,setImportFiles]=useState<EditableReportFile[]|null>(null);
 const [importIds,setImportIds]=useState<string[]>([]);
 const [importSearch,setImportSearch]=useState('');
 const currentFiles=useRef<EditableReportFile[]>([]);
 const currentSelection=useRef<string[]>([]);
 const mediaRevision=useRef(0);
 function selectFiles(ids:string[]){currentSelection.current=ids;setSelectedIds(ids);onSelectionChange?.(ids);}
 function updateFiles(incoming:EditableReportFile[],replace=false){
   mediaRevision.current+=1;
   const previous=currentFiles.current;
   const incomingById=new Map(incoming.map(file=>[file.id,file]));
   const added=[...incomingById.values()].filter(file=>!previous.some(row=>row.id===file.id));
   const next=[...previous.filter(file=>!replace||incomingById.has(file.id)).map(file=>incomingById.get(file.id)||file),...added];
   currentFiles.current=next;setFiles(next);
   selectFiles([...currentSelection.current.filter(id=>next.some(file=>file.id===id)),...added.map(file=>file.id)]);
 }
 function filesBusy(value:boolean){setBusy(value);onFilesBusyChange?.(value);}
 const base=`${API_BASE}/api/leads/${leadId}/customer-page`;
 useEffect(()=>{if(!token)return;let disposed=false;const controller=new AbortController();const revision=mediaRevision.current;async function load(){try{const result=await (section==='files'?fetch(`${base}/media`,{headers:authHeaders(token),cache:'no-store',signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error('Could not load media');return response.json();}):readPage(base,token)) as Page & {files:EditableReportFile[]} | null;if(disposed||!result)return;if(section==='files'){if(revision===mediaRevision.current)updateFiles(result.files,true);}else setData(result);}catch{if(!disposed&&revision===mediaRevision.current)setNotice('Could not load this section. Close and reopen this panel to retry.');}}void load();return()=>{disposed=true;controller.abort();};},[base,token,section,refreshRevision]);
 async function openFileImport(){
   filesBusy(true);setNotice('');
   try{const response=await fetch(`${base}/importable-files`,{headers:authHeaders(token)});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Could not load lead files');setImportFiles(result.files);setImportIds([]);setImportSearch('');}
   catch(error){setNotice((error as Error).message);}finally{filesBusy(false);}
 }
 async function importSelectedFiles(){
   filesBusy(true);setNotice('');
   try{const response=await fetch(`${base}/import-files`,{method:'POST',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify({file_ids:importIds})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Could not import files');updateFiles(result.files);setImportFiles(null);}
   catch(error){setNotice((error as Error).message);}finally{filesBusy(false);}
 }
 async function openRepPage(){
   if(busy || data?.revoked)return;
   const tab=window.open('about:blank','_blank');
   if(!tab){setNotice('Allow pop-ups to open the rep page.');return;}
   tab.opener=null;
   tab.document.title='Opening rep page';
   tab.document.body.textContent='Opening rep page...';
   setBusy(true);setNotice('');
   try{
     const response=await fetch(`${base}/rep-session`,{method:'POST',headers:authHeaders(token)});
     const result=await response.json();
     if(!response.ok)throw new Error(result.detail || 'Could not open the rep page.');
     const url=new URL(result.url,window.location.origin);
     if(url.origin!==window.location.origin)throw new Error('Open the CRM on the same website as the rep page to use automatic verification.');
     if(tab.closed)return;
     const key=`cm_session_${result.access_id}_rep`;
     tab.sessionStorage.setItem(key,result.session);
     tab.sessionStorage.setItem(key+':expiresAt',String(Date.parse(result.expires_at)));
     tab.location.replace(url.href);
   }catch(error){tab.close();setNotice((error as Error).message);}finally{setBusy(false);}
 }
 async function act(action:'sms'|'revoke'){setBusy(true);setNotice('');try{const r=await fetch(base+(action==='sms'?'/sms':''),{method:action==='sms'?'POST':'PATCH',headers:{...authHeaders(token),'Content-Type':'application/json'},body:action==='revoke'?JSON.stringify({revoke:!data?.revoked}):undefined});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not complete action');if(action==='revoke')setData(prev=>prev?{...prev,revoked:!prev.revoked}:prev);setNotice(action==='sms'?'SMS sent.':'Access updated.');}catch(e){setNotice((e as Error).message);}finally{setBusy(false);}}
 async function removeFiles(ids:string[]){
   if(!ids.length)return;
   const name=ids.length===1 ? files.find(file=>file.id===ids[0])?.name || 'this file' : `${ids.length} selected files`;
   if(!window.confirm(`Remove ${name} from this panel? The file stays attached to the lead.`))return;
   const removedIds:string[]=[];
   setBusy(true);
   onFilesBusyChange?.(true);
   try{
     for(const id of ids){
       const r=await fetch(`${base}/files/${encodeURIComponent(id)}`,{method:'DELETE',headers:authHeaders(token)});
       const result=await r.json();if(!r.ok)throw new Error(result.detail||'Could not delete file');
       removedIds.push(id);
      mediaRevision.current+=1;
      currentFiles.current=currentFiles.current.filter(file=>file.id!==id);
      setFiles(currentFiles.current);
     }
  }finally{if(removedIds.length)selectFiles(currentSelection.current.filter(value=>!removedIds.includes(value)));setBusy(false);onFilesBusyChange?.(false);}
 }
 async function downloadSelected(ids=selectedIds){setNotice('');try{for(const id of ids){const r=await fetch(`${base}/file-download/${encodeURIComponent(id)}`,{headers:authHeaders(token)});const d=await r.json();if(!r.ok || !d.url)throw new Error('Could not download this file.');const link=document.createElement('a');link.href=d.url;link.download=files.find(f=>f.id===id)?.name || 'file';document.body.appendChild(link);link.click();link.remove();}}catch(e){setNotice((e as Error).message);}}
 async function importChatFiles(){filesBusy(true);setNotice('Importing chat files...');let imported=0,failed=0;try{let next:{conversation:number;cursor:unknown}={conversation:0,cursor:null};const seen=new Set<string>();while(true){const cursor=JSON.stringify(next);if(seen.has(cursor))throw new Error('Chat import stopped because the server repeated the same page.');seen.add(cursor);const response=await fetch(`${base}/import-chat-files`,{method:'POST',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify(next)});const result=await response.json();if(!response.ok)throw new Error(result.detail || 'Could not import chat files');imported+=result.imported || 0;failed+=result.failed || 0;if(result.done)break;next={conversation:result.conversation,cursor:result.cursor};}const response=await fetch(`${base}/media`,{headers:authHeaders(token)});if(!response.ok)throw new Error('Could not reload imported chat files.');updateFiles((await response.json()).files,true);setNotice(`${imported} chat files imported.${failed ? ` ${failed} could not be saved; the source may be unavailable or the file too large.` : ''}`);}catch(e){setNotice((e as Error).message);}finally{filesBusy(false);}}
 if(section==='files') {
   const preview=async (id:string)=>{const response=await fetch(`${base}/file-preview/${encodeURIComponent(id)}`,{headers:authHeaders(token)});return response.ok?(await response.json()).url:null;};
   return <div className="crm-report-gallery">
     <LiveSwitchImport disabled={disabled||busy} onBusyChange={filesBusy} leadingAction={<><button type="button" className="slds-button" disabled={disabled||busy} onClick={()=>void importChatFiles()}>Import from chat</button><button type="button" className="slds-button" disabled={disabled||busy} onClick={()=>void openFileImport()}>Import from files</button></>} leadId={leadId} onImported={file=>updateFiles([file])}/>
     {importFiles && <section aria-label="Choose lead files" className="crm-file-import">
       <input type="search" className="slds-input" placeholder="Search lead files" aria-label="Search lead files" value={importSearch} onChange={event=>setImportSearch(event.target.value)}/>
       <div style={{maxHeight:320,overflow:'auto',margin:'10px 0'}}><ReportFileGallery title="Lead files" files={importFiles.filter(file=>file.name.toLowerCase().includes(importSearch.toLowerCase()))} selectedIds={importIds} onSelectionChange={setImportIds} loadPreview={preview} disabled={disabled||busy}/></div>
       <div className="ls-actions"><button type="button" className="slds-button" disabled={disabled||busy} onClick={()=>setImportFiles(null)}>Cancel</button><button type="button" className="slds-button" disabled={disabled||busy||!importIds.length} onClick={()=>void importSelectedFiles()}>Add selected ({importIds.length})</button></div>
     </section>}
     <ReportFileGallery title="Report media" selectedIds={selectedIds} onSelectionChange={selectFiles} onDownload={()=>void downloadSelected()} files={files} onRemoveSelected={removeFiles} disabled={disabled||busy} loadPreview={preview}/>
     {notice&&<p role="alert">{notice}</p>}
   </div>;
 }


 if(!data)return null;
 if(section==='links')return <><div className="ls-link"><div><strong>Customer link{data.revoked?' (revoked)':''}</strong><span title={data.url}>{data.url}</span></div><button className="slds-button" title="Copy customer link" aria-label="Copy customer link" onClick={()=>void navigator.clipboard.writeText(data.url).then(()=>setNotice('Link copied.')).catch(()=>setNotice('Could not copy link.'))}><ActionIcon kind="copy"/></button><button className="slds-button" title="Send SMS" aria-label="Send customer link by SMS" disabled={busy||data.revoked} onClick={()=>void act('sms')}><ActionIcon kind="sms"/></button><button className="slds-button" title={data.revoked?'Restore access':'Revoke access'} aria-label={data.revoked?'Restore customer access':'Revoke customer access'} disabled={busy} onClick={()=>void act('revoke')}><ActionIcon kind={data.revoked?"restore":"revoke"}/></button></div>{data.rep_url && <div className="ls-link"><div><strong>Rep link{data.revoked?' (revoked)':''}</strong><span title={data.rep_url}>{data.rep_url}</span><small>Open here without a code. Copied links require phone verification.</small></div><button className="slds-button" title="Copy rep link" aria-label="Copy rep link" onClick={()=>void navigator.clipboard.writeText(data.rep_url!).then(()=>setNotice('Rep link copied.')).catch(()=>setNotice('Could not copy link.'))}><ActionIcon kind="copy"/></button><button type="button" className="slds-button" disabled={busy||data.revoked} onClick={()=>void openRepPage()} title="Open rep page" aria-label="Open rep page in a new tab"><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M14 3h7v7M21 3L10 14M10 5H4v15h15v-6"/></svg></button></div>}{notice&&<p role="status">{notice}</p>}</>;
 const meeting=data.requests[0];return <section className="ls-card"><h3>Scheduled walkthrough</h3>{meeting?<p>{meeting.scheduled_at&&<>{new Date(meeting.scheduled_at).toLocaleString('en-US')} | </>}{meeting.rep_name&&<>{meeting.rep_name} | </>}<strong>{({scheduled:'Approved',requested:'Requested',completed:'Completed',cancelled:'Cancelled'} as Record<string,string>)[meeting.status]||meeting.status}</strong></p>:<p>No walkthrough requested</p>}<Link to={`/walkthrough-requests?lead_id=${encodeURIComponent(leadId)}`}>Meeting Calendar</Link></section>;
}
