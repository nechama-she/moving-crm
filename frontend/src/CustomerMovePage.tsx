import CustomerAddressInput from "./CustomerAddressInput";
import type { SelectedAddress } from "./googlePlaces";
import CustomerItemQuestions, { type ItemQuestion } from "./CustomerItemQuestions";
import QuestionReferenceImages from "./QuestionReferenceImages";
import ReportLinks from './ReportLinks';
import { savedPhotos, storePhoto, removePhoto } from './photoDrafts';
import ManualInventoryModal from "./ManualInventoryModal";
import type { EditableReportFile } from "./ReportFileList";
import ReportFileGallery from "./ReportFileGallery";
import ReportHistory, { type ReportRun } from "./ReportHistory";
import CustomerPackingOptions, { type PackingPackage, type PackingSelection } from "./CustomerPackingOptions";
import MeetingTimePicker from "./MeetingTimePicker";
import { useCustomerUpdates } from './useCustomerUpdates';
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import "./CustomerMovePage.css";

type LinkSms = { sent_at: string; phone_last4: string };
type Details = {
  google_maps_browser_key?: string;

  item_questions?: ItemQuestion[];
  link_sms?: LinkSms | null;
  list_changed?: boolean;
  inventory_draft?: { body: { rooms: { room_type_id: string; name: string; items: { item_id: string; quantity: number }[] }[] }; rooms: { name: string; items: { name: string; amount: number; cuft: number }[] }[]; rows: unknown[]; cuft: number };
  report_history?: ReportRun[];
  new_file_count?: number;
  editable_files?: EditableReportFile[];
  files_changed?: boolean;
  packing_package: PackingPackage | null;
  packing_items: { id: string; name: string; label: string; price: number; selected: boolean; selected_service: string | null; services: { kind: string; price: number }[] }[];
  packing_saved: boolean;
  name: string;
  phone: string;
  email: string;
  move_date: string;
  pickup: string;
  delivery: string;
  company: string;
  company_details?: {
    logo?: string;
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
  spark?: { id: string; status: string; source?: string; shareUrl?: string; cuft?: number; update_error?: string } | null;
  walkthrough: { status: string; availability: string; scheduled_at: string | null; timezone: string } | null;
  participant_url: string;
  files: { id: string; name: string; size: number }[];
};
type Pending = {id:string;file:File;status:string;progress:number;preview?:string;error?:string};
export default function CustomerMovePage() {
  const {accessId}=useParams();
  const [linkSms, setLinkSms] = useState<LinkSms | null>(null);
  const [repPage, setRepPage] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('audience') === 'rep');
  const sessionKey = `cm_session_${accessId}${repPage ? '_rep' : ''}`;
  const [key]=useState(()=>new URLSearchParams(window.location.hash.slice(1)).get('key')||'');
  const [session,setSession]=useState(()=>sessionStorage.getItem(sessionKey)||'');
  const [options,setOptions]=useState<{channel:string;destination:string;label?:string}[]>([]),[channel,setChannel]=useState('');
  const [code,setCode]=useState(''),[sent,setSent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [data,setData]=useState<Details>(),[files,setFiles]=useState<Pending[]>([]),[availability,setAvailability]=useState(''),[requested,setRequested]=useState(false),[rescheduling,setRescheduling]=useState(false);
  const uploadLock = useRef(false);
  const filePicker = useRef<HTMLInputElement>(null);
  const meetingDialog = useRef<HTMLDialogElement>(null);
  const [photosRestored, setPhotosRestored] = useState(false);
  useEffect(() => {
    let active = true;
    savedPhotos(accessId || '').then(rows => {
      if (!active) return;
      setFiles(rows.map(row => { const preview = row.file.type.startsWith('image/') ? URL.createObjectURL(row.file) : undefined; if (preview) previews.current.push(preview); return { ...row, preview, status: row.file.size ? 'Ready' : 'Empty file', progress: 0 }; }));
      setPhotosRestored(true);
    }).catch(() => { if (active) { setError('Could not restore pending photos on this device.'); setPhotosRestored(true); } });
    return () => { active = false; };
  }, [accessId]);
  useEffect(() => {
    if (photosRestored && data && session && !busy && !uploadLock.current && files.some(file => file.status === 'Ready')) void upload();
  }, [files, photosRestored, data, session, busy]);
  const [editingMove,setEditingMove]=useState(false);
  const addressDraft = useRef<{ pickup: string; delivery: string; pickup_place: SelectedAddress | null; delivery_place: SelectedAddress | null }>({ pickup: '', delivery: '', pickup_place: null, delivery_place: null });
  const [moveDraft,setMoveDraft]=useState({name:'',phone:'',email:'',move_date:'',pickup:'',delivery:''});
  const [reportState,setReportState]=useState<'idle'|'running'|'done'>('idle');
  const [reportNotice,setReportNotice]=useState('');
  const [hasNewUploads, setHasNewUploads] = useState(false);
  const [resendAt,setResendAt]=useState(0),[clock,setClock]=useState(Date.now());
  const [showQuestions, setShowQuestions] = useState(false);
  const [termsError, setTermsError] = useState('');
  const [showInventoryList, setShowInventoryList] = useState(false);
  const [packingSelection, setPackingSelection] = useState<Record<string, string>>({});
  const [packingStep, setPackingStep] = useState<'bulky' | 'package' | 'items'>('bulky');
  const [packageSelection, setPackageSelection] = useState<PackingSelection>({ mode: 'none', unpacking: false, item_ids: [] });
  const [calculatingPrice, setCalculatingPrice] = useState(false);
  const [calculationError, setCalculationError] = useState('');
  const [packingSaving, setPackingSaving] = useState(false);
  const [packingError, setPackingError] = useState('');
  const money = (amount: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
  async function selectReport(id: string) {
    setCalculatingPrice(true);
    try {
      await call(`/reports/${encodeURIComponent(id)}/select`, {});
      setFiles(current => current.filter(file => file.status !== 'Uploaded'));
      setHasNewUploads(false);
    } finally {
      try { setData(await call('/details')); }
      finally { setCalculatingPrice(false); }
    }
  }
  async function removeReportFile(id: string) {
    setBusy(true);
    try {
      await call(`/files/${encodeURIComponent(id)}`, undefined, 'DELETE');
      setData(await call('/details'));
      setReportState('idle');
      setHasNewUploads(true);
    } finally { setBusy(false); }
  }
  async function savePacking() {
    if (Object.values(packingSelection).some(value => !value)) {
      setPackingError('Choose packing or crating for each checked item.');
      return;
    }
    setPackingSaving(true);
    setPackingError('');
    try {
      setData(await call('/packing', { selections: packingSelection, ...(data?.packing_package ? { package: packageSelection } : {}) }));
      if (data?.item_questions?.length) setPackingStep('items'); else setShowQuestions(false);
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
      throw Object.assign(new Error(typeof result.detail==='string'?result.detail:result.detail?.message || 'Please check your details and try again.'), {detail:result.detail});
    }
    return result;
  }
  useEffect(()=>{
    document.title='Your move';
    const referrer=document.createElement('meta');referrer.name='referrer';referrer.content='strict-origin';document.head.appendChild(referrer);
    const urls=previews.current;
    return ()=>{referrer.remove();urls.forEach(URL.revokeObjectURL);};
  },[]);
  useEffect(()=>{const abort=new AbortController();fetch(base+'/verify-options',{headers:{'x-public-link':key},cache:'no-store',signal:abort.signal}).then(async r=>{const value=await r.json();if(!r.ok)throw new Error(value.detail||'This link is unavailable.');setRepPage(value.audience === 'rep');setOptions(value.options);setLinkSms(value.link_sms || null);setChannel(value.options[0]?.channel||'');if(value.company?.color)setThemeColor(value.company.color);}).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return ()=>abort.abort();},[base,key]);
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
    return ()=>{active=false;};
  },[base,key,session,sessionKey]);
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
  async function choose(list:FileList|null){
    if(!list?.length)return;
    try {
      // Snapshot the browser FileList before the input is reset or React runs the updater.
      const added:Pending[]=Array.from(list).map(file=>{
        const preview=file.type.startsWith('image/')?URL.createObjectURL(file):undefined;
        if(preview)previews.current.push(preview);
        return {id:crypto.randomUUID(),file,preview,progress:0,status:file.size===0?'Empty file':'Ready'};
      });
      await Promise.all(added.map(item => storePhoto(accessId || '', item.id, item.file)));
      setFiles(prev=>[...prev,...added]);setError('');
    } catch {setError('Could not save these files on this device. Check available storage and choose them again.');}
  }
  async function upload(){
    if (uploadLock.current) return;
    uploadLock.current = true;
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
        await removePhoto(accessId || '', item.id);
        update('Uploaded',100);
        uploadedAny = true;
      }catch(e){const message=(e as Error).message;setFiles(prev=>prev.map(f=>f.id===item.id?{...f,status:'Try again',progress:0,error:message}:f));}
    }
    if(uploadedAny){
      setHasNewUploads(true);
      setReportState('idle');
      void refreshDetails();
    }
    }finally{uploadLock.current = false;setBusy(false);}
  }
  async function walkthrough(){setBusy(true);setError('');try{const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;const result=await call(rescheduling?'/reschedule':'/walkthrough',{availability,timezone});setRequested(true);setRescheduling(false);meetingDialog.current?.close();setData(prev=>prev?{...prev,walkthrough:result,participant_url:''}:prev);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}

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
    addressDraft.current = { pickup: data.pickup || '', delivery: data.delivery || '', pickup_place: null, delivery_place: null };
    setMoveErrors({});
    setEditingMove(true);
  }

  const [moveErrors,setMoveErrors] = useState<Record<string,string>>({});
  function clearMoveError(field: string) {
    if (moveErrors[field]) setMoveErrors(previous => { const next={...previous}; delete next[field]; return next; });
  }
  const latestMoveDraft = useRef(moveDraft);
  latestMoveDraft.current = moveDraft;
  async function saveMoveDetails(e:React.FormEvent){
    e.preventDefault();
    const submittedAddresses = addressDraft.current;
    setBusy(true);
    setError('');
    setMoveErrors({});
    try{
      const result=await call('/details', { ...moveDraft, ...submittedAddresses });
      setData(result);
      if (latestMoveDraft.current === moveDraft && addressDraft.current === submittedAddresses) setEditingMove(false);
    }catch(err){
      const failure=err as Error & {detail?: {field?:string;message?:string} | {loc?:string[];msg?:string}[]};
      const fields: Record<string,string>={};
      if(Array.isArray(failure.detail)) {
        for(const item of failure.detail) {
          const field=item.loc?.[1]?.replace(/_place$/, '');
          if(field && ['name','phone','email','move_date','pickup','delivery'].includes(field)) fields[field]=(item.msg || 'Check this field.').replace(/^Value error, /,'');
        }
      } else if(failure.detail?.field) fields[failure.detail.field]=failure.detail.message || failure.message;
      if(!Object.keys(fields).length) fields.form=failure.message;
      setMoveErrors(fields);
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

  const updatesUnavailable = useCustomerUpdates(base, key, session, refreshDetails);
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
        {!repPage && (data?.link_sms || linkSms) && (
          <p role="status" className="cm-link-sms-notice">
            We sent a text message to your phone{(data?.link_sms || linkSms)?.phone_last4 ? ` ending in ${(data?.link_sms || linkSms)?.phone_last4}` : ''} with a link to this page. You can use it to return anytime.
          </p>
        )}
        {!session ? (
          <section className="cm-verify">
            <div className="cm-eyebrow">WELCOME</div>
            <h1>Let's get your<br/>move underway.</h1>
            <p>{repPage ? 'Verify with the assigned rep or company phone to open this move.' : "First, verify it's you. We'll send a code to the phone or email you provided."}</p>
            {error && <div role="alert" className="cm-error">{error}</div>}
            <fieldset>
              <legend>Where should we send your code?</legend>
              {options.map(option => (
                <label key={option.channel}>
                  <input type="radio" name="channel" value={option.channel} checked={channel===option.channel} disabled={busy} onChange={()=>{setChannel(option.channel);setSent(false);}}/>
                  {option.label || (option.channel==='sms' ? 'Text message' : 'Email')} <span>{option.destination}</span>
                </label>
              ))}
            </fieldset>
            {repPage && options.length === 0 && <p role="status">No rep or company phone is configured. Add a phone number in the CRM to verify this page.</p>}
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
                <div className="cm-company-logo-placeholder" style={data.company_details?.logo ? { border: 0, background: "transparent", overflow: "hidden", flexShrink: 0 } : undefined}>
                  {data.company_details?.logo ? <img src={data.company_details.logo} alt={`${data.company_details.name} logo`} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <span>LOGO</span>}
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
                  <form className="cm-route-edit" noValidate onSubmit={saveMoveDetails}>
                    <label>
                      Move Date
                      <input type="date" value={moveDraft.move_date} aria-invalid={!!moveErrors.move_date} aria-describedby={moveErrors.move_date ? 'move-move_date-error' : undefined} onChange={e=>{clearMoveError('move_date');setMoveDraft(prev=>({...prev,move_date:e.target.value}));}} />
                      {moveErrors.move_date && <small id="move-move_date-error" className="cm-field-error" role="alert">{moveErrors.move_date}</small>}
                    </label>
                    <CustomerAddressInput label="Pickup address" error={moveErrors.pickup} apiKey={data.google_maps_browser_key || ''} initialValue={data.pickup || ''} disabled={busy}
                      onChange={(text, place) => { clearMoveError('pickup'); addressDraft.current = { ...addressDraft.current, pickup: text, pickup_place: place }; }} />
                    <CustomerAddressInput label="Delivery address" error={moveErrors.delivery} apiKey={data.google_maps_browser_key || ''} initialValue={data.delivery || ''} disabled={busy}
                      onChange={(text, place) => { clearMoveError('delivery'); addressDraft.current = { ...addressDraft.current, delivery: text, delivery_place: place }; }} />
                    <label>
                      Full Name
                      <input type="text" value={moveDraft.name} aria-invalid={!!moveErrors.name} aria-describedby={moveErrors.name ? 'move-name-error' : undefined} onChange={e=>{clearMoveError('name');setMoveDraft(prev=>({...prev,name:e.target.value}));}} />
                      {moveErrors.name && <small id="move-name-error" className="cm-field-error" role="alert">{moveErrors.name}</small>}
                    </label>
                    <label>
                      Phone Number (required)
                      <input type="tel" required value={moveDraft.phone} aria-invalid={!!moveErrors.phone} aria-describedby={moveErrors.phone ? 'move-phone-error' : undefined} onChange={e=>{clearMoveError('phone');setMoveDraft(prev=>({...prev,phone:e.target.value}));}} />
                      {moveErrors.phone && <small id="move-phone-error" className="cm-field-error" role="alert">{moveErrors.phone}</small>}
                    </label>
                    <label>
                      Email Address (optional)
                      <input type="email" value={moveDraft.email} aria-invalid={!!moveErrors.email} aria-describedby={moveErrors.email ? 'move-email-error' : undefined} onChange={e=>{clearMoveError('email');setMoveDraft(prev=>({...prev,email:e.target.value}));}} />
                      {moveErrors.email && <small id="move-email-error" className="cm-field-error" role="alert">{moveErrors.email}</small>}
                    </label>
                    <div className="cm-route-actions">
                      {moveErrors.form && <p className="cm-field-error" role="alert">{moveErrors.form}</p>}
                      <button type="submit" className="slds-button cm-save-btn" disabled={busy}>Save changes</button>
                      <button type="button" className="slds-button cm-cancel-btn" disabled={busy} onClick={()=>setEditingMove(false)}>Cancel</button>
                    </div>
                  </form>
                )}
              </section>
            </section>
            {error&&<div className="cm-error" role="alert">{error}</div>}
            {updatesUnavailable && <p role="status">Live updates are disconnected. Use Refresh move details to check for changes.</p>}
            {data.spark?.update_error && <p role="alert">{data.spark.update_error}</p>}
            <div className="cm-actions-stack cm-actions-row">
              <section className="cm-card cm-upload">
                <div className="cm-eyebrow">SHOW US WHAT'S MOVING</div>
                <h2>Add files, a list, or request a virtual estimate.</h2>
                <p>Upload photos, videos, or documents, create an item list, or schedule a live virtual walkthrough with our team.</p>
                <p>Save and update your inventory anytime. When you&#8217;re ready, generate one report to calculate your total volume and estimate.</p>
                <div className="cm-inventory-actions">
                  <button type="button" className="slds-button cm-add-list-button" onClick={() => setShowInventoryList(true)}>{data.inventory_draft ? 'Update list' : 'Add a list'}</button>
                  <button type="button" className="slds-button cm-add-list-button" disabled={busy || !photosRestored} onClick={() => filePicker.current?.click()}>Upload files</button>
                  <button type="button" className="slds-button cm-add-list-button" onClick={() => meetingDialog.current?.showModal()}>Virtual estimate</button>
                  <input ref={filePicker} type="file" multiple hidden disabled={busy || !photosRestored} onChange={e=>{void choose(e.target.files);e.target.value='';}}/>
                  {files.some(f => f.status === 'Try again') && <button className="slds-button cm-primary cm-upload-btn" disabled={busy} onClick={()=>void upload()}>Retry upload</button>}
                </div>
                <div className="cm-file-list">
                  {files.filter(item => item.status !== 'Uploaded').map(item => (
                    <article key={item.id}>
                      {item.preview && <img src={item.preview} alt="" />}
                      <div>
                        <strong>{item.file.name}</strong>
                        <small role="status">{item.status}{item.status==='Uploading'?` ${item.progress}%`:''}</small>
                        {item.error && <small role="alert" style={{color:'#974327'}}>{item.error}</small>}
                        <progress max={100} value={item.progress} aria-label={`${item.file.name} upload progress`} />
                      </div>
                      {item.status!=='Uploaded' && !busy && <button className="slds-button" aria-label={`Remove ${item.file.name}`} onClick={()=>{ void removePhoto(accessId || '', item.id).then(()=>setFiles(prev=>prev.filter(f=>f.id!==item.id))).catch(()=>setError('Could not remove this pending file.')); }}>x</button>}
                    </article>
                  ))}
                </div>
                <ReportFileGallery newFileIds={(data.editable_files || data.files).filter(file => !(data.report_history?.find(report => report.current)?.files || []).some(previous => previous.id === file.id)).map(file => file.id)} files={data.editable_files || data.files} loadPreview={async id => { const response = await fetch(`${base}/file-preview/${encodeURIComponent(id)}`, { headers, cache: 'no-store' }); return response.ok ? (await response.json()).url : null; }} onRemove={removeReportFile} disabled={busy || reportState === 'running'} />
                {data.walkthrough && <div className="cm-meeting-summary">
                  <div><strong>Virtual estimate</strong><span>{meetingTime(data.walkthrough)}</span><small>{({requested:'Requested',scheduled:'Confirmed',completed:'Completed',cancelled:'Cancelled'} as Record<string,string>)[data.walkthrough.status] || data.walkthrough.status}</small></div>
                  <div className="cm-walkthrough-actions">
                    {data.walkthrough.status === 'scheduled' && data.participant_url && <a className="cm-primary" href={data.participant_url} target="_blank" rel="noopener noreferrer">Join walkthrough</a>}
                    <button type="button" className="cm-secondary-btn" onClick={() => { setAvailability(''); setRescheduling(true); meetingDialog.current?.showModal(); }}>{['requested','scheduled'].includes(data.walkthrough.status) ? 'Reschedule' : 'Schedule'}</button>
                  </div>
                </div>}

                {((data.editable_files || data.files).length > 0 || !!data.inventory_draft?.rows.length) && (!data.spark || hasNewUploads || data.files_changed || data.list_changed) && (reportState !== 'done' || data.files_changed || data.list_changed) && (
                  <div className="cm-spark-box">
                    <button
                      type="button"
                      className="slds-button cm-primary cm-spark-btn"
                      disabled={busy || reportState === 'running' || files.some(file => file.status !== 'Uploaded')}
                      onClick={async () => {
                        setReportState('running');
                        setReportNotice('');
                        try {
                          await call('/generate-inventory-report', {});
                          setReportState('done');
                          setHasNewUploads(false);
                          setReportNotice("Your report combines your files and saved list into one inventory and estimate.");
                          void refreshDetails();
                        } catch (err) {
                          setReportState('idle');
                          setError((err as Error).message);
                        }
                      }}
                    >
                      {reportState === 'running' ? 'Processing inventory...' : 'Generate report & get estimate'}
                    </button>
                    {reportNotice && <p role="status" className="cm-spark-notice">{reportNotice}</p>}
                  </div>
                )}
              </section>

              <dialog ref={meetingDialog} className="cm-meeting-dialog" aria-labelledby="cm-meeting-title">
                <button type="button" className="cm-meeting-close" aria-label="Close scheduling" onClick={() => meetingDialog.current?.close()}>&times;</button>
                <div className="cm-walkthrough-header">
                  <div>
                    <div className="cm-eyebrow">LIVE VIDEO WALKTHROUGH</div>
                    <h2 id="cm-meeting-title">Virtual estimate</h2>
                    <p className="cm-walkthrough-sub">Walk us through your home from your phone. Our team will help you plan what comes next.</p>
                  </div>
                  {data.walkthrough && (
                    <span className="cm-meeting-status">
                      {({requested:'Requested',scheduled:'Approved',completed:'Completed',cancelled:'Cancelled'} as Record<string,string>)[data.walkthrough.status]||data.walkthrough.status}
                    </span>
                  )}
                </div>
                {error && <p className="cm-error" role="alert">{error}</p>}
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
              </dialog>
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
                        {data.spark.status === 'completed' ? (data.spark.source === 'manual' ? 'Inventory list ready' : 'Report ready') : data.spark.status === 'running' ? 'Analyzing media...' : data.spark.status === 'failed' ? 'Report failed' : 'Queued'}
                      </span>
                      {data.spark.status === 'completed' && data.spark.cuft ? <strong className="cm-spark-volume">{data.spark.cuft} cu ft</strong> : null}
                    </div>
                    {data.report_history?.find(report => report.current) && <ReportLinks report={data.report_history.find(report => report.current)!} />}

                  </div>
                )}
              </div>
              {calculationError && <p role="alert">{calculationError}</p>}
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

              {(data.packing_items?.length > 0 || data.packing_package || !!data.item_questions?.length) && (
                <div className="cm-estimate-extra-actions">
                  <button
                    type="button"
                    className="slds-button cm-primary cm-extra-services-btn"
                    onClick={() => {
                      setPackingSelection(Object.fromEntries(data.packing_items.filter(item => item.selected).map(item => [item.id, item.selected_service || ''])));
                      setPackingStep(data.packing_items.length ? 'bulky' : data.packing_package ? 'package' : 'items');
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
              <ReportHistory reports={data.report_history || []} onSelect={selectReport} disabled={busy || calculatingPrice || packingSaving || reportState === 'running'} />
            </div>

            {showInventoryList && <ManualInventoryModal initialRooms={data.inventory_draft?.body.rooms} draftKey={`cm_inventory_draft_${accessId}`} loadCatalog={() => call('/inventory-catalog')} onClose={() => { setShowInventoryList(false); void refreshDetails(); }} submit={async body => {
              await call('/manual-inventory', body);
              // Refresh the summary when the editor closes; edits save without closing it.
              setHasNewUploads(true);
              setCalculationError('');
              setReportState('idle');
            }} />}
            {showQuestions && (
              <div className="cm-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="packing-title">
                <div className="cm-modal-card">
                  <div className="cm-modal-header">
                    <div>
                      <span className="cm-eyebrow">{packingStep === 'items' ? 'MOVING TERMS' : 'EXTRA SERVICES'}</span>
                      <h3 id="packing-title">{packingStep === 'items' ? 'A few details about your items' : packingStep === 'bulky' ? 'Packing & crating for your bulky items' : 'Packing services'}</h3>
                      <p>{packingStep === 'items' ? 'Review the instructions for these items before your move.' : packingStep === 'bulky' ? 'Select each item you want us to pack or crate.' : 'Choose packing and optional unpacking for your move.'}</p>
                    </div>
                    <button type="button" className="cm-modal-close" aria-label="Close" disabled={packingSaving} onClick={() => setShowQuestions(false)}>&times;</button>
                  </div>
                  <div className="cm-modal-body">
                    {packingStep === 'items' ? <CustomerItemQuestions disabled={packingSaving} questions={data.item_questions || []} endpoint={base} linkKey={key} session={session} onSave={async answer => { setPackingSaving(true); try { setData(await call('/item-answer', { ...answer, report_id: data.spark?.id })); setTermsError(''); } catch (error) { setTermsError('Please save your answer before continuing.'); throw error; } finally { setPackingSaving(false); } }} /> : packingStep === 'bulky' ? <>
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
                          <QuestionReferenceImages name={item.name} endpoint={`${base}/question-images`} linkKey={key} session={session} />
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
                  {packingStep === 'items' && termsError && <p role="alert" className="cm-field-error">{termsError}</p>}
                  <div className="cm-modal-footer">
                    {(packingStep !== 'items' || data.packing_package || data.packing_items.length > 0) && <button type="button" className="cm-secondary-btn" disabled={packingSaving} onClick={() => packingStep === 'items' ? (data.packing_package ? setPackingStep('package') : data.packing_items.length ? setPackingStep('bulky') : setShowQuestions(false)) : packingStep === 'package' && data.packing_items.length ? setPackingStep('bulky') : setShowQuestions(false)}>{packingStep === 'items' || (packingStep === 'package' && data.packing_items.length) ? 'Back' : 'Cancel'}</button>}
                    {packingStep === 'items' ? <button type="button" className="slds-button cm-primary" disabled={packingSaving} onClick={() => { if (termsError || (data.item_questions || []).some(q => !q.saved || q.saved.pending || (q.answers.find(a => a.id === q.saved?.answer_id)?.acknowledge && !q.saved.acknowledged))) { setTermsError('Please answer each item and acknowledge the required instructions.'); return; } setShowQuestions(false); }}>Done</button> : packingStep === 'bulky' && data.packing_package ? <button type="button" className="slds-button cm-primary" onClick={() => {
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
