import MeetingTimePicker from "./MeetingTimePicker";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import "./CustomerMovePage.css";

type Details = { name:string; phone:string; email:string; move_date:string; pickup:string; delivery:string; company:string; stops:{address:string;type:string|null}[]; estimate:{price:string;cuft:string}|null; walkthrough:{status:string;availability:string;scheduled_at:string|null;timezone:string}|null; participant_url:string; files:{id:string;name:string;size:number}[] };
type Pending = {id:string;file:File;status:string;progress:number;preview?:string;error?:string};
export default function CustomerMovePage() {
  const {accessId}=useParams();
  const [key]=useState(()=>new URLSearchParams(window.location.hash.slice(1)).get('key')||'');
  const [session,setSession]=useState(''),[options,setOptions]=useState<{channel:string;destination:string}[]>([]),[channel,setChannel]=useState('');
  const [code,setCode]=useState(''),[sent,setSent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [data,setData]=useState<Details>(),[files,setFiles]=useState<Pending[]>([]),[availability,setAvailability]=useState(''),[requested,setRequested]=useState(false),[rescheduling,setRescheduling]=useState(false);
  const [resendAt,setResendAt]=useState(0),[clock,setClock]=useState(Date.now());
  const previews=useRef<string[]>([]);
  const base=`${API_BASE}/api/public-moves/${accessId}`;
  const headers={'x-public-link':key,'x-public-session':session};
  async function call(path:string, body?:unknown) {
    const response=await fetch(base+path,{method:body===undefined?'GET':'POST',headers:{...headers,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
    const result=await response.json();
    if(!response.ok){if((response.status===401||response.status===404)){setSession('');setData(undefined);setSent(false);}throw new Error(typeof result.detail==='string'?result.detail:'Please check your details and try again.');}
    return result;
  }
  useEffect(()=>{
    document.title='Your move';
    const referrer=document.createElement('meta');referrer.name='referrer';referrer.content='no-referrer';document.head.appendChild(referrer);
    const urls=previews.current;
    return ()=>{referrer.remove();urls.forEach(URL.revokeObjectURL);};
  },[]);
  useEffect(()=>{const abort=new AbortController();fetch(base+'/verify-options',{headers:{'x-public-link':key},cache:'no-store',signal:abort.signal}).then(async r=>{const value=await r.json();if(!r.ok)throw new Error(value.detail||'This link is unavailable.');setOptions(value.options);setChannel(value.options[0]?.channel||'');}).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return ()=>abort.abort();},[base,key]);
  useEffect(()=>{if(!session)return;let active=true;const load=()=>fetch(base+'/details',{headers:{'x-public-link':key,'x-public-session':session},cache:'no-store'}).then(async r=>{if((r.status===401||r.status===404)){if(active){setSession('');setData(undefined);}return;}if(!r.ok)throw new Error('Your move could not be refreshed.');const next=await r.json();if(active)setData(next);}).catch(e=>{if(active)setError(e.message);});void load();const interval=setInterval(()=>void load(),15000);return ()=>{active=false;clearInterval(interval);};},[base,key,session]);
  useEffect(()=>{if(!sent)return;const t=setInterval(()=>setClock(Date.now()),1000);return ()=>clearInterval(t);},[sent]);
  async function send(){setBusy(true);setError('');try{await call('/send-code',{channel});setSent(true);setResendAt(Date.now()+60000);setClock(Date.now());}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function verify(){setBusy(true);setError('');try{const value=await call('/verify',{code});setSession(value.session);setCode('');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function choose(list:FileList|null){
    if(!list?.length)return;
    try {
      // Snapshot the browser FileList before the input is reset or React runs the updater.
      const added:Pending[]=Array.from(list).map(file=>{
        const preview=file.type.startsWith('image/')?URL.createObjectURL(file):undefined;
        if(preview)previews.current.push(preview);
        return {id:crypto.randomUUID(),file,preview,progress:0,status:file.size>100*1024*1024?'Too large (100 MB maximum)':file.size===0?'Empty file':'Ready'};
      });
      setFiles(prev=>[...prev,...added]);setError('');
    } catch {setError('Could not select these files. Please choose them again.');}
  }
  async function upload(){
    setBusy(true);setError('');
    try{for(const item of files.filter(f=>f.status==='Ready'||f.status==='Try again')){
      const update=(status:string,progress:number)=>setFiles(prev=>prev.map(f=>f.id===item.id?{...f,status,progress,error:undefined}:f));
      update('Uploading',0);
      try{
        const mime=item.file.type || 'application/octet-stream';
        const prepared=await call('/prepare-upload',{request_id:item.id,name:item.file.name,size:item.file.size,content_type:mime});
        if(!prepared.completed){
          await new Promise<void>((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST',prepared.upload.url);xhr.timeout=300000;xhr.upload.onprogress=e=>{if(e.lengthComputable)update('Uploading',Math.round(e.loaded/e.total*90));};xhr.onload=()=>xhr.status>=200&&xhr.status<300?resolve():reject(new Error('Upload interrupted. Please try again.'));xhr.onerror=xhr.ontimeout=()=>reject(new Error('Upload interrupted. Please try again.'));const form=new FormData();Object.entries(prepared.upload.fields as Record<string,string>).forEach(([k,v])=>form.append(k,v));form.append('file',item.file);xhr.send(form);});
          update('Finishing upload',95);await call('/finish-upload',{request_id:item.id});
        }
        update('Uploaded',100);
      }catch(e){const message=(e as Error).message;setFiles(prev=>prev.map(f=>f.id===item.id?{...f,status:'Try again',progress:0,error:message}:f));}
    }}finally{setBusy(false);}
  }
  async function walkthrough(){setBusy(true);setError('');try{const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;const result=await call(rescheduling?'/reschedule':'/walkthrough',{availability,timezone});setRequested(true);setRescheduling(false);setData(prev=>prev?{...prev,walkthrough:result,participant_url:''}:prev);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  const wait=Math.max(0,Math.ceil((resendAt-clock)/1000));

  return (
    <div className="customer-move">
      <div className="cm-wrap">
        {!session ? (
          <section className="cm-verify">
            <div className="cm-eyebrow">WELCOME</div>
            <h1>Let's get your<br/>move underway.</h1>
            <p>First, verify it's you. We'll send a code to the phone or email you provided.</p>
            {error && <div role="alert" className="cm-error">{error}</div>}
            <fieldset>
              <legend>Where should we send your code?</legend>
              {options.map(option => (
                <label key={option.channel}>
                  <input type="radio" name="channel" value={option.channel} checked={channel===option.channel} disabled={busy} onChange={()=>{setChannel(option.channel);setSent(false);}}/>
                  {option.channel==='sms' ? 'Text message' : 'Email'} <span>{option.destination}</span>
                </label>
              ))}
            </fieldset>
            {!sent ? (
              <button className="cm-primary" disabled={busy||!channel||!key} onClick={()=>void send()}>{busy?'Sending...':'Send verification code'}</button>
            ) : (
              <form onSubmit={e=>{e.preventDefault();void verify();}}>
                <label className="cm-code">Enter your 6-digit code<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,''))}/></label>
                <button className="cm-primary" disabled={busy||code.length!==6}>{busy?'Checking...':'View my move'}</button>
                <button type="button" className="cm-text-button" disabled={busy||wait>0} onClick={()=>void send()}>{wait?`Send again in ${wait}s`:'Send a new code'}</button>
              </form>
            )}
            <small className="cm-private">Your information is private. No account or password needed.</small>
          </section>
        ) : !data ? (
          <p role="status">Opening your move...</p>
        ) : (
          <>
            <section className="cm-intro"><div><div className="cm-eyebrow">LET'S MAKE YOUR NEXT MOVE EASIER</div><h1>Hi {data.name.split(' ')[0]},<br/>you're in the right place.</h1><p>Share a little more about your home.<br/>We'll take care of the estimate.</p></div><div className="cm-estimate"><span>{data.estimate?'Your moving estimate':'Your estimate'}</span><strong>{data.estimate?new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(data.estimate.price)):'We\'re working on it.'}</strong><p>{data.estimate?`${Number(data.estimate.cuft).toLocaleString()} cubic feet estimated`:'Add photos or request a video walkthrough to help us prepare your estimate.'}</p></div></section>
            {error&&<div className="cm-error" role="alert">{error}</div>}
            <div className="cm-columns"><section className="cm-card cm-route"><div className="cm-eyebrow">YOUR MOVE</div><h2>{data.move_date?new Date(data.move_date.slice(0,10)+'T12:00:00').toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'}):'Date to be confirmed'}</h2><ol>{[{address:data.pickup,type:'pickup'},...data.stops,{address:data.delivery,type:'delivery'}].map((stop,i)=><li key={i}><small>{stop.type==='pickup'?'Pickup':stop.type==='delivery'?'Delivery':'Stop'}</small><strong>{stop.address}</strong></li>)}</ol><div className="cm-contact"><strong>{data.name}</strong><span>{data.phone}</span><span>{data.email}</span></div></section>
            <section className="cm-card cm-upload"><div className="cm-eyebrow">SHOW US WHAT'S MOVING</div><h2>Add photos, documents<br/>or videos.</h2><p>A few photos of each room help us understand your move. Include any large or delicate items.</p><label className="cm-drop"><span aria-hidden="true">^</span><strong>Choose files</strong><small>Photos, documents or videos · Up to 100 MB each</small><input type="file" multiple disabled={busy} onChange={e=>{choose(e.target.files);e.target.value='';}}/></label>
            {files.length>0 && <p role="status">{files.filter(f=>f.status==='Uploaded').length} of {files.length} files uploaded</p>}
            <div className="cm-file-list">
              {files.map(item => (
                <article key={item.id}>
                  {item.preview && <img src={item.preview} alt="" />}
                  <div>
                    <strong>{item.file.name}</strong>
                    <small role="status">{item.status}{item.status==='Uploading'?` ${item.progress}%`:''}</small>
                    {item.error && <small role="alert" style={{color:'#974327'}}>{item.error}</small>}
                    <progress max={100} value={item.progress} aria-label={`${item.file.name} upload progress`} />
                  </div>
                  {item.status!=='Uploaded' && !busy && <button aria-label={`Remove ${item.file.name}`} onClick={()=>setFiles(prev=>prev.filter(f=>f.id!==item.id))}>x</button>}
                </article>
              ))}
            </div>
            <button className="cm-primary" disabled={busy||!files.some(f=>['Ready','Try again'].includes(f.status))} onClick={()=>void upload()}>{busy?'Please wait...':'Upload files'}</button>
            {data.files.length>0&&<details><summary>{data.files.length} saved files</summary>{data.files.map(file=><p key={file.id}>{file.name}</p>)}</details>}</section></div>
            <section className="cm-walkthrough"><div><div className="cm-eyebrow">PREFER TO SHOW US AROUND?</div><h2>Let's take a live<br/>video walkthrough.</h2><p>Walk us through your home from your phone.<br/>Our team will help you plan what comes next.</p></div><div>{data.walkthrough&&!rescheduling?<><span className="cm-meeting-status">{({requested:'Requested',scheduled:'Approved',completed:'Completed',cancelled:'Cancelled'} as Record<string,string>)[data.walkthrough.status]||data.walkthrough.status}</span><h3>{data.walkthrough.status==='scheduled'?'Your video walkthrough':'Video walkthrough request'}</h3><p className="cm-meeting-time">{meetingTime(data.walkthrough)}</p>{data.walkthrough.status==='scheduled'&&data.participant_url&&<a className="cm-primary" href={data.participant_url} target="_blank" rel="noopener noreferrer">Join video walkthrough</a>}{['requested','scheduled'].includes(data.walkthrough.status)&&<button type="button" className="cm-reschedule" onClick={()=>{setAvailability('');setRescheduling(true);}}>Reschedule</button>}</>:<form onSubmit={e=>{e.preventDefault();void walkthrough();}}><MeetingTimePicker onChange={setAvailability} availabilityUrl={base+"/availability"} linkKey={key} session={session} moveDate={data.move_date || null} /><button className="cm-primary" disabled={busy||!availability.trim()}>{rescheduling?'Request new time':'Request a video walkthrough'}</button>{rescheduling&&<button type="button" className="cm-reschedule" disabled={busy} onClick={()=>setRescheduling(false)}>Cancel</button>}{requested&&<p role="status">Request saved.</p>}</form>}</div></section>
            <footer className="cm-footer">Your move. Your pace. We're here to help.</footer>
          </>
        )}
      </div>
    </div>
  );
}

function meetingTime(meeting:NonNullable<Details['walkthrough']>){
  if(meeting.scheduled_at)return new Date(meeting.scheduled_at).toLocaleString(undefined,{weekday:'long',month:'long',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
  const dates=meeting.availability.match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z/g)||[];
  if(dates[0])return `${new Date(dates[0]).toLocaleString(undefined,{month:'long',day:'numeric',hour:'numeric',minute:'2-digit'})}${dates[1]?' - '+new Date(dates[1]).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit',timeZoneName:'short'}):''}`;
  return meeting.availability.split(';')[0];
}
