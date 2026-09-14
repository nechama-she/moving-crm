import { useEffect, useState } from 'react';

const dateKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
export default function MeetingTimePicker({ onChange }: { onChange: (value: string) => void }) {
  const [month, setMonth] = useState(() => new Date());
  const [date, setDate] = useState('');
  const [time, setTime] = useState('');
  const today = dateKey(new Date());
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const year = month.getFullYear(), index = month.getMonth();
  const selected = date && time ? new Date(`${date}T${time}:00`) : null;
  const valid = selected !== null && selected.getTime() > Date.now();
  useEffect(() => {
    if (!date || !time) { onChange(''); return; }
    const value = new Date(`${date}T${time}:00`);
    onChange(value.getTime() > Date.now() ? `${value.toLocaleString('en-US',{dateStyle:'full',timeStyle:'short'})} (${timezone}); ${value.toISOString()}` : '');
  }, [date, time, timezone, onChange]);
  return <div className="cm-meeting-picker">
    <h3>Choose your preferred date and time</h3>
    <div className="cm-date-calendar">
      <div className="cm-date-heading"><button type="button" aria-label="Previous month" disabled={year === new Date().getFullYear() && index === new Date().getMonth()} onClick={() => setMonth(new Date(year,index-1,1))}>â€¹</button><strong aria-live="polite">{month.toLocaleDateString('en-US',{month:'long',year:'numeric'})}</strong><button type="button" aria-label="Next month" onClick={() => setMonth(new Date(year,index+1,1))}>â€º</button></div>
      <div className="cm-date-grid">
        {['Su','Mo','Tu','We','Th','Fr','Sa'].map(day => <span key={day}>{day}</span>)}
        {Array.from({length:new Date(year,index,1).getDay()},(_,i)=><span key={`blank-${i}`}/>)}
        {Array.from({length:new Date(year,index+1,0).getDate()},(_,i)=>{
          const value=dateKey(new Date(year,index,i+1));
          return <button type="button" key={value} disabled={value<today} aria-label={new Date(year,index,i+1).toLocaleDateString('en-US',{dateStyle:'full'})} aria-pressed={date===value} aria-current={value===today?'date':undefined} onClick={()=>setDate(value)}>{i+1}</button>;
        })}
      </div>
      <label className="cm-time-label">Preferred time<select aria-label="Preferred time" value={time} onChange={e=>setTime(e.target.value)} required><option value="">Select a time</option>{Array.from({length:48},(_,i)=>{
        const value=`${String(Math.floor(i/2)).padStart(2,'0')}:${i%2?'30':'00'}`;
        const d=new Date(`${date||today}T${value}:00`);
        return <option key={value} value={value} disabled={!!date&&d.getTime()<=Date.now()}>{d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'})}</option>;
      })}</select></label>
      <small>Times are shown in {timezone.split('_').join(' ')}.</small>
    </div>
    <p aria-live="polite">{valid ? `${selected!.toLocaleString('en-US',{dateStyle:'medium',timeStyle:'short'})} â€” our team will confirm your appointment.` : 'Select a future date and time. Our team will confirm availability.'}</p>
  </div>;
}

