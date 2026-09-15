import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import "./LocalPricing.css";

type Settings = { minimum_hours: number | null; capacity_per_mover: number | null; full_pack_hourly: number | null; hourly_rates: (number | null)[]; crew_thresholds: (number | null)[]; truck_thresholds: (number | null)[] };
type Job = { leadId: string; jobId: string; name: string; order: number; volume: number | null; pickup: string; delivery: string; moveType: string };
type Quote = { recommended_crew: number; crew_size: number; trucks: number; capacity: number; estimated_hours: number; billable_hours: number; hourly_rate: number | null; full_pack_hourly: number; minimum_applied: boolean; total: number | null; warning: string; charges: { name: string; description: string; subtotal: number; discountAmount: number; totalCost: number }[] };
const blankSettings = (): Settings => ({ minimum_hours: null, capacity_per_mover: null, full_pack_hourly: null, hourly_rates: Array(10).fill(null), crew_thresholds: Array(9).fill(null), truck_thresholds: Array(9).fill(null) });
const numeric = (value: unknown): number | null => value == null || value === "" ? null : Number(value);
const normalize = (data: Settings): Settings => ({ minimum_hours: numeric(data.minimum_hours), capacity_per_mover: numeric(data.capacity_per_mover), full_pack_hourly: numeric(data.full_pack_hourly), hourly_rates: data.hourly_rates.map(numeric), crew_thresholds: data.crew_thresholds.map(numeric), truck_thresholds: data.truck_thresholds.map(numeric) });
const money = (value: unknown) => value == null ? "?" : Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" });
const number = (value: unknown) => Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 });
async function failure(response: Response) {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((row: { msg: string }) => row.msg).join("; ") : "Could not complete the request. Please retry.";
}

export default function LocalPricing({ planId, companyName, bookName, job }: { planId: string; companyName: string; bookName: string; job?: Job }) {
  const { token, user } = useAuth();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings>(blankSettings);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [volume, setVolume] = useState(job?.volume == null ? "" : String(job.volume));
  const [crew, setCrew] = useState("");
  const [hours, setHours] = useState("");
  const [fullPack, setFullPack] = useState(false);
  const [result, setResult] = useState<{ key: string; quote: Quote } | null>(null);
  const savingRef = useRef(false);
  const base = `${API_BASE}/api/pricing/local/${encodeURIComponent(planId)}`;
  const requestKey = JSON.stringify([planId, settings, volume, crew, hours, fullPack]);
  const quote = result?.key === requestKey ? result.quote : null;
  const active = editing ? draft : settings;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setNotice(""); setSettings(null); setEditing(false);
    void fetch(base, { headers: authHeaders(token), signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(await failure(response));
      return response.json();
    }).then(data => { const value = data.settings ? normalize(data.settings) : null; setSettings(value); setDraft(value || blankSettings()); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [base, token]);

  useEffect(() => {
    if (!settings || editing || !(Number(volume) > 0) || (hours !== "" && !(Number(hours) > 0))) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void fetch(`${base}/calculate`, { method: "POST", headers: { ...authHeaders(token), "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ cubic_feet: Number(volume), crew_size: crew ? Number(crew) : null, hours: hours ? Number(hours) : null, full_pack: fullPack }) })
        .then(async response => { if (!response.ok) throw new Error(await failure(response)); return response.json(); })
        .then(data => { setResult({ key: requestKey, quote: data }); setError(""); })
        .catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [base, token, settings, editing, volume, crew, hours, fullPack, requestKey]);

  function patch(field: keyof Settings, value: number | null, index?: number) {
    setDraft(current => index == null ? { ...current, [field]: value } : { ...current, [field]: (current[field] as (number | null)[]).map((item, i) => i === index ? value : item) });
  }
  async function saveSettings(event: React.FormEvent) {
    event.preventDefault();
    if (savingRef.current) return;
    savingRef.current = true; setSaving(true); setError(""); setNotice("");
    try {
      const response = await fetch(base, { method: "PUT", headers: { ...authHeaders(token), "Content-Type": "application/json" }, body: JSON.stringify(draft) });
      if (!response.ok) throw new Error(await failure(response));
      const data = await response.json(); setSettings(normalize(data.settings)); setDraft(normalize(data.settings)); setEditing(false); setNotice("Local settings saved for this pricing book.");
    } catch (reason) { setError((reason as Error).message); }
    finally { savingRef.current = false; setSaving(false); }
  }
  async function savePrice() {
    if (!job || !quote || Number(quote.total) <= 0 || quote.total == null || savingRef.current || job.moveType !== "Local") return;
    savingRef.current = true; setSaving(true); setError(""); setNotice("");
    try {
      const response = await fetch(`${API_BASE}/api/leads/${encodeURIComponent(job.leadId)}/jobs/${encodeURIComponent(job.jobId)}/price`, {
        method: "PUT", headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({ price: quote.total, estimatedCharges: quote.charges.filter(line => Number(line.totalCost) !== 0).map((line, sortOrder) => ({ ...line, sortOrder })) }),
      });
      if (!response.ok) throw new Error(await failure(response));
      setNotice(`Saved ${money(quote.total)} to Job ${job.order}.`);
    } catch (reason) { setError((reason as Error).message); }
    finally { savingRef.current = false; setSaving(false); }
  }
  function settingInput(field: keyof Settings, label: string, index?: number, required = true) {
    const value = index == null ? draft[field] as number | null : (draft[field] as (number | null)[])[index];
    return <input aria-label={label} type="number" min={field === "hourly_rates" || field === "minimum_hours" || field === "capacity_per_mover" ? "0.01" : "0"} step={field.includes("thresholds") ? "1" : "0.01"} required={required} value={value ?? ""} placeholder="Not set" onChange={event => patch(field, numeric(event.target.value), index)} />;
  }
  if (loading) return <section className="pricing-card" role="status">Loading local pricing?</section>;
  return <div className="local-pricing">
    {job && <section className="pricing-card pricing-job-context"><div><span className="eyebrow">Pricing Job {job.order}</span><h2>{job.name}</h2><p>{job.pickup} → {job.delivery}</p></div><Link to={`/leads/${job.leadId}?job_id=${encodeURIComponent(job.jobId)}`}>Back to lead</Link></section>}
    <section className="pricing-card local-intro"><div><span className="eyebrow">{companyName} — {bookName}</span><h2>Local moving</h2><p>Same-state moves. One hourly rate for every day of the week.</p></div><span className="local-badge">Hourly pricing</span></section>
    {error && <div className="pricing-alert error" role="alert">{error}</div>}
    {notice && <div className="pricing-alert success" role="status">{notice}</div>}
    {!editing && settings && <section className="pricing-card local-calculator">
      <span className="eyebrow">Build an estimate</span><h2>How much are we moving?</h2>
      <div className="local-fields">
        <label>Volume (cubic feet)<input type="number" min="1" value={volume} placeholder="e.g. 1,000" onChange={e => { setVolume(e.target.value); setNotice(""); }} /></label>
        <label>Movers<select value={crew} onChange={e => { setCrew(e.target.value); setNotice(""); }}><option value="">Automatic from volume</option>{Array.from({ length: 10 }, (_, i) => <option key={i} value={i + 1}>{i + 1} {i ? "movers" : "mover"}</option>)}</select></label>
        <label>Hours override (optional)<input type="number" min="0.01" step="0.01" placeholder="Automatic from volume" value={hours} onChange={e => { setHours(e.target.value); setNotice(""); }} /></label>
      </div>
      <label className="local-pack"><input type="checkbox" checked={fullPack} onChange={e => { setFullPack(e.target.checked); setNotice(""); }} /><span><strong>Add full packing</strong><small>One additional {money(settings.full_pack_hourly)} per billable hour for the whole crew.</small></span><b>+{money(settings.full_pack_hourly)}/hr</b></label>
      {quote ? <>
        <div className="local-metrics"><div><span>Movers</span><strong>{quote.crew_size}</strong><small>{quote.recommended_crew} recommended</small></div><div><span>Trucks</span><strong>{quote.trucks}</strong><small>Based on volume</small></div><div><span>Billable hours</span><strong>{number(quote.billable_hours)}</strong><small>{quote.minimum_applied ? `${settings.minimum_hours}-hour minimum applied` : `${number(quote.capacity)} cf per hour`}</small></div><div><span>Hourly rate</span><strong>{quote.hourly_rate == null ? "Not set" : money(Number(quote.hourly_rate) + Number(quote.full_pack_hourly))}</strong><small>{fullPack ? "Including full packing" : "Moving crew"}</small></div></div>
        {quote.warning && <p role="status" className="local-warning">{quote.warning}</p>}
        {quote.total != null && <div className="local-total"><div>{quote.charges.map(line => <div className="local-charge" key={line.name}><span><strong>{line.name}</strong><small>{line.description}</small></span><b>{money(line.totalCost)}</b></div>)}<div className="local-total-bottom"><strong>Estimated total</strong><b>{money(quote.total)}</b></div></div>
          {job && <button className="slds-button primary" disabled={saving || Number(quote.total) <= 0 || job.moveType !== "Local"} onClick={() => void savePrice()}>{saving ? "Saving?" : "Save price"}</button>}
        </div>}
      </> : <p className="local-hint" role="status">{Number(volume) > 0 ? "Calculating estimate?" : "Enter the move volume to calculate crew, trucks, hours, and price."}</p>}
      {job && job.moveType !== "Local" && <p className="local-warning">{job.moveType === "Long Distance" ? "This job crosses state lines. Use Long Distance pricing for this job." : "Confirm pickup and delivery addresses in the same state before saving local pricing."}</p>}
      <p className="local-hint">Estimated hours = cubic feet ÷ (movers × {settings.capacity_per_mover} cf/hour). Billable hours are at least {settings.minimum_hours}. Trucks are a planning count; no separate truck fee is included.</p>
    </section>}
    <form className="pricing-card local-settings" onSubmit={saveSettings}>
      <div className="local-section-heading"><div><span className="eyebrow">Rate settings</span><h2>A simple table. Every day.</h2></div>{user?.role === "admin" && !editing && <button type="button" className="slds-button" onClick={() => { setDraft(settings ? structuredClone(settings) : blankSettings()); setEditing(true); setNotice(""); }}>Edit local settings</button>}</div>
      {!settings && !editing && <p className="local-warning">Local rates have not been set for this book. Add values in Edit local settings to start quoting.</p>}
      <fieldset disabled={saving}>
        <div className="local-setting-basics">
          <label>Minimum billable hours{editing ? settingInput("minimum_hours", "Minimum billable hours") : <strong>{settings?.minimum_hours ?? "Not set"}</strong>}</label>
          <label>Cubic feet per mover / hour{editing ? settingInput("capacity_per_mover", "Cubic feet per mover per hour") : <strong>{settings?.capacity_per_mover ?? "Not set"}</strong>}</label>
          <label>Full packing / hour{editing ? settingInput("full_pack_hourly", "Full packing per hour") : <strong>{money(settings?.full_pack_hourly)}</strong>}</label>
        </div>
        <div className="local-table-scroll"><table className="local-rate-table"><caption>Hourly crew rates — Monday through Sunday</caption><thead><tr><th>Movers</th><th>Moving / hr</th><th>With full pack / hr</th><th>Capacity / hr</th><th>Use when volume exceeds</th></tr></thead><tbody>{Array.from({ length: 10 }, (_, i) => {
          const rate = active?.hourly_rates[i]; const capacity = active?.capacity_per_mover; const pack = active?.full_pack_hourly;
          return <tr key={i}><th scope="row">{i + 1} {i ? "movers" : "mover"}</th><td>{editing ? settingInput("hourly_rates", `Hourly rate for ${i + 1} movers`, i, false) : money(rate)}</td><td>{rate != null && pack != null ? money(rate + pack) : "?"}</td><td>{capacity != null ? `${number(capacity * (i + 1))} cf` : "?"}</td><td>{i === 0 ? "Base crew" : editing ? settingInput("crew_thresholds", `Volume threshold for ${i + 1} movers`, i - 1) : active?.crew_thresholds[i - 1] != null ? `${number(active.crew_thresholds[i - 1])} cf` : "?"}</td></tr>;
        })}</tbody></table></div>
        <p className="local-hint">Thresholds use greater than, so a crew increases only after its volume threshold is exceeded. Blank rates cannot be quoted.</p>
        <details className="local-trucks" open={editing}><summary>Truck requirements <span>Volume thresholds</span></summary><div className="local-table-scroll"><table className="local-rate-table"><caption>One truck by default; add trucks at these thresholds.</caption><thead><tr><th>Trucks</th>{Array.from({ length: 9 }, (_, i) => <th key={i}>{i + 2}</th>)}</tr></thead><tbody><tr><th>Above cubic feet</th>{Array.from({ length: 9 }, (_, i) => <td key={i}>{editing ? settingInput("truck_thresholds", `Volume threshold for ${i + 2} trucks`, i) : active?.truck_thresholds[i] ?? "?"}</td>)}</tr></tbody></table></div></details>
        {editing && <div className="local-edit-actions"><button className="slds-button primary" type="submit">{saving ? "Saving?" : "Save local settings"}</button><button type="button" className="slds-button" onClick={() => setEditing(false)}>Cancel</button></div>}
      </fieldset>
    </form>
  </div>;
}
