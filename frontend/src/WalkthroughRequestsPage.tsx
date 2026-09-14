import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import ReportControls, { type ReportOptions } from "./ReportControls";
import { period } from "./reportPeriods";
import "./ReportsPage.css";
import "./MeetingRequests.css";

type Meeting={created_at?:string;id:string;status:string;availability:string;timezone:string;scheduled_at:string|null;assigned_to:string};
type Row={phone:string;pickup:string;delivery:string;move_date:string;lead_id:string;name:string;company:string;company_id:string;requests:Meeting[]};
export default function WalkthroughRequestsPage(){
  const {token}=useAuth();
  const [rows,setRows]=useState<Row[]>([]),[options,setOptions]=useState<ReportOptions>({companies:[],reps:[]});
  const [error,setError]=useState(''),[loading,setLoading]=useState(true),[filter,setFilter]=useState('requested'),[search,setSearch]=useState('');
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
  return <main className="reports-page meeting-requests">
    <header><h1>Schedule Meetings</h1></header>
    <ReportControls range={range} companies={companies} reps={reps} options={options} onApply={(next,c,r)=>{setRange(next);setCompanies(c);setReps(r);}} />
    <section className="reports-results">
      <div className="reports-toolbar"><h2>Meeting requests</h2><input placeholder="Search customer" aria-label="Search customer" value={search} onChange={e=>setSearch(e.target.value)}/><select aria-label="Request status" value={filter} onChange={e=>setFilter(e.target.value)}>{[['requested','Requested'],['scheduled','Approved'],['completed','Completed'],['cancelled','Cancelled'],['all','All statuses'],['unassigned','Unassigned company']].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select><button disabled={loading} onClick={()=>void load().catch(e=>setError(e.message))}>Refresh</button></div>
      {error&&<p className="reports-error" role="alert">{error}</p>}
      {loading&&<p role="status">Loading meetings...</p>}
      {!loading&&!error&&!visible.length&&<p className="reports-empty">No meetings match your selection.</p>}
      <div className="reports-table"><table><thead><tr>{['Customer','Phone','Moving from','Moving to','Move date','Appointment request','Status',''].map((title,i)=><th key={i}>{title}</th>)}</tr></thead><tbody>
        {visible.flatMap(row=>row.requests.map(meeting=><tr key={meeting.id}>
          <td><Link to={`/leads/${row.lead_id}`} target="_blank" rel="noopener noreferrer">{row.name}</Link></td>
          <td>{row.phone?<a href={`tel:${row.phone}`}>{row.phone}</a>:'?'}</td><td>{row.pickup||'?'}</td><td>{row.delivery||'?'}</td>
          <td>{row.move_date?new Date(row.move_date.slice(0,10)+'T12:00:00').toLocaleDateString():'?'}</td>
          <td>{appointment(meeting)}</td><td><span className={`reports-badge ${meeting.status==='scheduled'?'booked':''}`}>{({requested:'Requested',scheduled:'Approved',completed:'Completed',cancelled:'Cancelled'} as Record<string,string>)[meeting.status]}</span></td>
          <td><Schedule meeting={meeting} reps={options.reps.filter(r=>r.id!=='__unassigned__')} onSave={load}/></td>
        </tr>))}
      </tbody></table></div>
    </section>
  </main>;
}
function requestDates(meeting:Meeting){return meeting.availability.match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z/g)||[];}
function appointment(meeting:Meeting){
  const dates=requestDates(meeting);
  if(meeting.scheduled_at)return new Date(meeting.scheduled_at).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
  if(dates.length){const start=new Date(dates[0]!);return `${start.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}${dates[1]?' - '+new Date(dates[1]).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}):''}`;}
  return meeting.availability.split(';')[0]||'?';
}
function Schedule({meeting,reps,onSave}:{meeting:Meeting;reps:{id:string;name:string}[];onSave:()=>Promise<void>}){
  const {token}=useAuth();const [rep,setRep]=useState(meeting.assigned_to||''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function save(status:string){setBusy(true);setError('');try{
    const r=await fetch(`${API_BASE}/api/walkthrough-requests/${meeting.id}`,{method:'PATCH',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify({status,assigned_to:rep||null,scheduled_at:meeting.scheduled_at||requestDates(meeting)[0]||null})});
    const d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not update meeting');await onSave();
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <details className="meeting-row-actions"><summary>Manage</summary><div><label>Rep<select value={rep} onChange={e=>setRep(e.target.value)}><option value="">Select rep</option>{reps.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
    {meeting.status==='requested'&&<button disabled={busy||!rep||!requestDates(meeting).length} onClick={()=>void save('scheduled')}>Approve</button>}
    {meeting.status==='scheduled'&&<button disabled={busy} onClick={()=>void save('completed')}>Mark completed</button>}
    {['requested','scheduled'].includes(meeting.status)&&<button disabled={busy} onClick={()=>void save('cancelled')}>Cancel meeting</button>}
    {error&&<p role="alert">{error}</p>}</div></details>;
}
