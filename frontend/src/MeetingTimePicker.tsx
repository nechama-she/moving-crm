import { useEffect, useRef, useState } from 'react';

const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const day = (value: string) => new Date(`${value}T12:00:00`);
const windows = [
  {label:'8 - 10 AM',start:8,end:10}, {label:'10 AM - 12 PM',start:10,end:12},
  {label:'12 - 2 PM',start:12,end:14}, {label:'2 - 4 PM',start:14,end:16},
  {label:'4 - 6 PM',start:16,end:18}, {label:'6 - 8 PM',start:18,end:20},
];
type Selection = {date:string;slot:number};
export default function MeetingTimePicker({ onChange, availabilityUrl, linkKey, session, moveDate }: { onChange: (value: string) => void; availabilityUrl:string; linkKey:string; session:string; moveDate?: string | null }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const moveEnd = moveDate ? new Date(`${moveDate}T23:59:59`) : null;
  const today = key(new Date());
  const [first,setFirst] = useState(today);
  const [slots,setSlots]=useState<Record<string,boolean>>({});
  const [slotError,setSlotError]=useState('');
  useEffect(()=>{
    const controller=new AbortController();
    const entries=Array.from({length:5},(_,i)=>{const d=day(first);d.setDate(d.getDate()+i);return windows.map((w,slot)=>{const start=new Date(d);start.setHours(w.start,0,0,0);return {id:`${key(d)}-${slot}`,start:start.toISOString()};});}).flat();
    async function refresh(){try{
      const r=await fetch(availabilityUrl,{method:'POST',headers:{'Content-Type':'application/json','x-public-link':linkKey,'x-public-session':session},body:JSON.stringify({starts:entries.map(e=>e.start)}),signal:controller.signal});
      if(!r.ok)throw new Error('Could not load available times. Please reopen the picker.');
      const result=await r.json();setSlots(Object.fromEntries(entries.map((e,i)=>[e.id,!!result.available[i]])));setSlotError('');
    }catch(e){if(!controller.signal.aborted){setSlots({});setSlotError((e as Error).message);}}}
    setSlots({});void refresh();const timer=setInterval(()=>void refresh(),15000);
    return ()=>{controller.abort();clearInterval(timer);};
  },[first,availabilityUrl,linkKey,session]);

  const [calendar,setCalendar] = useState(false);
  const [month,setMonth] = useState(()=>day(today));
  const [draft,setDraft] = useState<Selection>();
  const [selected,setSelected] = useState<Selection>();
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zoneName = new Intl.DateTimeFormat('en-US',{timeZoneName:'long',timeZone:timezone}).formatToParts(day(draft?.date||today)).find(p=>p.type==='timeZoneName')?.value || timezone;
  const dates = Array.from({length:5},(_,i)=>{const d=day(first);d.setDate(d.getDate()+i);return key(d);}).filter(date => !moveEnd || day(date).getTime() <= moveEnd.getTime());
  const future = (value:Selection) => {
    const d=day(value.date);d.setHours(windows[value.slot].start,0,0,0);
    const isAfterMoveDate = moveEnd ? d.getTime() > moveEnd.getTime() : false;
    return !isAfterMoveDate && d.getTime()>Date.now() && slots[`${value.date}-${value.slot}`]===true;
  };
  const describe = (value:Selection) => `${day(value.date).toLocaleDateString('en-US',{month:'short',day:'numeric'})}, ${windows[value.slot].label}`;
  function close(){setCalendar(false);dialog.current?.close();trigger.current?.focus();}
  function apply(){
    if(!draft||!future(draft))return;
    const start=day(draft.date),end=day(draft.date);
    start.setHours(windows[draft.slot].start,0,0,0);end.setHours(windows[draft.slot].end,0,0,0);
    onChange(`${day(draft.date).toLocaleDateString('en-US',{dateStyle:'full'})}, ${windows[draft.slot].label} (${timezone}); ${start.toISOString()} to ${end.toISOString()}`);
    setSelected(draft);close();
  }
  return <div className="cm-slot-picker">
    <label htmlFor="cm-choose-time">When works best for you?</label>
    <button id="cm-choose-time" ref={trigger} type="button" className="slds-button cm-slot-trigger" aria-haspopup="dialog" onClick={()=>{setDraft(selected);setFirst(selected?.date && selected.date>=today?selected.date:today);dialog.current?.showModal();}}><span>{selected?describe(selected):'Choose a date & time'}</span><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4M17 3v4M3 11h18"/></svg></button>
    <small>{zoneName}. Our team will confirm your appointment.</small>
    <dialog ref={dialog} className="cm-slot-dialog" aria-labelledby="cm-slot-title" onClick={e=>{if(e.target===dialog.current)close();}}>
      <div className="cm-slot-content">
        <header><div><h3 id="cm-slot-title">Choose your preferred time</h3><p>{zoneName}</p></div><button className="slds-button" type="button" aria-label="Close time picker" onClick={close}>&times;</button></header>
        <div className="cm-slot-navigation"><div className="cm-jump"><button type="button" className="slds-button cm-jump-trigger" aria-expanded={calendar} onClick={()=>{setMonth(day(first));setCalendar(!calendar);}}>{day(first).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}<span aria-hidden="true">&#9662;</span></button>
          {calendar&&<div className="cm-jump-calendar" aria-label="Choose date" onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();setCalendar(false);}}}>
            <div className="cm-jump-heading"><button className="slds-button" type="button" aria-label="Previous month" disabled={month.getFullYear()===day(today).getFullYear()&&month.getMonth()===day(today).getMonth()} onClick={()=>setMonth(new Date(month.getFullYear(),month.getMonth()-1,1))}>&#8249;</button><strong aria-live="polite">{month.toLocaleDateString('en-US',{month:'long',year:'numeric'})}</strong><button className="slds-button" type="button" aria-label="Next month" onClick={()=>setMonth(new Date(month.getFullYear(),month.getMonth()+1,1))}>&#8250;</button></div>
            <div className="cm-jump-grid">{['Su','Mo','Tu','We','Th','Fr','Sa'].map(d=><span key={d}>{d}</span>)}{Array.from({length:new Date(month.getFullYear(),month.getMonth(),1).getDay()},(_,i)=><span key={`blank${i}`}/>)}{Array.from({length:new Date(month.getFullYear(),month.getMonth()+1,0).getDate()},(_,i)=>{const value=key(new Date(month.getFullYear(),month.getMonth(),i+1)); const isAfterMoveDate = moveEnd ? new Date(`${value}T12:00:00`).getTime() > moveEnd.getTime() : false; return <button className="slds-button" type="button" key={value} disabled={value<today || isAfterMoveDate} aria-label={value} aria-pressed={first===value} aria-current={value===today?'date':undefined} onClick={()=>{setFirst(value);setCalendar(false);}}>{i+1}</button>;})}</div>
            <button type="button" className="slds-button cm-jump-today" onClick={()=>{setFirst(today);setCalendar(false);}}>Today</button>
          </div>}
        </div><div><button className="slds-button" type="button" aria-label="Previous five days" disabled={first<=today} onClick={()=>{const d=day(first);d.setDate(d.getDate()-5);setFirst(key(d)<today?today:key(d));}}>&#8249;</button><button className="slds-button" type="button" aria-label="Next five days" onClick={()=>{const d=day(first);d.setDate(d.getDate()+5);setFirst(key(d));}}>&#8250;</button></div></div>
        {slotError&&<p role="alert">{slotError}</p>}<div className="cm-slot-days">{dates.map(date=><section key={date}><h4>{day(date).toLocaleDateString('en-US',{weekday:'short'})}<strong>{day(date).toLocaleDateString('en-US',{month:'short',day:'numeric'})}</strong></h4>{windows.map((window,slot)=><button className="slds-button" type="button" key={slot} disabled={!future({date,slot})} aria-label={`${date}, ${window.label}`} aria-pressed={draft?.date===date&&draft.slot===slot} onClick={()=>setDraft({date,slot})} title={slots[`${date}-${slot}`]===false?"Unavailable":undefined}>{window.label}</button>)}</section>)}</div>
        <footer><span aria-live="polite">{draft?describe(draft):'Select a time window'}</span><button className="slds-button" type="button" onClick={close}>Cancel</button><button type="button" className="slds-button cm-primary" disabled={!draft||!future(draft)} onClick={apply}>Apply</button></footer>
      </div>
    </dialog>
  </div>;
}
