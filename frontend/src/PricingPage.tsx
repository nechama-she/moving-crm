import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type PlanSummary = {
  id: string; company_name: string; name: string; pickup_regions: string;
  fuel_percent: number | null; rate_count: number; rule_count: number;
  service_count: number; updated_at: string;
};
type Rule = { id?: string; category: string; title: string; description: string };
type Rate = {
  id?: string; destination: string; destination_group: string;
  minimum_price: number | null; minimum_text: string; band_label: string;
  cubic_feet_min: number | null; cubic_feet_max: number | null;
  rate: number | null; rate_text: string;
};
type Service = { id?: string; name: string; rate_text: string; comments: string };
type Plan = PlanSummary & {
  active: boolean; source_file: string; source_sheet: string;
  rules: Rule[]; rates: Rate[]; services: Service[];
};

const money = (value: number | null | undefined) =>
  value == null ? "—" : value.toLocaleString("en-US", { style: "currency", currency: "USD" });

export default function PricingPage() {
  const { token, user } = useAuth();
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [draft, setDraft] = useState<Plan | null>(null);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [destination, setDestination] = useState("");
  const [cubicFeet, setCubicFeet] = useState("");
  const [quote, setQuote] = useState<Record<string, unknown> | null>(null);
  const [openSections, setOpenSections] = useState({ rules: true, rates: true, services: true });

  useEffect(() => {
    void fetch(`${API_BASE}/api/pricing`, { headers: authHeaders(token) })
      .then(async (response) => {
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Failed to load pricing");
        return response.json();
      })
      .then((rows: PlanSummary[]) => {
        setPlans(rows);
        setSelectedId((current) => current || rows[0]?.id || "");
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Failed to load pricing"))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    if (!selectedId) return;
    setLoading(true);
    setError("");
    setEditing(false);
    setQuote(null);
    void fetch(`${API_BASE}/api/pricing/${selectedId}`, { headers: authHeaders(token) })
      .then(async (response) => {
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Failed to load pricing plan");
        return response.json();
      })
      .then((row: Plan) => {
        setPlan(row);
        setDraft(structuredClone(row));
        setDestination(row.rates[0]?.destination || "");
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Failed to load pricing plan"))
      .finally(() => setLoading(false));
  }, [selectedId, token]);

  const active = editing ? draft : plan;
  const destinations = useMemo(
    () => Array.from(new Set((active?.rates || []).map((row) => row.destination))),
    [active],
  );
  const bands = useMemo(
    () => Array.from(new Set((active?.rates || []).map((row) => row.band_label))),
    [active],
  );
  const rateRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return destinations
      .filter((name) => !query || name.toLowerCase().includes(query))
      .map((name) => ({ name, rates: (active?.rates || []).filter((row) => row.destination === name) }));
  }, [active, destinations, search]);

  function patchDraft(patch: Partial<Plan>) {
    setDraft((current) => current ? { ...current, ...patch } : current);
  }
  function patchRule(index: number, patch: Partial<Rule>) {
    if (!draft) return;
    patchDraft({ rules: draft.rules.map((row, idx) => idx === index ? { ...row, ...patch } : row) });
  }
  function patchService(index: number, patch: Partial<Service>) {
    if (!draft) return;
    patchDraft({ services: draft.services.map((row, idx) => idx === index ? { ...row, ...patch } : row) });
  }
  function patchRate(id: string | undefined, patch: Partial<Rate>) {
    if (!draft) return;
    patchDraft({ rates: draft.rates.map((row) => row.id === id ? { ...row, ...patch } : row) });
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`${API_BASE}/api/pricing/${draft.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          name: draft.name, pickup_regions: draft.pickup_regions,
          fuel_percent: draft.fuel_percent, active: draft.active,
          rules: draft.rules, rates: draft.rates, services: draft.services,
        }),
      });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Failed to save pricing");
      const saved: Plan = await response.json();
      setPlan(saved);
      setDraft(structuredClone(saved));
      setEditing(false);
      setNotice("Pricing changes saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to save pricing");
    } finally {
      setSaving(false);
    }
  }

  async function calculate() {
    if (!active || !destination || !cubicFeet) return;
    setError("");
    const params = new URLSearchParams({ destination, cubic_feet: cubicFeet });
    const response = await fetch(`${API_BASE}/api/pricing/${active.id}/quote?${params}`, { headers: authHeaders(token) });
    if (!response.ok) {
      setError((await response.json().catch(() => ({}))).detail || "Could not calculate pricing");
      return;
    }
    setQuote(await response.json());
  }

  return (
    <div className="pricing-page">
      <header className="pricing-heading">
        <div>
          <h1>Pricing</h1>
          <p>Company rate books, exceptions, and additional services imported from Excel.</p>
        </div>
        {user?.role === "admin" && active ? (
          <div className="pricing-actions">
            {editing ? (
              <>
                <button className="slds-button secondary" onClick={() => { setDraft(plan ? structuredClone(plan) : null); setEditing(false); }}>Cancel</button>
                <button className="slds-button primary" disabled={saving} onClick={() => void save()}>{saving ? "Saving…" : "Save changes"}</button>
              </>
            ) : <button className="slds-button primary" onClick={() => setEditing(true)}>Edit pricing</button>}
          </div>
        ) : null}
      </header>

      {error ? <div className="pricing-alert error">{error}</div> : null}
      {notice ? <div className="pricing-alert success">{notice}</div> : null}

      <div className="pricing-layout">
        <aside className="pricing-book-list">
          <label>Pricing book</label>
          <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            {plans.map((row) => <option key={row.id} value={row.id}>{row.company_name} — {row.name}</option>)}
          </select>
          <div className="pricing-books-desktop">
            {plans.map((row) => (
              <button key={row.id} className={row.id === selectedId ? "active" : ""} onClick={() => setSelectedId(row.id)}>
                <strong>{row.company_name}</strong><span>{row.name}</span>
                <small>{row.rate_count} rates · {row.rule_count} rules</small>
              </button>
            ))}
          </div>
        </aside>

        <main className="pricing-content">
          {loading || !active ? <div className="pricing-card">Loading pricing…</div> : (
            <>
              <section className="pricing-card pricing-overview">
                <div>
                  <span className="eyebrow">{active.company_name}</span>
                  {editing ? <input className="pricing-title-input" value={active.name} onChange={(e) => patchDraft({ name: e.target.value })} /> : <h2>{active.name}</h2>}
                  <p>{active.pickup_regions || "Pickup coverage is described in the rules below."}</p>
                </div>
                <div className="pricing-kpis">
                  <div><span>Fuel</span>{editing ? <input type="number" step="0.1" value={active.fuel_percent ?? ""} onChange={(e) => patchDraft({ fuel_percent: e.target.value === "" ? null : Number(e.target.value) })} /> : <strong>{active.fuel_percent == null ? "See rules" : `${active.fuel_percent}%`}</strong>}</div>
                  <div><span>Destinations</span><strong>{destinations.length}</strong></div>
                  <div><span>Services</span><strong>{active.services.length}</strong></div>
                </div>
              </section>

              <section className="pricing-card pricing-calculator">
                <div><span className="eyebrow">Quick estimate</span><h2>Rate lookup</h2></div>
                <div className="pricing-calc-fields">
                  <label>Destination<select value={destination} onChange={(e) => { setDestination(e.target.value); setQuote(null); }}>{destinations.map((name) => <option key={name}>{name}</option>)}</select></label>
                  <label>Cubic feet<input type="number" min="0" value={cubicFeet} onChange={(e) => { setCubicFeet(e.target.value); setQuote(null); }} placeholder="e.g. 650" /></label>
                  <button className="slds-button primary" onClick={() => void calculate()}>Calculate</button>
                </div>
                {quote ? (
                  <div className="pricing-quote">
                    <div><span>Rate</span><strong>{(quote.match as Rate | null)?.rate == null ? (quote.match as Rate | null)?.rate_text || "Manual" : `${money((quote.match as Rate).rate)}/cf`}</strong></div>
                    <div><span>Base / minimum</span><strong>{money(quote.base_price as number | null)}</strong></div>
                    <div><span>Fuel</span><strong>{money(quote.fuel as number | null)}</strong></div>
                    <div className="total"><span>Before services</span><strong>{money(quote.total_before_services as number | null)}</strong></div>
                    {quote.warning ? <p>{String(quote.warning)}</p> : null}
                  </div>
                ) : null}
              </section>

              <PricingSection title="Rules & exceptions" count={active.rules.length} open={openSections.rules} toggle={() => setOpenSections((s) => ({ ...s, rules: !s.rules }))}>
                <div className="pricing-rules">
                  {active.rules.map((rule, index) => (
                    <article key={rule.id || index} className={rule.category === "exception" ? "exception" : ""}>
                      {editing ? (
                        <>
                          <input value={rule.title} onChange={(e) => patchRule(index, { title: e.target.value })} />
                          <textarea value={rule.description} onChange={(e) => patchRule(index, { description: e.target.value })} />
                          <button className="text-danger" onClick={() => patchDraft({ rules: draft!.rules.filter((_, idx) => idx !== index) })}>Remove</button>
                        </>
                      ) : <><strong>{rule.title}</strong><p>{rule.description}</p></>}
                    </article>
                  ))}
                  {editing ? <button className="add-row" onClick={() => patchDraft({ rules: [...draft!.rules, { category: "general", title: "Pricing rule", description: "" }] })}>+ Add rule</button> : null}
                </div>
              </PricingSection>

              <PricingSection title="Transportation rates" count={rateRows.length} open={openSections.rates} toggle={() => setOpenSections((s) => ({ ...s, rates: !s.rates }))}>
                <div className="pricing-table-toolbar"><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search destination or ZIP area" /><span>{bands.length} cubic-foot bands</span></div>
                <div className="pricing-rate-table-wrap">
                  <table className="pricing-rate-table">
                    <thead><tr><th>Destination</th><th>Minimum</th>{bands.map((band) => <th key={band}>{band}</th>)}</tr></thead>
                    <tbody>
                      {rateRows.map((group) => (
                        <tr key={group.name}>
                          <th>{group.name}<small>{group.rates[0]?.destination_group}</small></th>
                          <td>{editing ? <input type="number" value={group.rates[0]?.minimum_price ?? ""} onChange={(e) => group.rates.forEach((rate) => patchRate(rate.id, { minimum_price: e.target.value === "" ? null : Number(e.target.value) }))} /> : money(group.rates[0]?.minimum_price)}</td>
                          {bands.map((band) => {
                            const rate = group.rates.find((row) => row.band_label === band);
                            return <td key={band}>{!rate ? "—" : editing ? <input value={rate.rate ?? rate.rate_text} onChange={(e) => patchRate(rate.id, { rate: e.target.value === "" || Number.isNaN(Number(e.target.value)) ? null : Number(e.target.value), rate_text: e.target.value })} /> : rate.rate == null ? rate.rate_text : money(rate.rate)}</td>;
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </PricingSection>

              <PricingSection title="Additional services" count={active.services.length} open={openSections.services} toggle={() => setOpenSections((s) => ({ ...s, services: !s.services }))}>
                <div className="pricing-services">
                  {active.services.map((service, index) => (
                    <article key={service.id || index}>
                      {editing ? (
                        <>
                          <input value={service.name} onChange={(e) => patchService(index, { name: e.target.value })} />
                          <input value={service.rate_text} onChange={(e) => patchService(index, { rate_text: e.target.value })} />
                          <input value={service.comments} onChange={(e) => patchService(index, { comments: e.target.value })} />
                          <button className="text-danger" onClick={() => patchDraft({ services: draft!.services.filter((_, idx) => idx !== index) })}>Remove</button>
                        </>
                      ) : <><div><strong>{service.name}</strong>{service.comments ? <small>{service.comments}</small> : null}</div><b>{service.rate_text || "See note"}</b></>}
                    </article>
                  ))}
                  {editing ? <button className="add-row" onClick={() => patchDraft({ services: [...draft!.services, { name: "", rate_text: "", comments: "" }] })}>+ Add service</button> : null}
                </div>
              </PricingSection>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function PricingSection({ title, count, open, toggle, children }: { title: string; count: number; open: boolean; toggle: () => void; children: React.ReactNode }) {
  return <section className="pricing-card pricing-section"><button className="pricing-section-title" onClick={toggle}><span><strong>{title}</strong><small>{count}</small></span><b>{open ? "−" : "+"}</b></button>{open ? <div className="pricing-section-body">{children}</div> : null}</section>;
}
