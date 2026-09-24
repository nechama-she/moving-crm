import { useEffect, useRef, useState } from 'react';
import './DeliveryDateCalendar.css';
export const dateKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const day = (iso: string) => new Date(`${iso}T12:00:00`);
export function storagePeriods(pickup: string, selected: string, freeDays: number, periodDays: number) {
  const utc = (iso: string) => { const [y,m,d] = iso.split('-').map(Number); return Date.UTC(y,m-1,d); };
  const elapsed = Math.round((utc(selected)-utc(pickup))/86400000);
  return { elapsed, periods: Math.ceil(Math.max(0, elapsed-freeDays)/periodDays) };
}
export default function DeliveryDateCalendar({ value, minDate, freeDays, onChange }: {
  value: string; minDate: string; freeDays: number; onChange: (date: string) => void;
}) {
  const today = dateKey(new Date());
  const initial = value || (minDate > today ? minDate : today);
  const [month, setMonth] = useState(() => day(initial));
  const [focusDate, setFocusDate] = useState('');
  const calendar = useRef<HTMLDivElement>(null);
  useEffect(() => { if (focusDate) calendar.current?.querySelector<HTMLButtonElement>(`[data-date="${focusDate}"]`)?.focus(); }, [focusDate, month]);
  const year = month.getFullYear(), monthIndex = month.getMonth();
  const offset = new Date(year,monthIndex,1).getDay();
  const count = new Date(year,monthIndex+1,0).getDate();
  const freeEnd = day(minDate); freeEnd.setDate(freeEnd.getDate()+freeDays);
  const cutoff = dateKey(freeEnd);
  const label = (iso: string) => day(iso).toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric',year:'numeric'});
  return <div className="delivery-calendar" ref={calendar}>
    <div className="delivery-calendar-selection"><small>EARLIEST DELIVERY DATE</small><strong>{value ? label(value) : 'Choose a day below'}</strong></div>
    <div className="delivery-calendar-nav">
      <button type="button" aria-label="Previous month" disabled={dateKey(new Date(year,monthIndex,1)) <= minDate.slice(0,7)+'-01'} onClick={() => setMonth(new Date(year,monthIndex-1,1,12))}>‹</button>
      <strong aria-live="polite">{month.toLocaleDateString('en-US',{month:'long',year:'numeric'})}</strong>
      <button type="button" aria-label="Next month" onClick={() => setMonth(new Date(year,monthIndex+1,1,12))}>›</button>
    </div>
    <div className="delivery-calendar-grid" role="group" aria-label="Choose earliest delivery date">
      {['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(name => <span className="delivery-calendar-weekday" key={name}>{name}</span>)}
      {Array.from({length:offset},(_,i)=><span key={`blank-${i}`} />)}
      {Array.from({length:count},(_,i)=>{
        const iso=dateKey(new Date(year,monthIndex,i+1,12)), disabled=iso<minDate, free=iso<=cutoff && !disabled;
        return <button type="button" key={iso} data-date={iso} disabled={disabled} aria-label={`${label(iso)}${free ? ', within free storage period' : ''}`} aria-pressed={iso===value} aria-current={iso===today ? 'date' : undefined}
          className={`${iso===value ? 'selected' : ''} ${free ? 'free' : ''}`} onClick={()=>onChange(iso)}
          onKeyDown={e=>{const delta=({ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7} as Record<string,number>)[e.key];if(delta){e.preventDefault();const next=day(iso);next.setDate(next.getDate()+delta);const key=dateKey(next);if(key>=minDate){setMonth(new Date(next.getFullYear(),next.getMonth(),1,12));setFocusDate(key);}}}}>{i+1}</button>;
      })}
    </div>
    <p className="delivery-calendar-legend"><span /> Free storage through {freeEnd.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}</p>
    <small>This is your earliest available date, not a confirmed delivery appointment.</small>
  </div>;
}
