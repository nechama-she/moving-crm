import CustomerPackingOptions, { type PackingPackage, type PackingSelection } from "./CustomerPackingOptions";
import MeetingTimePicker from "./MeetingTimePicker";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import "./CustomerMovePage.css";

type Details = {
  packing_package: PackingPackage | null;
  packing_items: { id: string; label: string; price: number; selected: boolean; selected_service: string | null; services: { kind: string; price: number }[] }[];
  packing_saved: boolean;
  name: string;
  phone: string;
  email: string;
  move_date: string;
  pickup: string;
  delivery: string;
  company: string;
  company_details?: {
    name: string;
    phone: string;
    office_address: string;
  };
  stops: { address: string; type: string | null }[];
  estimate: {
    price: string;
    cuft: string;
    charges?: { name: string; description: string; total: number }[];
  } | null;
  spark?: { id: string; status: string; shareUrl?: string; cuft?: number } | null;
  walkthrough: { status: string; availability: string; scheduled_at: string | null; timezone: string } | null;
  participant_url: string;
  files: { id: string; name: string; size: number }[];
};
type Pending = {id:string;file:File;status:string;progress:number;preview?:string;error?:string};
export default function CustomerMovePage() {
  const {accessId}=useParams();
  const sessionKey = `cm_session_${accessId}`;
  const [key]=useState(()=>new URLSearchParams(window.location.hash.slice(1)).get('key')||'');
  const [session,setSession]=useState(()=>sessionStorage.getItem(sessionKey)||'');
  const [options,setOptions]=useState<{channel:string;destination:string}[]>([]),[channel,setChannel]=useState('');
  const [code,setCode]=useState(''),[sent,setSent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [data,setData]=useState<Details>(),[files,setFiles]=useState<Pending[]>([]),[availability,setAvailability]=useState(''),[requested,setRequested]=useState(false),[rescheduling,setRescheduling]=useState(false);
  const [editingMove,setEditingMove]=useState(false);
  const [moveDraft,setMoveDraft]=useState({name:'',phone:'',email:'',move_date:'',pickup:'',delivery:''});
  const [reportState,setReportState]=useState<'idle'|'running'|'done'>('idle');
  const [reportNotice,setReportNotice]=useState('');
  const [hasNewUploads, setHasNewUploads] = useState(false);
  const [resendAt,setResendAt]=useState(0),[clock,setClock]=useState(Date.now());
  const [showQuestions, setShowQuestions] = useState(false);
  const [packingSelection, setPackingSelection] = useState<Record<string, string>>({});
  const [packingStep, setPackingStep] = useState<'bulky' | 'package'>('bulky');
  const [packageSelection, setPackageSelection] = useState<PackingSelection>({ mode: 'none', unpacking: false, item_ids: [] });
  const [packingSaving, setPackingSaving] = useState(false);
  const [packingError, setPackingError] = useState('');
  const money = (amount: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
  async function savePacking() {
    if (Object.values(packingSelection).some(value => !value)) {
      setPackingError('Choose packing or crating for each checked item.');
      return;
    }
    setPackingSaving(true);
    setPackingError('');
    try {
      setData(await call('/packing', { selections: packingSelection, ...(data?.packing_package ? { package: packageSelection } : {}) }));
      setShowQuestions(false);
    } catch (err) {
      setPackingError((err as Error).message);
    } finally {
      setPackingSaving(false);
    }
  }
  const [themeColor, setThemeColor] = useState<string>('#214c3e');
  const previews=useRef<string[]>([]);
  const base=`${API_BASE}/api/public-moves/${accessId}`;
  const headers={'x-public-link':key,'x-public-session':session};

  async function call(path:string, body?:unknown, method?:string) {
    const httpMethod = method || (body===undefined ? 'GET' : 'POST');
    const response=await fetch(base+path,{method:httpMethod,headers:{...headers,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
    const result=await response.json();
    if(!response.ok){
      if((response.status===401||response.status===404)){
        sessionStorage.removeItem(sessionKey);
        setSession('');
        setData(undefined);
        setSent(false);
      }
      throw new Error(typeof result.detail==='string'?result.detail:'Please check your details and try again.');
    }
    return result;
  }
  useEffect(()=>{
    document.title='Your move';
    const referrer=document.createElement('meta');referrer.name='referrer';referrer.content='no-referrer';document.head.appendChild(referrer);
    const urls=previews.current;
    return ()=>{referrer.remove();urls.forEach(URL.revokeObjectURL);};
  },[]);
  useEffect(()=>{const abort=new AbortController();fetch(base+'/verify-options',{headers:{'x-public-link':key},cache:'no-store',signal:abort.signal}).then(async r=>{const value=await r.json();if(!r.ok)throw new Error(value.detail||'This link is unavailable.');setOptions(value.options);setChannel(value.options[0]?.channel||'');if(value.company?.color)setThemeColor(value.company.color);}).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return ()=>abort.abort();},[base,key]);
  useEffect(()=>{
    if(!session)return;
    let active=true;
    const load=()=>fetch(base+'/details',{headers:{'x-public-link':key,'x-public-session':session},cache:'no-store'}).then(async r=>{
      if((r.status===401||r.status===404)){
        if(active){
          sessionStorage.removeItem(sessionKey);
          setSession('');
          setData(undefined);
        }
        return;
      }
      if(!r.ok)throw new Error('Your move could not be refreshed.');
      const next=await r.json();
      if(active){
        setData(next);
        if(next.company_details?.color)setThemeColor(next.company_details.color);
      }
    }).catch(e=>{if(active)setError(e.message);});
    void load();
    // Poll every minute (60s) if spark is queued or running, otherwise standard 15s
    const isSparkPending = data?.spark && (data.spark.status === 'queued' || data.spark.status === 'running');
    const interval=setInterval(()=>void load(), isSparkPending ? 60000 : 15000);
    return ()=>{active=false;clearInterval(interval);};
  },[base,key,session,sessionKey,data?.spark?.status]);
  useEffect(()=>{if(!sent)return;const t=setInterval(()=>setClock(Date.now()),1000);return ()=>clearInterval(t);},[sent]);
  async function send(){setBusy(true);setError('');try{await call('/send-code',{channel});setSent(true);setResendAt(Date.now()+60000);setClock(Date.now());}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function verify(){
    setBusy(true);setError('');
    try{
      const value=await call('/verify',{code});
      sessionStorage.setItem(sessionKey, value.session);
      setSession(value.session);
      setCode('');
    }catch(e){
      setError((e as Error).message);
    }finally{
      setBusy(false);
    }
  }
  function choose(list:FileList|null){
    if(!list?.length)return;
    try {
      // Snapshot the browser FileList before the input is reset or React runs the updater.
      const added:Pending[]=Array.from(list).map(file=>{
        const preview=file.type.startsWith('image/')?URL.createObjectURL(file):undefined;
        if(preview)previews.current.push(preview);
        return {id:crypto.randomUUID(),file,preview,progress:0,status:file.size===0?'Empty file':'Ready'};
      });
      setFiles(prev=>[...prev,...added]);setError('');
    } catch {setError('Could not select these files. Please choose them again.');}
  }
  async function upload(){
    setBusy(true);setError('');
    let uploadedAny = false;
    try{for(const item of files.filter(f=>f.status==='Ready'||f.status==='Try again')){
      const update=(status:string,progress:number)=>setFiles(prev=>prev.map(f=>f.id===item.id?{...f,status,progress,error:undefined}:f));
      update('Uploading',0);
      try{
        const mime=item.file.type || 'application/octet-stream';
        const prepared=await call('/prepare-upload',{request_id:item.id,name:item.file.name,size:item.file.size,content_type:mime});
        if(!prepared.completed){
          await new Promise<void>((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST',prepared.upload.url);xhr.timeout=0;xhr.upload.onprogress=e=>{if(e.lengthComputable)update('Uploading',Math.round(e.loaded/e.total*90));};xhr.onload=()=>xhr.status>=200&&xhr.status<300?resolve():reject(new Error('Upload interrupted. Please try again.'));xhr.onerror=xhr.ontimeout=()=>reject(new Error('Upload interrupted. Please try again.'));const form=new FormData();Object.entries(prepared.upload.fields as Record<string,string>).forEach(([k,v])=>form.append(k,v));form.append('file',item.file);xhr.send(form);});
          update('Finishing upload',95);await call('/finish-upload',{request_id:item.id});
        }
        update('Uploaded',100);
        uploadedAny = true;
      }catch(e){const message=(e as Error).message;setFiles(prev=>prev.map(f=>f.id===item.id?{...f,status:'Try again',progress:0,error:message}:f));}
    }
    if(uploadedAny){
      setHasNewUploads(true);
      setReportState('idle');
      void refreshDetails();
    }
    }finally{setBusy(false);}
  }
  async function walkthrough(){setBusy(true);setError('');try{const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;const result=await call(rescheduling?'/reschedule':'/walkthrough',{availability,timezone});setRequested(true);setRescheduling(false);setData(prev=>prev?{...prev,walkthrough:result,participant_url:''}:prev);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}

  function startEditMove(){
    if(!data)return;
    setMoveDraft({
      name:data.name||'',
      phone:data.phone||'',
      email:data.email||'',
      move_date:data.move_date?data.move_date.slice(0,10):'',
      pickup:data.pickup||'',
      delivery:data.delivery||'',
    });
    setEditingMove(true);
  }

  async function saveMoveDetails(e:React.FormEvent){
    e.preventDefault();
    setBusy(true);
    setError('');
    try{
      const result=await call('/details',moveDraft);
      setData(result);
      setEditingMove(false);
    }catch(err){
      setError((err as Error).message);
    }finally{
      setBusy(false);
    }
  }

  async function refreshDetails(){
    if(!session)return;
    setBusy(true);
    setError('');
    try{
      const next=await call('/details');
      setData(next);
    }catch(err){
      setError((err as Error).message);
    }finally{
      setBusy(false);
    }
  }

  const wait=Math.max(0,Math.ceil((resendAt-clock)/1000));

  const paletteStyle = useMemo(() => {
    let c = (themeColor || '#214c3e').replace('#', '');
    if (c.length === 3) c = c.split('').map(x => x + x).join('');
    const r = parseInt(c.slice(0, 2), 16) / 255 || 0;
    const g = parseInt(c.slice(2, 4), 16) / 255 || 0;
    const b = parseInt(c.slice(4, 6), 16) / 255 || 0;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h = 0, s = 0, l = (max + min) / 2;
    if (max !== min) {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r: h = (g - b) / d + (g < b ? 6 : 0); break;
        case g: h = (b - r) / d + 2; break;
        case b: h = (r - g) / d + 4; break;
      }
      h = Math.round(h * 60);
    }
    s = Math.round(s * 100);
    l = Math.round(l * 100);
    return {
      '--cm-primary': themeColor || '#214c3e',
      '--cm-primary-hover': `hsl(${h}, ${Math.min(100, s + 10)}%, ${Math.max(12, l - 8)}%)`,
      '--cm-primary-dark': `hsl(${h}, ${Math.min(100, s + 15)}%, ${Math.max(8, l - 16)}%)`,
      '--cm-tint': `hsl(${h}, ${Math.min(45, Math.round(s * 0.45))}%, 96%)`,
      '--cm-tint-strong': `hsl(${h}, ${Math.min(40, Math.round(s * 0.4))}%, 91%)`,
      '--cm-tint-hover': `hsl(${h}, ${Math.min(45, Math.round(s * 0.45))}%, 93%)`,
      '--cm-border': `hsl(${h}, ${Math.min(30, Math.round(s * 0.35))}%, 80%)`,
      '--cm-border-soft': `hsl(${h}, ${Math.min(25, Math.round(s * 0.3))}%, 88%)`,
      '--cm-text': `hsl(${h}, ${Math.min(40, Math.round(s * 0.5))}%, 15%)`,
      '--cm-text-muted': `hsl(${h}, ${Math.min(25, Math.round(s * 0.35))}%, 38%)`,
    } as React.CSSProperties;
  }, [themeColor]);

  return (
    <div className="customer-move" style={paletteStyle}>
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
              <button className="slds-button cm-primary" disabled={busy||!channel||!key} onClick={()=>void send()}>{busy?'Sending...':'Send verification code'}</button>
            ) : (
              <form onSubmit={e=>{e.preventDefault();void verify();}}>
                <label className="cm-code">Enter your 6-digit code<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,''))}/></label>
                <button className="slds-button cm-primary" disabled={busy||code.length!==6}>{busy?'Checking...':'View my move'}</button>
                <button type="button" className="slds-button cm-text-button" disabled={busy||wait>0} onClick={()=>void send()}>{wait?`Send again in ${wait}s`:'Send a new code'}</button>
              </form>
            )}
            <small className="cm-private">Your information is private. No account or password needed.</small>
          </section>
        ) : !data ? (
          <p role="status">Opening your move...</p>
        ) : (
          <>
            <header className="cm-company-header">
              <div className="cm-company-header-left">
                <div className="cm-company-logo-placeholder" aria-hidden="true">
                  <span>LOGO</span>
                </div>
                <div>
                  <span className="cm-company-welcome">Welcome to</span>
                  <h2 className="cm-company-name">{data.company_details?.name || data.company || 'Your Moving Team'}</h2>
                </div>
              </div>
              {(data.company_details?.phone || data.company_details?.office_address) && (
                <div className="cm-company-header-right">
                  {data.company_details.phone && (
                    <a className="cm-company-phone" href={`tel:${data.company_details.phone}`}>
                      📞 {data.company_details.phone}
                    </a>
                  )}
                  {data.company_details.office_address && (
                    <span className="cm-company-address">
                      📍 {data.company_details.office_address}
                    </span>
                  )}
                </div>
              )}
            </header>

            <section className="cm-two-col cm-intro">
              <div>
                <div className="cm-eyebrow">LET'S MAKE YOUR NEXT MOVE EASIER</div>
                <h1>Hi {data.name.split(' ')[0]},<br/>you're in the right place.</h1>
                <p>Share a little more about your home.<br/>We'll take care of the estimate.</p>
              </div>
              <section className="cm-card cm-route">
                <div className="cm-route-header">
                  <div className="cm-eyebrow">YOUR MOVE</div>
                  <div className="cm-route-actions-top">
                    <button type="button" className="slds-button cm-refresh-btn" aria-label="Refresh move details" title="Refresh move details" disabled={busy} onClick={()=>void refreshDetails()}>&#8635;</button>
                    {!editingMove && (
                      <button type="button" className="slds-button cm-edit-button" onClick={startEditMove}>Edit</button>
                    )}
                  </div>
                </div>

                {!editingMove ? (
                  <>
                    <h2>{data.move_date?new Date(data.move_date.slice(0,10)+'T12:00:00').toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'}):'Date to be confirmed'}</h2>
                    <ol>{[{address:data.pickup,type:'pickup'},...data.stops,{address:data.delivery,type:'delivery'}].map((stop,i)=><li key={i}><small>{stop.type==='pickup'?'Pickup':stop.type==='delivery'?'Delivery':'Stop'}</small><strong>{stop.address||'—'}</strong></li>)}</ol>
                    <div className="cm-contact"><strong>{data.name}</strong><span>{data.phone}</span><span>{data.email}</span></div>
                  </>
                ) : (
                  <form className="cm-route-edit" onSubmit={saveMoveDetails}>
                    <label>
                      Move Date
                      <input type="date" value={moveDraft.move_date} onChange={e=>setMoveDraft(prev=>({...prev,move_date:e.target.value}))} />
                    </label>
                    <label>
                      Pickup Address / Zip
                      <input type="text" placeholder="123 Main St, City, ST 12345" value={moveDraft.pickup} onChange={e=>setMoveDraft(prev=>({...prev,pickup:e.target.value}))} />
                    </label>
                    <label>
                      Delivery Address / Zip
                      <input type="text" placeholder="456 Elm St, City, ST 67890" value={moveDraft.delivery} onChange={e=>setMoveDraft(prev=>({...prev,delivery:e.target.value}))} />
                    </label>
                    <label>
                      Full Name
                      <input type="text" value={moveDraft.name} onChange={e=>setMoveDraft(prev=>({...prev,name:e.target.value}))} />
                    </label>
                    <label>
                      Phone Number (required)
                      <input type="tel" required value={moveDraft.phone} onChange={e=>setMoveDraft(prev=>({...prev,phone:e.target.value}))} />
                    </label>
                    <label>
                      Email Address (optional)
                      <input type="email" value={moveDraft.email} onChange={e=>setMoveDraft(prev=>({...prev,email:e.target.value}))} />
                    </label>
                    <div className="cm-route-actions">
                      <button type="submit" className="slds-button cm-save-btn" disabled={busy}>Save changes</button>
                      <button type="button" className="slds-button cm-cancel-btn" disabled={busy} onClick={()=>setEditingMove(false)}>Cancel</button>
                    </div>
                  </form>
                )}
              </section>
            </section>
            {error&&<div className="cm-error" role="alert">{error}</div>}
            <div className="cm-two-col cm-actions-row">
              <section className="cm-card cm-upload">
                <div className="cm-eyebrow">SHOW US WHAT'S MOVING</div>
                <h2>Add photos, documents<br/>or videos.</h2>
                <p>A few photos of each room help us understand your move. Include any large or delicate items.</p>
                <div className="cm-upload-row">
                  <label className="cm-drop">
                    <span className="cm-drop-icon" aria-hidden="true">📁</span>
                    <strong>Choose files or drop here</strong>
                    <input type="file" multiple disabled={busy} onChange={e=>{choose(e.target.files);e.target.value='';}}/>
                  </label>
                  <button className="slds-button cm-primary cm-upload-btn" disabled={busy||!files.some(f=>['Ready','Try again'].includes(f.status))} onClick={()=>void upload()}>{busy?'Please wait...':'Upload files'}</button>
                </div>
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
                      {item.status!=='Uploaded' && !busy && <button className="slds-button" aria-label={`Remove ${item.file.name}`} onClick={()=>setFiles(prev=>prev.filter(f=>f.id!==item.id))}>x</button>}
                    </article>
                  ))}
                </div>
                {data.files.length>0&&<details><summary>{data.files.length} saved files</summary>{data.files.map(file=><p key={file.id}>{file.name}</p>)}</details>}
                {data.files.length > 0 && (!data.spark || hasNewUploads) && reportState !== 'done' && (
                  <div className="cm-spark-box">
                    <button
                      type="button"
                      className="slds-button cm-primary cm-spark-btn"
                      disabled={busy || reportState === 'running'}
                      onClick={async () => {
                        setReportState('running');
                        setReportNotice('');
                        try {
                          await call('/generate-inventory-report', {});
                          setReportState('done');
                          setHasNewUploads(false);
                          setReportNotice("We're analyzing your photos and videos to calculate your total inventory volume.");
                          void refreshDetails();
                        } catch (err) {
                          setReportState('idle');
                          setError((err as Error).message);
                        }
                      }}
                    >
                      {reportState === 'running' ? 'Processing inventory...' : data.spark ? "Done Uploading — Recalculate My Move" : "Done Uploading — Calculate My Move"}
                    </button>
                    {reportNotice && <p role="status" className="cm-spark-notice">{reportNotice}</p>}
                  </div>
                )}
              </section>

              <section className="cm-card cm-walkthrough-card">
                <div className="cm-walkthrough-header">
                  <div>
                    <div className="cm-eyebrow">LIVE VIDEO WALKTHROUGH</div>
                    <h2>Let's take a live<br/>video walkthrough.</h2>
                    <p className="cm-walkthrough-sub">Walk us through your home from your phone. Our team will help you plan what comes next.</p>
                  </div>
                  {data.walkthrough && (
                    <span className="cm-meeting-status">
                      {({requested:'Requested',scheduled:'Approved',completed:'Completed',cancelled:'Cancelled'} as Record<string,string>)[data.walkthrough.status]||data.walkthrough.status}
                    </span>
                  )}
                </div>
                {data.walkthrough && !rescheduling ? (
                  <div className="cm-walkthrough-body">
                    <p className="cm-meeting-time">{meetingTime(data.walkthrough)}</p>
                    <div className="cm-walkthrough-actions">
                      {data.walkthrough.status==='scheduled' && data.participant_url && (
                        <a className="cm-primary" href={data.participant_url} target="_blank" rel="noopener noreferrer">Join video walkthrough</a>
                      )}
                      {['requested','scheduled'].includes(data.walkthrough.status) && (
                        <button type="button" className="cm-secondary-btn" onClick={()=>{setAvailability('');setRescheduling(true);}}>Reschedule</button>
                      )}
                    </div>
                  </div>
                ) : (
                  <form className="cm-walkthrough-form" onSubmit={e=>{e.preventDefault();void walkthrough();}}>
                    <MeetingTimePicker onChange={setAvailability} availabilityUrl={base+"/availability"} linkKey={key} session={session} moveDate={data.move_date || null} />
                    <div className="cm-walkthrough-form-actions">
                      <button className="slds-button cm-primary" disabled={busy||!availability.trim()}>{rescheduling?'Request new time':'Schedule video walkthrough'}</button>
                      {rescheduling && (
                        <button type="button" className="cm-secondary-btn" disabled={busy} onClick={()=>setRescheduling(false)}>Cancel</button>
                      )}
                    </div>
                    {requested && <p role="status" className="cm-walkthrough-notice">Request saved.</p>}
                  </form>
                )}
              </section>
            </div>

            <div className="cm-estimate cm-estimate-full">
              <div className="cm-estimate-top">
                <div className="cm-estimate-main-info">
                  <span className="cm-estimate-eyebrow">{data.estimate?'Your moving estimate':'Your estimate'}</span>
                  <strong>{data.estimate?new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(data.estimate.price)):data.spark?.status==='running'||data.spark?.status==='queued'?'Calculating your estimate...':data.spark?.status==='completed'?'Your report is ready. Pricing is pending.':'We\'re working on it.'}</strong>
                  <p className="cm-estimate-desc">{data.estimate?(Number(data.estimate.cuft) > 0 ? `${Number(data.estimate.cuft).toLocaleString()} cubic feet estimated` : 'Based on your moving details'):data.spark?.status==='running'||data.spark?.status==='queued'?'Analyzing your uploaded photos and videos to calculate volume and pricing...':data.spark?.status==='completed'?'Your report is ready. We still need to finish preparing your inventory and estimate. Any available service questions are shown below.':data.files.length?'Your files have been received. Your inventory and estimate are being prepared.':'Add photos or request a video walkthrough to help us prepare your estimate.'}</p>
                </div>
                {data.spark && (
                  <div className="cm-spark-card cm-spark-estimate-card">
                    <div className="cm-spark-status-row">
                      <span className="cm-spark-pill">
                        <span className={`cm-spark-dot ${data.spark.status === 'completed' ? 'dot-complete' : data.spark.status === 'failed' ? 'dot-failed' : 'dot-pulse'}`} />
                        {data.spark.status === 'completed' ? 'Report ready' : data.spark.status === 'running' ? 'Analyzing media...' : data.spark.status === 'failed' ? 'Report failed' : 'Queued'}
                      </span>
                      {data.spark.status === 'completed' && data.spark.cuft ? <strong className="cm-spark-volume">{data.spark.cuft} cu ft</strong> : null}
                    </div>
                    {data.spark.status === 'completed' && data.spark.shareUrl && (
                      <a href={data.spark.shareUrl} target="_blank" rel="noopener noreferrer" className="cm-spark-link">
                        View Itemized Report ↗
                      </a>
                    )}
                  </div>
                )}
              </div>
              {data.estimate && Number(data.estimate.cuft) > 0 && (
                <div className="cm-estimate-details">
                  <div className="cm-estimate-detail-item">
                    <span>Volume</span>
                    <strong>{Number(data.estimate.cuft).toLocaleString()} cu ft</strong>
                  </div>
                </div>
              )}
              {data.estimate?.charges && data.estimate.charges.length > 0 && (
                <div className="cm-estimate-breakdown">
                  <div className="cm-estimate-breakdown-title">Price Breakdown</div>
                  <div className="cm-estimate-charges-grid">
                    {data.estimate.charges.map((charge, idx) => (
                      <div key={idx} className="cm-estimate-charge-row">
                        <div>
                          <strong>{charge.name}</strong>
                          {charge.description && <small>{charge.description}</small>}
                        </div>
                        <span>
                          {new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(charge.total)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {(data.packing_items?.length > 0 || data.packing_package) && (
                <div className="cm-estimate-extra-actions">
                  <button
                    type="button"
                    className="slds-button cm-primary cm-extra-services-btn"
                    onClick={() => {
                      setPackingSelection(Object.fromEntries(data.packing_items.filter(item => item.selected).map(item => [item.id, item.selected_service || ''])));
                      setPackingStep(data.packing_items.length ? 'bulky' : 'package');
                      setPackageSelection(data.packing_package?.selection || { mode: 'none', unpacking: false, item_ids: [] });
                      setPackingError('');
                      setShowQuestions(true);
                    }}
                  >
                    {data.packing_saved ? '✓ Review extra services & questions' : '+ Add extra services & details'}
                  </button>
                  {data.packing_saved && (
                    <span className="cm-meeting-status">Extra services saved</span>
                  )}
                </div>
              )}
            </div>

            {showQuestions && (
              <div className="cm-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="packing-title">
                <div className="cm-modal-card">
                  <div className="cm-modal-header">
                    <div>
                      <span className="cm-eyebrow">EXTRA SERVICES</span>
                      <h3 id="packing-title">{packingStep === 'bulky' ? 'Packing & crating for your bulky items' : 'Packing services'}</h3>
                      <p>{packingStep === 'bulky' ? 'Select each item you want us to pack or crate.' : 'Choose packing and optional unpacking for your move.'}</p>
                    </div>
                    <button type="button" className="cm-modal-close" aria-label="Close" disabled={packingSaving} onClick={() => setShowQuestions(false)}>&times;</button>
                  </div>
                  <div className="cm-modal-body">
                    {packingStep === 'bulky' ? <>
                    <p className="cm-step-sub">Unchecked items will be packed by owner. When both services are available, choose one.</p>
                    <div className="cm-checklist">
                      {data.packing_items.map(item => (
                        <div key={item.id}>
                          <label className="cm-check-item">
                            <input type="checkbox" disabled={packingSaving} checked={item.id in packingSelection} onChange={e => {
                              const checked = e.target.checked;
                              setPackingSelection(prev => {
                                const next = { ...prev };
                                if (checked) next[item.id] = item.services.length === 1 ? item.services[0].kind : '';
                                else delete next[item.id];
                                return next;
                              });
                            }} />
                            <span>{item.label}{item.services.length === 1 && <> &mdash; {item.services[0].kind === 'packing' ? 'Packing' : 'Crating'}: {money(item.services[0].price)}</>}</span>
                          </label>
                          {item.id in packingSelection && item.services.length > 1 && (
                            <fieldset disabled={packingSaving}>
                              <legend>Choose a service for {item.label}</legend>
                              {item.services.map(service => (
                                <label key={service.kind} className="cm-check-item">
                                  <input type="radio" name={`service-${item.id}`} checked={packingSelection[item.id] === service.kind} onChange={() => setPackingSelection(prev => ({ ...prev, [item.id]: service.kind }))} />
                                  <span>{service.kind === 'packing' ? 'Packing' : 'Crating'} &mdash; {money(service.price)}</span>
                                </label>
                              ))}
                            </fieldset>
                          )}
                        </div>
                      ))}
                    </div>
                    <p><strong>Selected services total: {money(data.packing_items.reduce((sum, item) => sum + (item.services.find(service => service.kind === packingSelection[item.id])?.price || 0), 0))}</strong></p>
                    </> : data.packing_package && <CustomerPackingOptions config={data.packing_package} selection={packageSelection} onChange={setPackageSelection} disabled={packingSaving} />}
                    {!data.estimate && <p>Your choices will be saved and included when your estimate is ready.</p>}
                    {packingError && <p role="alert">{packingError}</p>}
                  </div>
                  <div className="cm-modal-footer">
                    <button type="button" className="cm-secondary-btn" disabled={packingSaving} onClick={() => packingStep === 'package' && data.packing_items.length ? setPackingStep('bulky') : setShowQuestions(false)}>{packingStep === 'package' && data.packing_items.length ? 'Back' : 'Cancel'}</button>
                    {packingStep === 'bulky' && data.packing_package ? <button type="button" className="slds-button cm-primary" onClick={() => {
                      if (Object.values(packingSelection).some(value => !value)) { setPackingError('Choose packing or crating for each checked item.'); return; }
                      setPackingError(''); setPackingStep('package');
                    }}>Next: packing services</button> : <button type="button" className="slds-button cm-primary" disabled={packingSaving} onClick={() => void savePacking()}>{packingSaving ? 'Saving...' : data.estimate ? 'Save & update price' : 'Save selections'}</button>}
                  </div>
                </div>
              </div>
            )}
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
