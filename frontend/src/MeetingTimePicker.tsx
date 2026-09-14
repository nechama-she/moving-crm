import { useRef, useState } from 'react';

const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const day = (value: string) => new Date(`${value}T12:00:00`);
const windows = [
  {label:'8 - 10 AM',start:8,end:10}, {label:'10 AM - 12 PM',start:10,end:12},
  {label:'12 - 2 PM',start:12,end:14}, {label:'2 - 4 PM',start:14,end:16},
  {label:'4 - 6 PM',start:16,end:18}, {label:'6 - 8 PM',start:18,end:20},
];
type Selection = {date:string;slot:number};
export default function MeetingTimePicker({ onChange }: { onChange: (value: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const today = key(new Date());
  const [first,setFirst] = useState(today);
  const [draft,setDraft] = useState<Selection>();
  const [selected,setSelected] = useState<Selection>();
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zoneName = new Intl.DateTimeFormat('en-US',{timeZoneName:'long',timeZone:timezone}).formatToParts(day(draft?.date||today)).find(p=>p.type==='timeZoneName')?.value || timezone;
  const dates = Array.from({length:5},(_,i)=>{const d=day(first);d.setDate(d.getDate()+i);return key(d);});
  const future = (value:Selection) => {const d=day(value.date);d.setHours(windows[value.slot].start,0,0,0);return d.getTime()>Date.now();};
  const describe = (value:Selection) => `${day(value.date).toLocaleDateString('en-US',{month:'short',day:'numeric'})}, ${windows[value.slot].label}`;
  function close(){dialog.current?.close();trigger.current?.focus();}
  function apply(){
    if(!draft||!future(draft))return;
    const start=day(draft.date),end=day(draft.date);
    start.setHours(windows[draft.slot].start,0,0,0);end.setHours(windows[draft.slot].end,0,0,0);
    onChange(`${day(draft.date).toLocaleDateString('en-US',{dateStyle:'full'})}, ${windows[draft.slot].label} (${timezone}); ${start.toISOString()} to ${end.toISOString()}`);
    setSelected(draft);close();
  }
  return <div className="cm-slot-picker">
    <label htmlFor="cm-choose-time">When works best for you?</label>
    <button id="cm-choose-time" ref={trigger} type="button" className="cm-slot-trigger" aria-haspopup="dialog" onClick={()=>{setDraft(selected);setFirst(selected?.date && selected.date>=today?selected.date:today);dialog.current?.showModal();}}><span>{selected?describe(selected):'Choose a date & time'}</span><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4M17 3v4M3 11h18"/></svg></button>
    <small>{zoneName}. Our team will confirm your appointment.</small>
    <dialog ref={dialog} className="cm-slot-dialog" aria-labelledby="cm-slot-title" onClick={e=>{if(e.target===dialog.current)close();}}>
      <div className="cm-slot-content">
        <header><div><h3 id="cm-slot-title">Choose your preferred time</h3><p>{zoneName}</p></div><button type="button" aria-label="Close time picker" onClick={close}>&times;</button></header>
        <div className="cm-slot-navigation"><label>Jump to date<input type="date" min={today} value={first} onChange={e=>{if(e.target.value>=today)setFirst(e.target.value);}}/></label><div><button type="button" aria-label="Previous five days" disabled={first<=today} onClick={()=>{const d=day(first);d.setDate(d.getDate()-5);setFirst(key(d)<today?today:key(d));}}>&#8249;</button><button type="button" aria-label="Next five days" onClick={()=>{const d=day(first);d.setDate(d.getDate()+5);setFirst(key(d));}}>&#8250;</button></div></div>
        <div className="cm-slot-days">{dates.map(date=><section key={date}><h4>{day(date).toLocaleDateString('en-US',{weekday:'short'})}<strong>{day(date).toLocaleDateString('en-US',{month:'short',day:'numeric'})}</strong></h4>{windows.map((window,slot)=><button type="button" key={slot} disabled={!future({date,slot})} aria-label={`${date}, ${window.label}`} aria-pressed={draft?.date===date&&draft.slot===slot} onClick={()=>setDraft({date,slot})}>{window.label}</button>)}</section>)}</div>
        <footer><span aria-live="polite">{draft?describe(draft):'Select a time window'}</span><button type="button" onClick={close}>Cancel</button><button type="button" className="cm-primary" disabled={!draft||!future(draft)} onClick={apply}>Apply</button></footer>
      </div>
    </dialog>
  </div>;
}
