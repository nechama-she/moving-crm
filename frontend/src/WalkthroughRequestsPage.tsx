import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import ReportControls, { type ReportOptions } from "./ReportControls";
import { period } from "./reportPeriods";
import "./ReportsPage.css";
import "./MeetingRequests.css";

type Meeting={created_at?:string;id:string;status:string;availability:string;timezone:string;scheduled_at:string|null;assigned_to:string};
type Row={phone:string;pickup:string;delivery:string;move_date:string;lead_id:string;name:string;company:string;company_id:string;requests:Meeting[]};

const STATUS_OPTIONS = [
  { id: 'requested', name: 'Requested' },
  { id: 'scheduled', name: 'Approved' },
  { id: 'completed', name: 'Completed' },
  { id: 'cancelled', name: 'Cancelled' },
];

export default function WalkthroughRequestsPage(){
  const {token}=useAuth();
  const [params]=useSearchParams();
  const currentLead=params.get("lead_id");
  const [rows,setRows]=useState<Row[]>([]),[options,setOptions]=useState<ReportOptions>({companies:[],reps:[],statuses:STATUS_OPTIONS});
  const [error,setError]=useState(''),[loading,setLoading]=useState(true),[search,setSearch]=useState('');
  const [range,setRange]=useState(()=>period('All Time'));
  const [companies,setCompanies]=useState<string[]>([]),[reps,setReps]=useState<string[]>([]),[statuses,setStatuses]=useState<string[]>([]);
  const load=useCallback(async()=>{
    setError('');setLoading(true);
    try {
      const r=await fetch(`${API_BASE}/api/walkthrough-requests`,{headers:authHeaders(token)});
      const d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not load requests');
      setRows(d.items);
      const companyOptions=new Map<string,string>((d.companies||[]).map((c:{id:string;name:string})=>[c.id,c.name]));
      (d.items as Row[]).forEach(row=>companyOptions.set(row.company_id||'__unassigned__',row.company||'Unassigned company'));
      setOptions({companies:Array.from(companyOptions,([id,name])=>({id,name})),reps:[...d.reps,{id:'__unassigned__',name:'Unassigned rep'}],statuses:STATUS_OPTIONS});
    } finally {setLoading(false);}
  },[token]);
  useEffect(()=>{void load().catch(e=>setError(e.message));},[load]);
  const matches=(m:Meeting)=>{
    if(statuses.length&&!statuses.includes(m.status))return false;
    if(reps.length&&!reps.includes(m.assigned_to||'__unassigned__'))return false;
    if(range.label==='All Time')return true;
    const value=m.scheduled_at||m.created_at;if(!value)return false;
    const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
    return date>=range.start&&date<=range.end;
  };
  const visible=rows.filter(row=>(!companies.length||companies.includes(row.company_id||'__unassigned__'))&&row.name.toLowerCase().includes(search.toLowerCase())).map(row=>({...row,requests:row.requests.filter(matches)})).filter(row=>row.requests.length).sort((a,b)=>Number(b.lead_id===currentLead)-Number(a.lead_id===currentLead));
  return <main className="reports-page meeting-requests">
    <header><h1>Meetings Calendar</h1></header>
    <ReportControls range={range} companies={companies} reps={reps} statuses={statuses} options={options} onApply={(next,c,r,s)=>{setRange(next);setCompanies(c);setReps(r);setStatuses(s||[]);}} />
    <section className="reports-results">
      <div className="reports-toolbar"><h2>Meetings</h2><input placeholder="Search customer" aria-label="Search customer" value={search} onChange={e=>setSearch(e.target.value)}/></div>
      {error&&<p className="reports-error" role="alert">{error}</p>}
      {loading&&<p role="status">Loading meetings...</p>}
      {!loading&&!error&&!visible.length&&<p className="reports-empty">No meetings match your selection.</p>}
      <div className="reports-table"><table><thead><tr>{['Customer','Phone','Moving from','Moving to','Move date','Appointment request','Status','Rep'].map((title,i)=><th key={i}>{title}</th>)}</tr></thead><tbody>
        {visible.flatMap(row=>row.requests.map(meeting=><MeetingRow key={meeting.id} meeting={meeting} row={row} reps={options.reps.filter(r=>r.id!=='__unassigned__')} onSave={load}/>))}
      </tbody></table></div>
    </section>
  </main>;
}
function requestDates(meeting:Meeting){return meeting.availability.match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z/g)||[];}
function appointment(meeting:Meeting){
  const dates=requestDates(meeting);
  if(meeting.scheduled_at)return new Date(meeting.scheduled_at).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
  if(dates.length){const start=new Date(dates[0]!);return `${start.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}${dates[1]?' - '+new Date(dates[1]).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}):''}`;}
  return meeting.availability.split(';')[0]||'—';
}

function MeetingRow({meeting,row,reps,onSave}:{meeting:Meeting;row:Row;reps:{id:string;name:string}[];onSave:()=>Promise<void>}){
  const {token}=useAuth();
  const [currentStatus,setCurrentStatus]=useState(meeting.status);
  const [currentRep,setCurrentRep]=useState(meeting.assigned_to||'');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');

  useEffect(()=>{
    setCurrentStatus(meeting.status);
    setCurrentRep(meeting.assigned_to||'');
  },[meeting.status,meeting.assigned_to]);

  async function updateMeeting(patch:{status?:string;assigned_to?:string|null}){
    setBusy(true);
    setError('');
    const targetStatus=patch.status!==undefined?patch.status:currentStatus;
    const targetRep=patch.assigned_to!==undefined?patch.assigned_to:(currentRep||null);

    if(patch.status!==undefined)setCurrentStatus(patch.status);
    if(patch.assigned_to!==undefined)setCurrentRep(patch.assigned_to||'');

    try{
      const payload:Record<string,unknown>={
        status:targetStatus,
        assigned_to:targetRep,
        scheduled_at:meeting.scheduled_at||requestDates(meeting)[0]||null,
      };
      const r=await fetch(`${API_BASE}/api/walkthrough-requests/${meeting.id}`,{
        method:'PATCH',
        headers:{...authHeaders(token),'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
      const d=await r.json();
      if(!r.ok)throw new Error(d.detail||'Could not update meeting');
      await onSave();
    }catch(e){
      setError((e as Error).message);
      setCurrentStatus(meeting.status);
      setCurrentRep(meeting.assigned_to||'');
    }finally{
      setBusy(false);
    }
  }

  return (
    <tr>
      <td><Link to={`/leads/${row.lead_id}`} target="_blank" rel="noopener noreferrer">{row.name}</Link></td>
      <td>{row.phone?<a href={`tel:${row.phone}`}>{row.phone}</a>:'—'}</td>
      <td>{row.pickup||'—'}</td>
      <td>{row.delivery||'—'}</td>
      <td>{row.move_date?new Date(row.move_date.slice(0,10)+'T12:00:00').toLocaleDateString():'—'}</td>
      <td>{appointment(meeting)}</td>
      <td>
        <div className="meeting-status-select-wrap">
          <select
            className={`meeting-status-select status-${currentStatus}`}
            value={currentStatus}
            disabled={busy}
            aria-label="Change meeting status"
            onChange={e=>void updateMeeting({status:e.target.value})}
          >
            <option value="requested">Requested</option>
            <option value="scheduled">Approved</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
          {error&&<span className="meeting-row-inline-error" role="alert">{error}</span>}
        </div>
      </td>
      <td>
        <div className="meeting-rep-select-wrap">
          <select
            className={`meeting-rep-select ${!currentRep?'unassigned':''}`}
            value={currentRep}
            disabled={busy}
            aria-label="Assign sales rep"
            onChange={e=>void updateMeeting({assigned_to:e.target.value||null})}
          >
            <option value="">Unassigned</option>
            {reps.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </div>
      </td>
    </tr>
  );
}
