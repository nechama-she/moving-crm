import { useEffect, useRef, useState } from "react";
export type ReportRange = { start: string; end: string; label: string };
export type ReportOptions = { companies: { id: string; name: string }[]; reps: { id: string; name: string }[] };
import { iso, day, now, period } from "./reportPeriods";
export default function ReportControls({ range, companies, reps, options, onApply }: { range: ReportRange; companies: string[]; reps: string[]; options: ReportOptions; onApply: (range: ReportRange, companies: string[], reps: string[]) => void }) {
  const [open,setOpen]=useState<"dates"|"filters"|null>(null);
  const [draft,setDraft]=useState(range);
  const [month,setMonth]=useState(()=>day(range.start));
  const [anchor,setAnchor]=useState<string|null>(null);
  const [draftCompanies,setDraftCompanies]=useState(companies), [draftReps,setDraftReps]=useState(reps);
  const wrapper=useRef<HTMLDivElement>(null);
  useEffect(()=>{ const close=(event:PointerEvent)=>{if (!wrapper.current?.contains(event.target as Node)) setOpen(null);}; document.addEventListener("pointerdown",close); return ()=>document.removeEventListener("pointerdown",close);},[]);
  const y=month.getFullYear(), m=month.getMonth(), offset=new Date(y,m,1).getDay(), count=new Date(y,m+1,0).getDate();
  const toggle=(values:string[], id:string)=>values.includes(id)?values.filter(v=>v!==id):[...values,id];
  return <div className="report-controls" ref={wrapper} onKeyDown={e=>{if(e.key==="Escape") {setOpen(null); (wrapper.current?.querySelector('button') as HTMLButtonElement)?.focus();}}}>
    <button type="button" aria-expanded={open==="dates"} onClick={()=>{setDraft(range);setAnchor(null);setMonth(range.label==="All Time"?now():day(range.start));setOpen(open==="dates"?null:"dates");}}>&#128197; {range.label}</button>
    <button type="button" aria-expanded={open==="filters"} onClick={()=>{setDraftCompanies(companies);setDraftReps(reps);setOpen(open==="filters"?null:"filters");}}>Filters{companies.length+reps.length ? ` (${companies.length+reps.length})` : ""}</button>
    <span className="report-scope">{companies.length ? `${companies.length} companies` : "All companies"} · {reps.length ? `${reps.length} reps` : "All reps"}</span>
    {open==="dates" && <div className="report-calendar" role="dialog" aria-label="Choose signup date range">
      <div className="report-presets">{["Today","Yesterday","This Week","Last Week","This Month","Last Month","Last 30 Days","This Quarter","This Year","Last Year","All Time"].map(label=><button type="button" key={label} className={draft.label===label?"selected":""} onClick={()=>{const next=period(label);setDraft(next);setMonth(label==="All Time"?now():day(next.start));setAnchor(null);}}>{label}</button>)}</div>
      <div className="report-calendar-main"><div className="report-month-nav"><button type="button" aria-label="Previous month" onClick={()=>setMonth(new Date(y,m-1,1))}>&lsaquo;</button><label className="report-month-label"><span className="sr-only">Calendar month</span><input aria-label="Calendar month" type="month" value={`${y}-${String(m+1).padStart(2,"0")}`} onChange={e=>{if(e.target.value) setMonth(day(`${e.target.value}-01`));}} /></label><button type="button" aria-label="Next month" onClick={()=>setMonth(new Date(y,m+1,1))}>&rsaquo;</button></div>
      <div className="report-calendar-grid">{["S","M","T","W","T","F","S"].map((v,i)=><span key={`w${i}`}>{v}</span>)}{Array.from({length:offset},(_,i)=><span key={`e${i}`}/>)}{Array.from({length:count},(_,i)=>{const value=iso(new Date(y,m,i+1));return <button type="button" key={value} aria-label={value} aria-pressed={value>=draft.start&&value<=draft.end} className={`${value>=draft.start&&value<=draft.end?"in-range":""} ${value===draft.start||value===draft.end?"endpoint":""}`} onClick={()=>{if(!anchor){setAnchor(value);setDraft({start:value,end:value,label:"Custom range"});}else {setDraft({start:anchor<value?anchor:value,end:anchor<value?value:anchor,label:"Custom range"});setAnchor(null);}}}>{i+1}</button>;})}</div>
      <p className="report-calendar-hint">{anchor?"Choose the last day, or Apply for one day.":"Choose a period or click a first and last day."}</p><div className="report-calendar-footer"><small>{draft.label==="All Time"?"All signup dates":`${draft.start} – ${draft.end}`}</small><button type="button" className="reports-primary" onClick={()=>{onApply(draft,companies,reps);setOpen(null);}}>Apply</button></div></div>
    </div>}
    {open==="filters" && <aside className="report-filter-panel" role="dialog" aria-label="Report filters"><header><strong>Filters</strong><button type="button" aria-label="Close filters" onClick={()=>setOpen(null)}>&times;</button></header>
      {([['Companies',options.companies,draftCompanies,setDraftCompanies],['Reps',options.reps,draftReps,setDraftReps]] as const).map(([title,values,selected,setSelected])=><fieldset key={title}><legend>{title}</legend><button type="button" onClick={()=>setSelected([])}>All {title.toLowerCase()}</button><div className="report-filter-options">{values.map(option=><label key={option.id}><input type="checkbox" checked={selected.includes(option.id)} onChange={()=>setSelected(toggle(selected,option.id))}/>{option.name}</label>)}{!values.length&&<small>Options will appear when the report loads.</small>}</div></fieldset>)}
      <footer><button type="button" onClick={()=>{setDraftCompanies([]);setDraftReps([]);}}>Reset</button><button type="button" className="reports-primary" onClick={()=>{onApply(range,draftCompanies,draftReps);setOpen(null);}}>Apply filters</button></footer></aside>}
  </div>;
}
