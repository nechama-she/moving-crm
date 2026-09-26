import ReportFileGallery from "./ReportFileGallery";
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
export default function CustomerPageControls({leadId,section='meeting',onFilesBusyChange,onSelectionChange}:{leadId:string;section?:'links'|'files'|'meeting';onFilesBusyChange?:(busy:boolean)=>void;onSelectionChange?:(ids:string[])=>void}){
 const {token}=useAuth();const [data,setData]=useState<Page>(),[files,setFiles]=useState<EditableReportFile[]>([]),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
 const [selectedIds,setSelectedIds]=useState<string[]>([]);
 const [reportFileIds,setReportFileIds]=useState<string[]>([]);
 const initialized=useRef(false);
 const [videoNotice,setVideoNotice]=useState('');
 useEffect(()=>{
   if(section!=='files' || !token)return;
   let disposed=false;
   let timer:ReturnType<typeof setTimeout> | undefined;
   const endpoint=`${API_BASE}/api/leads/${leadId}/customer-page`;
   async function check(start=false){
     try{
       if(start){
         setVideoNotice('Checking LiveSwitch videos...');
         const response=await fetch(`${endpoint}/import-recordings`,{method:'POST',headers:authHeaders(token)});
         const result=await response.json();
         if(!response.ok)throw new Error(result.detail || 'Could not check LiveSwitch videos.');
       }
       const response=await fetch(`${endpoint}/sync-status`,{headers:authHeaders(token),cache:'no-store'});
       if(!response.ok)throw new Error('Could not check video import status.');
       const result=await response.json();
       if(disposed)return;
       setFiles(result.editable_files || []);
       const state=result.recording_import || {};
       if(state.status==='queued' || state.status==='running'){
         setVideoNotice('Saving LiveSwitch videos to CRM...');
         timer=setTimeout(()=>void check(),3000);
       }else{
         setVideoNotice(state.error || (state.imported ? `${state.imported} videos saved to CRM.` : state.pending ? 'Some LiveSwitch videos are still processing.' : ''));
       }
     }catch(error){if(!disposed)setVideoNotice((error as Error).message);}
   }
   void check(true);
   return()=>{disposed=true;if(timer)clearTimeout(timer);};
 },[leadId,token,section]);
 function selectFiles(ids:string[]){setSelectedIds(ids);onSelectionChange?.(ids);}
 const base=`${API_BASE}/api/leads/${leadId}/customer-page`;
 useEffect(()=>{if(!token)return;let disposed=false;async function load(){try{const d=await readPage(base+(section==='files'?'/sync-status':''),token) as Page & {editable_files?:EditableReportFile[];files:EditableReportFile[];report_file_ids?:string[]} | null;if(disposed||!d)return;if(section==='files'){const available=d.editable_files || d.files;setFiles(available);setReportFileIds(d.report_file_ids || []);if(!initialized.current){initialized.current=true;selectFiles((d.report_file_ids || []).filter(id=>available.some(file=>file.id===id)));}}else setData(d);}catch{ /* A later explicit opening can retry. */ }}void load();return()=>{disposed=true;};},[base,token,section]);
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
 async function removeFile(id:string){onFilesBusyChange?.(true);try{const r=await fetch(`${base}/files/${encodeURIComponent(id)}`,{method:'DELETE',headers:authHeaders(token)});const result=await r.json();if(!r.ok)throw new Error(result.detail||'Could not delete file');setFiles(current=>current.filter(file=>file.id!==id));}finally{onFilesBusyChange?.(false);}}
 async function downloadSelected(ids=selectedIds){setNotice('');try{for(const id of ids){const r=await fetch(`${base}/file-download/${encodeURIComponent(id)}`,{headers:authHeaders(token)});const d=await r.json();if(!r.ok || !d.url)throw new Error('Could not download this file.');const link=document.createElement('a');link.href=d.url;link.download=files.find(f=>f.id===id)?.name || 'file';document.body.appendChild(link);link.click();link.remove();}}catch(e){setNotice((e as Error).message);}}
 async function importChatFiles(){setBusy(true);onFilesBusyChange?.(true);setNotice('Importing chat files...');let imported=0,failed=0;try{let next:{conversation:number;cursor:unknown}={conversation:0,cursor:null};while(true){const response=await fetch(`${base}/import-chat-files`,{method:'POST',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify(next)});const result=await response.json();if(!response.ok)throw new Error(result.detail || 'Could not import chat files');imported+=result.imported || 0;failed+=result.failed || 0;setNotice(`Importing chat files: ${imported} saved...`);if(result.done)break;next={conversation:result.conversation,cursor:result.cursor};}const response=await fetch(`${base}/sync-status`,{headers:authHeaders(token)});if(response.ok){const result=await response.json();setFiles(result.editable_files || []);}setNotice(`${imported} chat files imported.${failed ? ` ${failed} could not be saved; the source may be unavailable or the file too large.` : ''}`);}catch(e){setNotice((e as Error).message);}finally{setBusy(false);onFilesBusyChange?.(false);}}
 if(section==='files') {
   const current=files.filter(file=>reportFileIds.includes(file.id));
   const available=files.filter(file=>!reportFileIds.includes(file.id));
   const preview=async (id:string)=>{const response=await fetch(`${base}/file-preview/${encodeURIComponent(id)}`,{headers:authHeaders(token)});return response.ok?(await response.json()).url:null;};
   const group=(rows:EditableReportFile[],title:string)=> <ReportFileGallery title={title} selectedIds={selectedIds.filter(id=>rows.some(file=>file.id===id))} onSelectionChange={ids=>selectFiles([...selectedIds.filter(id=>!rows.some(file=>file.id===id)),...ids])} onDownload={()=>void downloadSelected(selectedIds.filter(id=>rows.some(file=>file.id===id)))} files={rows} onRemove={removeFile} disabled={busy} loadPreview={preview}/>;
   return <div className="crm-report-gallery">
     <div className="crm-gallery-current"><h4>Files in the current report</h4><p>Already included. Keep selected to include them in your next report.</p>{current.length?group(current,'Current report files'):<p>No files in the current report yet.</p>}</div>
     <div className="crm-gallery-available"><h4>Available files to add</h4><button type="button" className="slds-button" disabled={busy} onClick={()=>void importChatFiles()}>Import chat files</button><p>Not in the current report. Select the files you want to send to LiveSwitch.</p>{available.length?group(available,'Available files'):<p>No additional files available.</p>}</div>
     <p role="status"><strong>{selectedIds.length} files selected for the next report</strong></p>
     {notice&&<p role="alert">{notice}</p>}
     {videoNotice&&<p role="status">{videoNotice}</p>}
   </div>;
 }


 if(!data)return null;
 if(section==='links')return <><div className="ls-link"><div><strong>Customer link{data.revoked?' (revoked)':''}</strong><span title={data.url}>{data.url}</span></div><button className="slds-button" title="Copy customer link" aria-label="Copy customer link" onClick={()=>void navigator.clipboard.writeText(data.url).then(()=>setNotice('Link copied.')).catch(()=>setNotice('Could not copy link.'))}><ActionIcon kind="copy"/></button><button className="slds-button" title="Send SMS" aria-label="Send customer link by SMS" disabled={busy||data.revoked} onClick={()=>void act('sms')}><ActionIcon kind="sms"/></button><button className="slds-button" title={data.revoked?'Restore access':'Revoke access'} aria-label={data.revoked?'Restore customer access':'Revoke customer access'} disabled={busy} onClick={()=>void act('revoke')}><ActionIcon kind={data.revoked?"restore":"revoke"}/></button></div>{data.rep_url && <div className="ls-link"><div><strong>Rep link{data.revoked?' (revoked)':''}</strong><span title={data.rep_url}>{data.rep_url}</span><small>Open here without a code. Copied links require phone verification.</small></div><button className="slds-button" title="Copy rep link" aria-label="Copy rep link" onClick={()=>void navigator.clipboard.writeText(data.rep_url!).then(()=>setNotice('Rep link copied.')).catch(()=>setNotice('Could not copy link.'))}><ActionIcon kind="copy"/></button><button type="button" className="slds-button" disabled={busy||data.revoked} onClick={()=>void openRepPage()} title="Open rep page" aria-label="Open rep page in a new tab"><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M14 3h7v7M21 3L10 14M10 5H4v15h15v-6"/></svg></button></div>}{notice&&<p role="status">{notice}</p>}</>;
 const meeting=data.requests[0];return <section className="ls-card"><h3>Scheduled walkthrough</h3>{meeting?<p>{meeting.scheduled_at&&<>{new Date(meeting.scheduled_at).toLocaleString('en-US')} | </>}{meeting.rep_name&&<>{meeting.rep_name} | </>}<strong>{({scheduled:'Approved',requested:'Requested',completed:'Completed',cancelled:'Cancelled'} as Record<string,string>)[meeting.status]||meeting.status}</strong></p>:<p>No walkthrough requested</p>}<Link to={`/walkthrough-requests?lead_id=${encodeURIComponent(leadId)}`}>Meeting Calendar</Link></section>;
}
