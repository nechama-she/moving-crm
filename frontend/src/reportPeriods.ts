import type { ReportRange } from "./ReportControls";
export const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
export const day = (s: string) => new Date(`${s}T12:00:00`);
export const now = () => day(new Intl.DateTimeFormat("en-CA", { timeZone:"America/New_York", year:"numeric", month:"2-digit", day:"2-digit" }).format(new Date()));
export function period(label: string): ReportRange {
  const t = now(), y=t.getFullYear(), m=t.getMonth(); let a=t, b=t;
  if (label === "Yesterday") a=b=new Date(y,m,t.getDate()-1);
  if (label === "This Week") { a=new Date(y,m,t.getDate()-t.getDay()); b=new Date(a.getFullYear(),a.getMonth(),a.getDate()+6); }
  if (label === "Last Week") { a=new Date(y,m,t.getDate()-t.getDay()-7); b=new Date(a.getFullYear(),a.getMonth(),a.getDate()+6); }
  if (label === "This Month") { a=new Date(y,m,1); b=new Date(y,m+1,0); }
  if (label === "Last Month") { a=new Date(y,m-1,1); b=new Date(y,m,0); }
  if (label === "Last 30 Days") a=new Date(y,m,t.getDate()-29);
  if (label === "This Quarter") { a=new Date(y,Math.floor(m/3)*3,1); b=new Date(y,Math.floor(m/3)*3+3,0); }
  if (label === "This Year") { a=new Date(y,0,1); b=new Date(y,11,31); }
  if (label === "Last Year") { a=new Date(y-1,0,1); b=new Date(y-1,11,31); }
  if (label === "All Time") { a=new Date(1900,0,1); b=new Date(9999,11,31); }
  return {start:iso(a),end:iso(b),label};
}
