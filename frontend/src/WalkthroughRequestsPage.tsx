import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import CustomerPageControls from "./CustomerPageControls";
import ReportControls, { type ReportOptions } from "./ReportControls";
import { period } from "./reportPeriods";
import "./ReportsPage.css";

type Meeting={created_at?:string;id:string;status:string;availability:string;timezone:string;scheduled_at:string|null;assigned_to:string};
type Row={lead_id:string;name:string;company:string;company_id:string;requests:Meeting[]};
export default function WalkthroughRequestsPage(){
  const {token}=useAuth();
  const [rows,setRows]=useState<Row[]>([]),[options,setOptions]=useState<ReportOptions>({companies:[],reps:[]});
  const [error,setError]=useState(''),[loading,setLoading]=useState(true),[filter,setFilter]=useState('requested'),[search,setSearch]=useState(''),[active,setActive]=useState('');
  const [range,setRange]=useState(()=>period('All Time'));
  const [companies,setCompanies]=useState<string[]>([]),[reps,setReps]=useState<string[]>([]);
  const load=useCallback(async()=>{
    setError('');setLoading(true);
    try {
      const r=await fetch(`${API_BASE}/api/walkthrough-requests`,{headers:authHeaders(token)});
      const d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not load requests');
      setRows(d.items);
      const companyOptions=new Map<string,string>((d.companies||[]).map((c:{id:string;name:string})=>[c.id,c.name]));
      (d.items as Row[]).forEach(row=>companyOptions.set(row.company_id||'__unassigned__',row.company||'Unassigned company'));
      setOptions({companies:Array.from(companyOptions,([id,name])=>({id,name})),reps:[...d.reps,{id:'__unassigned__',name:'Unassigned rep'}]});
    } finally {setLoading(false);}
  },[token]);
  useEffect(()=>{void load().catch(e=>setError(e.message));},[load]);
  const matches=(m:Meeting)=>{
    if(filter!=='all'&&filter!=='unassigned'&&m.status!==filter)return false;
    if(reps.length&&!reps.includes(m.assigned_to||'__unassigned__'))return false;
    if(range.label==='All Time')return true;
    const value=m.scheduled_at||m.created_at;if(!value)return false;
    const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
    return date>=range.start&&date<=range.end;
  };
  const visible=rows.filter(row=>(!companies.length||companies.includes(row.company_id||'__unassigned__'))&&row.name.toLowerCase().includes(search.toLowerCase())&&(filter!=='unassigned'||!row.company_id)).map(row=>({...row,requests:row.requests.filter(matches)})).filter(row=>row.requests.length||(filter==='unassigned'&&range.label==='All Time'&&!reps.length));
  return <main className="reports-page">
    <header><h1>Schedule Meetings</h1></header>
    <ReportControls range={range} companies={companies} reps={reps} options={options} onApply={(next,c,r)=>{setRange(next);setCompanies(c);setReps(r);}} />
    <section className="reports-results">
      <div className="reports-toolbar"><h2>Meeting requests</h2><input placeholder="Search customer" aria-label="Search customer" value={search} onChange={e=>setSearch(e.target.value)}/><select aria-label="Request status" value={filter} onChange={e=>setFilter(e.target.value)}>{[['requested','Requested'],['scheduled','Scheduled'],['completed','Completed'],['cancelled','Cancelled'],['all','All statuses'],['unassigned','Unassigned company']].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select><button disabled={loading} onClick={()=>void load().catch(e=>setError(e.message))}>Refresh</button></div>
      {error&&<p className="reports-error" role="alert">{error}</p>}
      {loading&&<p role="status">Loading meetings...</p>}
      {!loading&&!error&&!visible.length&&<p className="reports-empty">No meetings match your selection.</p>}
      {visible.map(row=><section key={row.lead_id} style={{padding:20,borderTop:'1px solid #d8dde6'}}><div style={{display:'flex',justifyContent:'space-between',gap:12,flexWrap:'wrap'}}><div><Link to={`/leads/${row.lead_id}`} target="_blank" rel="noopener noreferrer"><strong>{row.name}</strong></Link><p>{row.company||'Unassigned company'}</p></div><button onClick={()=>setActive(active===row.lead_id?'':row.lead_id)}>Manage customer page / company</button></div>{active===row.lead_id&&<CustomerPageControls leadId={row.lead_id}/>} {row.requests.map(m=><Schedule key={`${m.id}-${m.status}-${m.scheduled_at}-${m.assigned_to}`} meeting={m} reps={options.reps.filter(r=>r.id!=='__unassigned__')} onSave={load}/>)}</section>)}
    </section>
  </main>;
}
function Schedule({meeting,reps,onSave}:{meeting:Meeting;reps:{id:string;name:string}[];onSave:()=>Promise<void>}){const {token}=useAuth();const [rep,setRep]=useState(meeting.assigned_to),[date,setDate]=useState(()=>{if(!meeting.scheduled_at)return '';const d=new Date(meeting.scheduled_at);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}),[status,setStatus]=useState(meeting.status),[busy,setBusy]=useState(false),[error,setError]=useState('');async function save(){setBusy(true);setError('');try{const r=await fetch(`${API_BASE}/api/walkthrough-requests/${meeting.id}`,{method:'PATCH',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify({status,assigned_to:rep||null,scheduled_at:date?new Date(date).toISOString():null})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not schedule');await onSave();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}return <div style={{borderTop:'1px solid #eee',paddingTop:12}}><p>Customer availability: {meeting.availability} ({meeting.timezone})</p><div style={{display:'flex',gap:12,flexWrap:'wrap'}}><select aria-label="Assigned rep" value={rep} onChange={e=>setRep(e.target.value)}><option value="">Choose rep</option>{reps.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select><label>Appointment (your local time)<input type="datetime-local" value={date} onChange={e=>setDate(e.target.value)}/></label><select aria-label="Status" value={status} onChange={e=>setStatus(e.target.value)}>{['requested','scheduled','completed','cancelled'].map(s=><option key={s}>{s}</option>)}</select><button disabled={busy} onClick={()=>void save()}>Save</button></div>{error&&<p role="alert">{error}</p>}</div>;}
