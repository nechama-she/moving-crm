import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { API_BASE } from "../apiConfig";
import { authHeaders, useAuth } from "../AuthContext";
import type { Lead } from "../leadUtils";
import { initials } from "./initials";
import Icon from "./Icon";
import { SmartSummary, StageStepper } from "./LeadBits";
import { useCountUp } from "./motion";
import { greeting } from "./greeting";
import { Attention, PipelineFunnel } from "./LeadsOverview";

type Totals = { new_today: number; new_month: number; quotes: number; quote_value: number; booked_value: number };
// `previous` (same period one month earlier; new_today = same weekday last week) and `trend` (daily
// values for the month) come from the server's overview; older servers omit them and the cards still work.
type Summary = Totals & { previous?: Totals; trend?: Record<"new_leads" | "quotes" | "quote_value" | "booked_value", number[]> };
type Kpi = { label: string; value: string; current?: number; previous?: number; note: string; series?: number[]; color: string; format: (n: number) => string };

function changePercent(current?: number, previous?: number) {
  if (current == null || previous == null || previous <= 0) return null;
  const pct = Math.round(((current - previous) / previous) * 100);
  return { up: pct >= 0, text: `${pct >= 0 ? "+" : "−"}${Math.abs(pct)}%` };
}

function Sparkline({ values, color }: { values?: number[]; color: string }) {
  if (!values || values.length < 2) return null;
  // 3-day average of the daily values: shows the direction without single-day spikes.
  const points = values.map((_, i) => { const win = values.slice(Math.max(0, i - 2), i + 1); return win.reduce((a, b) => a + b, 0) / win.length; });
  const max = Math.max(...points), min = Math.min(...points);
  if (max === min) return null;
  const w = 96, h = 36, pad = 3;
  const path = points.map((v, i) => `${(pad + (i / (points.length - 1)) * (w - pad * 2)).toFixed(1)},${(h - pad - ((v - min) / (max - min)) * (h - pad * 2)).toFixed(1)}`).join(" ");
  return <svg className="aur-spark" aria-hidden="true" width={w} height={h} viewBox={`0 0 ${w} ${h}`} fill="none"><polyline points={path} pathLength={1} stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
// A KPI value that counts up to its number, showing whole numbers on the way and the exact value at the end.
function CountUp({ value, format }: { value: number; format: (n: number) => string }) {
  const shown = useCountUp(value);
  return <>{format(Math.abs(shown - value) < 1e-9 ? value : Math.round(shown))}</>;
}
type Option = { id: string; name: string };

const VIEWS: Array<{ label: string; status: string }> = [
  { label: "All leads", status: "" },
  { label: "New", status: "new" },
  { label: "Contacted", status: "contacted" },
  { label: "Quoted", status: "quoted" },
  { label: "Booked", status: "booked" },
];
const MORE_STATUSES = ["scheduled", "completed", "lost", "cancelled"];
const PALETTE = [["#E4E6FF", "#3D3FE0"], ["#FFE3D3", "#8A3A12"], ["#DDF3E8", "#0F6B47"], ["#FFF0CC", "#7A4C00"], ["#F1EBFF", "#5B34C7"], ["#E3F3FF", "#0B5C8F"]];
const DOTS = ["#4B4DF7", "#E2552B", "#0E9F8A", "#B7791F", "#7C5CFA", "#0B7FB8"];

// Exact amounts (cents only when there are any), never shortened to k/M.
const usd = (n: number) => {
  const digits = Number.isInteger(Math.round(n * 100) / 100) ? 0 : 2;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
};
const hash = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
const tint = (s: string) => PALETTE[hash(s) % PALETTE.length];
const quoteOf = (lead: Lead) => Number((lead.estimatedTotal as { finalTotal?: number } | null)?.finalTotal || 0);
const str = (v: unknown) => (v == null ? "" : String(v));

function relativeDays(date: string) {
  const d = new Date(date.length === 10 ? `${date}T12:00:00` : date);
  if (isNaN(d.getTime())) return "";
  const days = Math.round((d.getTime() - Date.now()) / 86400000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  if (days > 0) return days < 14 ? `in ${days} days` : days < 60 ? `in ${Math.round(days / 7)} weeks` : `in ${Math.round(days / 30)} months`;
  return days > -14 ? `${-days} days ago` : `${Math.round(-days / 7)} weeks ago`;
}

function since(date: string) {
  const d = new Date(date);
  if (isNaN(d.getTime())) return "";
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return relativeDays(date);
}

function formatDate(date: string) {
  const d = new Date(date.length === 10 ? `${date}T12:00:00` : date);
  return isNaN(d.getTime()) ? date : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function shortPlace(place: string) {
  return place.replace(/\s+\d{5}(-\d{4})?$/, "") || place;
}

export default function AuroraLeads() {
  const { token, user } = useAuth();
  const easternParts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit" }).formatToParts(new Date());
  const currentMonth = `${easternParts.find(p => p.type === "year")!.value}-${easternParts.find(p => p.type === "month")!.value}`;
  const [month, setMonth] = useState(currentMonth);
  const isCurrentMonth = month === currentMonth;
  const monthLabel = new Date(`${month}-01T12:00:00`).toLocaleDateString("en-US", { month: "long", year: "numeric" });

  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);
  // True while the cards wait for a new month or filter, so they never show the previous numbers.
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [searchParams] = useSearchParams();
  const urlSearch = searchParams.get("search") || "";
  const [searchInput, setSearchInput] = useState(urlSearch);
  const [search, setSearch] = useState(urlSearch);
  // The lead search's "See all results" links here with ?search=.
  useEffect(() => {
    if (!urlSearch) return;
    setSearch(urlSearch);
    setSearchInput(urlSearch);
  }, [urlSearch]);
  const [status, setStatus] = useState("");
  const [company, setCompany] = useState("");
  const [rep, setRep] = useState("");
  const [sortBy, setSortBy] = useState("created_time");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [companies, setCompanies] = useState<Option[]>([]);
  const [reps, setReps] = useState<Option[]>([]);
  const [selected, setSelected] = useState<Lead | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const active = useRef<AbortController | null>(null);
  const version = useRef(0);

  useEffect(() => {
    fetch(`${API_BASE}/api/companies/mine`, { headers: authHeaders(token) }).then(r => r.json()).then(d => setCompanies(Array.isArray(d) ? d : [])).catch(() => {});
    fetch(`${API_BASE}/api/users/mine-reps`, { headers: authHeaders(token) }).then(r => r.json()).then(d => setReps(Array.isArray(d) ? d : [])).catch(() => {});
  }, [token]);

  const load = useCallback(async (offset: number) => {
    const first = offset === 0;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const v = first ? ++version.current : version.current;
    if (first) { setError(""); setLoading(true); setSummaryLoading(true); } else setLoadingMore(true);
    try {
      const params = new URLSearchParams({ limit: "50", offset: String(offset), overview_month: month, sort_by: sortBy, sort_dir: sortDir });
      if (search) params.set("search", search);
      if (status) params.set("status", status);
      if (company) params.set("company_id", company);
      if (rep) params.set("assigned_to", rep);
      const res = await fetch(`${API_BASE}/api/leads?${params}`, { headers: authHeaders(token), signal: controller.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (v !== version.current) return;
      setLeads(prev => {
        if (first) return data.items;
        const merged = new Map(prev.map(l => [l.id, l]));
        for (const l of data.items) merged.set(l.id, l);
        return [...merged.values()];
      });
      setHasMore(data.has_more);
      setTotal(data.total);
      if (first) setSummary(data.summary || null);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (v === version.current) setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (v === version.current && active.current === controller) { setLoading(false); setLoadingMore(false); setSummaryLoading(false); }
    }
  }, [token, month, sortBy, sortDir, search, status, company, rep]);

  useEffect(() => { load(0); return () => active.current?.abort(); }, [load]);

  const observer = useRef<IntersectionObserver | null>(null);
  const sentinel = useCallback((node: HTMLDivElement | null) => {
    observer.current?.disconnect();
    if (!node || !hasMore) return;
    observer.current = new IntersectionObserver(entries => { if (entries[0].isIntersecting && !loadingMore) load(leads.length); });
    observer.current.observe(node);
  }, [hasMore, loadingMore, load, leads.length]);

  function onSearch(value: string) {
    setSearchInput(value);
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => setSearch(value), 300);
  }

  function sort(col: string) {
    if (sortBy === col) setSortDir(d => (d === "asc" ? "desc" : "asc"));
    else { setSortBy(col); setSortDir(col === "created_time" ? "desc" : "asc"); }
  }

  function moveMonth(delta: number) {
    const [y, m] = month.split("-").map(Number);
    const d = new Date(y, m - 1 + delta, 1);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }

  function clearFilters() {
    if (debounce.current) clearTimeout(debounce.current);
    setSearchInput(""); setSearch(""); setStatus(""); setCompany(""); setRep("");
  }

  const period = isCurrentMonth ? "month to date" : monthLabel;
  const prev = summary?.previous;
  const kpis: Kpi[] = [
    {
      label: isCurrentMonth ? "New leads today" : "New leads",
      value: summary ? (isCurrentMonth ? summary.new_today : summary.new_month).toLocaleString() : "—",
      current: summary ? (isCurrentMonth ? summary.new_today : summary.new_month) : undefined,
      previous: prev ? (isCurrentMonth ? prev.new_today : prev.new_month) : undefined,
      note: isCurrentMonth ? "vs. same day last week" : `${monthLabel} vs. previous month`,
      series: summary?.trend?.new_leads, color: "#4B4DF7", format: n => n.toLocaleString(),
    },
    { label: isCurrentMonth ? "Quotes this month" : "Quotes", value: summary ? summary.quotes.toLocaleString() : "—", current: summary?.quotes, previous: prev?.quotes, note: `Priority 1 leads · ${period}`, series: summary?.trend?.quotes, color: "#7C5CFA", format: n => n.toLocaleString() },
    { label: "Quote value", value: summary ? usd(summary.quote_value) : "—", current: summary?.quote_value, previous: prev?.quote_value, note: `Open quote totals · ${period}`, series: summary?.trend?.quote_value, color: "#0E9F8A", format: usd },
    { label: "Booked value", value: summary ? usd(summary.booked_value) : "—", current: summary?.booked_value, previous: prev?.booked_value, note: `Booked sales · ${period}`, series: summary?.trend?.booked_value, color: "#E2552B", format: usd },
  ];
  const companyLabel = companies.find(c => c.id === company)?.name || "All accessible companies";
  const sortMark = (col: string) => (sortBy === col ? (sortDir === "asc" ? "ascending" : "descending") : undefined);

  return (
    <div className="aur-page aur-leads">
      <header className="aur-page-head">
        <div>
          <span className="aur-eyebrow">Leads</span>
          {/* One text value, so the heading can build in letter by letter (motion.ts). */}
          <h1>{`${greeting()}${user?.name ? `, ${user.name.split(" ")[0]}` : ""}`}</h1>
          <Attention newToday={isCurrentMonth && summary ? summary.new_today : undefined} />
          <p className="aur-muted aur-records">{loading ? "Updating records…" : `${total.toLocaleString()} records`} {"·"} {companyLabel}</p>
        </div>
        <div className="aur-month" role="group" aria-label="Overview month">
          <button type="button" className="aur-icon-btn is-bordered" aria-label="Previous month" onClick={() => moveMonth(-1)}><span className="aur-flip"><Icon name="chevron" size={16} /></span></button>
          <span aria-live="polite">{monthLabel}</span>
          <button type="button" className="aur-icon-btn is-bordered" aria-label="Next month" disabled={month >= currentMonth} onClick={() => moveMonth(1)}><Icon name="chevron" size={16} /></button>
          <button type="button" className="aur-btn" disabled={isCurrentMonth} onClick={() => setMonth(currentMonth)}>This month</button>
        </div>
      </header>

      <section className={`aur-kpis${summaryLoading ? " is-loading" : ""}`} aria-label="Sales overview" aria-busy={summaryLoading}>
        {summaryLoading && <div className="aur-kpis-progress" role="progressbar" aria-label={`Loading ${monthLabel} overview`} />}
        {kpis.map(k => {
          const delta = summaryLoading ? null : changePercent(k.current, k.previous);
          return (
            <div className="aur-kpi" key={k.label}>
              <div className="aur-kpi-top">
                <span className="aur-kpi-label">{k.label}</span>
                {delta && <span className={`aur-kpi-delta ${delta.up ? "is-up" : "is-down"}`} title={k.note}>{delta.text}</span>}
              </div>
              <div className="aur-kpi-row">
                {summaryLoading ? <span className="aur-skeleton aur-kpi-skeleton" aria-hidden="true" /> : <strong>{k.current === undefined ? k.value : <CountUp value={k.current} format={k.format} />}</strong>}
                {!summaryLoading && <Sparkline values={k.series} color={k.color} />}
              </div>
              <small>{k.note}</small>
            </div>
          );
        })}
      </section>

      <PipelineFunnel month={month} monthLabel={monthLabel} company={company} rep={rep} />

      {error && <div className="aur-alert" role="alert"><span>Failed to load leads: {error}</span><button type="button" className="aur-btn" onClick={() => load(0)}>Retry</button></div>}

      <div className={`aur-leads-body${selected ? " has-panel" : ""}`}>
        <section className="aur-card aur-directory" aria-label="Lead directory">
          <div className="aur-tabs" role="tablist" aria-label="Views">
            {VIEWS.map(v => (
              <button key={v.label} type="button" role="tab" aria-selected={status === v.status} className={`aur-tab${status === v.status ? " is-active" : ""}`} onClick={() => setStatus(v.status)}>{v.label}</button>
            ))}
            <label className="aur-tab-more">
              <span className="aur-sr">More statuses</span>
              <select value={MORE_STATUSES.includes(status) ? status : ""} onChange={e => setStatus(e.target.value)}>
                <option value="">More…</option>
                {MORE_STATUSES.map(s => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}
              </select>
            </label>
          </div>

          <div className="aur-filters">
            <label className="aur-searchbox">
              <Icon name="search" size={16} />
              <input type="search" aria-label="Search leads" placeholder="Search name, ID, phone or email" value={searchInput} onChange={e => onSearch(e.target.value)} />
            </label>
            {(companies.length > 1 || user?.role === "admin") && (
              <select className="aur-select" aria-label="Company" value={company} onChange={e => setCompany(e.target.value)}>
                <option value="">All companies</option>
                {user?.role === "admin" && <option value="__unassigned__">Unassigned company</option>}
                {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
            {reps.length > 0 && (
              <select className="aur-select" aria-label="Sales representative" value={rep} onChange={e => setRep(e.target.value)}>
                <option value="">All reps</option>
                <option value="__unassigned__">Unassigned</option>
                {reps.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            )}
            <button type="button" className="aur-btn is-ghost" onClick={clearFilters}>Clear</button>
          </div>

          {loading && !leads.length ? <div className="aur-empty">Loading leads…</div> : !leads.length ? <div className="aur-empty">No leads match these filters.</div> : (
            <div className="aur-table-wrap">
              <table className="aur-table">
                <thead>
                  <tr>
                    <th scope="col" aria-sort={sortMark("full_name")}><button type="button" onClick={() => sort("full_name")}>Customer</button></th>
                    <th scope="col" aria-sort={sortMark("status")}><button type="button" onClick={() => sort("status")}>Stage</button></th>
                    <th scope="col" aria-sort={sortMark("pickup_zip")}><button type="button" onClick={() => sort("pickup_zip")}>Route</button></th>
                    <th scope="col">Move</th>
                    <th scope="col" className="is-num">Quote</th>
                    <th scope="col">Owner</th>
                    <th scope="col" aria-sort={sortMark("created_time")}><button type="button" onClick={() => sort("created_time")}>Created</button></th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map(lead => {
                    const name = str(lead.full_name) || "Unnamed lead";
                    const [bg, fg] = tint(name);
                    const owner = str(lead.assigned_to_name);
                    const [obg, ofg] = tint(owner || "-");
                    const companyName = lead.company_id ? str(lead.company_name) : "Unassigned company";
                    const stage = str(lead.status || "new").toLowerCase();
                    const quote = quoteOf(lead);
                    const moveDate = str(lead["when_is_the_move?"]);
                    return (
                      <tr key={lead.id} className={selected?.id === lead.id ? "is-selected" : undefined} onClick={() => setSelected(lead)}>
                        <td>
                          <div className="aur-person">
                            <span className="aur-avatar is-square" style={{ background: bg, color: fg }}>{initials(name)}</span>
                            <span className="aur-person-text">
                              <button type="button" className="aur-link-strong" onClick={e => { e.stopPropagation(); setSelected(lead); }}>{name}</button>
                              <small><i className="aur-dot" style={{ background: DOTS[hash(companyName) % DOTS.length] }} />{companyName}</small>
                            </span>
                          </div>
                        </td>
                        <td><span className={`aur-stage stage-${stage}`}>{stage}</span></td>
                        <td>
                          <span className="aur-route">{shortPlace(str(lead.pickup_zip)) || "—"}<Icon name="arrow" size={14} />{shortPlace(str(lead.delivery_zip)) || "—"}</span>
                          <small className="aur-muted">{str(lead.move_size)}</small>
                        </td>
                        <td>{moveDate ? <><span className="aur-strong">{formatDate(moveDate)}</span><small className="aur-muted">{relativeDays(moveDate)}</small></> : <span className="aur-muted">{"—"}</span>}</td>
                        <td className="is-num aur-strong">{quote ? usd(quote) : <span className="aur-muted">{"—"}</span>}</td>
                        <td>{owner ? <span className="aur-avatar is-sm" title={owner} style={{ background: obg, color: ofg }}>{initials(owner)}</span> : <span className="aur-muted">Unassigned</span>}</td>
                        <td className="aur-muted">{since(str(lead.created_time || lead.created_at))}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div ref={sentinel} style={{ height: 1 }} />
              {loadingMore && <div className="aur-empty is-small">Loading more…</div>}
            </div>
          )}
          <div className="aur-table-foot aur-muted">{`${leads.length.toLocaleString()} of ${total.toLocaleString()} records · overview follows filters`}</div>
        </section>

        {selected && <LeadPanel lead={selected} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}

function LeadPanel({ lead, onClose }: { lead: Lead; onClose: () => void }) {
  const name = str(lead.full_name) || "Unnamed lead";
  const [bg, fg] = tint(name);
  const phone = str(lead.phone_number);
  const email = str(lead.email);
  const quote = quoteOf(lead);
  const moveDate = str(lead["when_is_the_move?"]);

  return (
    <aside className="aur-card aur-panel" aria-label={`Lead ${name}`}>
      <div className="aur-panel-head">
        <span className="aur-avatar is-lg is-square" style={{ background: bg, color: fg }}>{initials(name)}</span>
        <div className="aur-panel-title">
          <strong>{name}</strong>
          <small className="aur-muted">{lead.company_id ? str(lead.company_name) : "Unassigned company"}{lead.leadgen_id ? ` · Lead ${str(lead.leadgen_id)}` : ""}</small>
        </div>
        <button type="button" className="aur-icon-btn" aria-label="Close lead panel" onClick={onClose}><Icon name="close" size={16} /></button>
      </div>

      <StageStepper status={str(lead.status)} />

      <div className="aur-quick">
        {phone ? <a className="aur-quick-btn" href={`tel:${phone}`}><Icon name="phone" size={16} />Call</a> : <span className="aur-quick-btn is-disabled"><Icon name="phone" size={16} />Call</span>}
        {email ? <a className="aur-quick-btn" href={`mailto:${email}`}><Icon name="mail" size={16} />Email</a> : <span className="aur-quick-btn is-disabled"><Icon name="mail" size={16} />Email</span>}
        <Link className="aur-quick-btn is-primary" to={`/leads/${encodeURIComponent(lead.id)}`} target="_blank" rel="noopener noreferrer"><Icon name="external" size={16} />Open lead</Link>
      </div>

      <SmartSummary leadId={lead.id} />

      <dl className="aur-facts">
        <div><dt>Pickup</dt><dd>{str(lead.pickup_zip) || "—"}</dd></div>
        <div><dt>Delivery</dt><dd>{str(lead.delivery_zip) || "—"}</dd></div>
        <div><dt>Move date</dt><dd>{moveDate ? formatDate(moveDate) : "—"}</dd></div>
        <div><dt>Size</dt><dd>{str(lead.move_size) || "—"}</dd></div>
        <div><dt>Quote</dt><dd className="aur-strong">{quote ? usd(quote) : "—"}</dd></div>
        <div><dt>Owner</dt><dd>{str(lead.assigned_to_name) || "Unassigned"}</dd></div>
        <div><dt>Phone</dt><dd>{phone || "—"}</dd></div>
        <div><dt>Email</dt><dd className="aur-break">{email || "—"}</dd></div>
      </dl>
    </aside>
  );
}
