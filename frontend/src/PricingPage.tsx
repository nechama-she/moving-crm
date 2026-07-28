import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
type CalculatedCharge = {
  id: string; name: string; description: string; calculation_type: string;
  rate: number; default_selected: boolean; automatic: boolean; applies: boolean;
  quantity_label: string; selected: boolean; amount: number;
};
type Calculation = {
  match: Rate | null; transport: number | null; minimum: number | null;
  minimum_applied: boolean; base_price: number | null; charges: CalculatedCharge[];
  total: number; warning: string;
};
type JobContext = {
  lead: { id: string; full_name: string; volume: number | null; weight: number | null };
  job: { id: string; job_order: number; company_name: string; pickup_zip: string; delivery_zip: string; pickup_state: string; pickup_zip_code: string; delivery_state: string; delivery_zip_code: string; move_date: string; booked_move_date: string };
  plans: PlanSummary[];
  recommended_plan_id: string;
  serviceability: "supported" | "unknown_pickup" | "unsupported_pickup";
};

const money = (value: number | null | undefined) =>
  value == null ? "—" : value.toLocaleString("en-US", { style: "currency", currency: "USD" });

function destinationFromAddress(address: string, options: string[], resolvedState = "", resolvedZip = ""): string {
  const state = resolvedState || address.toUpperCase().match(/(?:,\s*|\b)([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?|\b)/)?.[1];
  if (!state) return "";
  const zip = resolvedZip || address.match(/\b(\d{5})(?:-\d{4})?\b/)?.[1] || "";
  const zipPrefix = zip ? Number(zip.slice(0, 2)) : null;
  const stateOptions = options.filter((option) => option.toUpperCase() === state || option.toUpperCase().startsWith(`${state} `) || option.toUpperCase().startsWith(`${state} (`));
  if (zipPrefix != null) {
    const ranged = stateOptions.find((option) => {
      const range = option.match(/(\d{2})\s*x{3}\s*-\s*(\d{2})\s*x{3}/i);
      return range ? zipPrefix >= Number(range[1]) && zipPrefix <= Number(range[2]) : false;
    });
    if (ranged) return ranged;
  }
  return stateOptions.find((option) => option.toUpperCase() === state)
    || stateOptions[0]
    || "";
}

export default function PricingPage() {
  const { token, user } = useAuth();
  const [searchParams] = useSearchParams();
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
  const [quote, setQuote] = useState<Calculation | null>(null);
  const [jobContext, setJobContext] = useState<JobContext | null>(null);
  const [selectedCharges, setSelectedCharges] = useState<Record<string, boolean>>({});
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [manualAmounts, setManualAmounts] = useState<Record<string, number>>({});
  const [openSections, setOpenSections] = useState({ rates: true, services: true });

  useEffect(() => {
    void fetch(`${API_BASE}/api/pricing`, { headers: authHeaders(token) })
      .then(async (response) => {
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Failed to load pricing");
        return response.json();
      })
      .then((rows: PlanSummary[]) => {
        setPlans(rows);
        if (!searchParams.get("lead_id") || !searchParams.get("job_id")) {
          setSelectedId((current) => current || rows[0]?.id || "");
        }
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Failed to load pricing"))
      .finally(() => setLoading(false));
  }, [searchParams, token]);

  useEffect(() => {
    const leadId = searchParams.get("lead_id");
    const jobId = searchParams.get("job_id");
    if (!leadId || !jobId) return;
    void fetch(`${API_BASE}/api/pricing/context?lead_id=${encodeURIComponent(leadId)}&job_id=${encodeURIComponent(jobId)}`, { headers: authHeaders(token) })
      .then(async (response) => {
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Failed to load job pricing");
        return response.json();
      })
      .then((context: JobContext) => {
        setJobContext(context);
        setPlans(context.plans);
        setSelectedId(context.recommended_plan_id || "");
        if (!context.recommended_plan_id) {
          setPlan(null);
          setDraft(null);
        }
        setCubicFeet(context.lead.volume == null ? "" : String(context.lead.volume));
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Failed to load job pricing"));
  }, [searchParams, token]);

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
        const options = Array.from(new Set(row.rates.map((rate) => rate.destination)));
        const inferredDestination = destinationFromAddress(
          jobContext?.job.delivery_zip || "",
          options,
          jobContext?.job.delivery_state || "",
          jobContext?.job.delivery_zip_code || "",
        );
        setDestination(inferredDestination || (jobContext ? "" : options[0] || ""));
        setSelectedCharges({});
        setQuantities({});
        setManualAmounts({});
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
  useEffect(() => {
    if (!plan || !jobContext) return;
    const options = Array.from(new Set(plan.rates.map((rate) => rate.destination)));
    const inferred = destinationFromAddress(
      jobContext.job.delivery_zip,
      options,
      jobContext.job.delivery_state,
      jobContext.job.delivery_zip_code,
    );
    if (inferred) setDestination(inferred);
  }, [jobContext, plan]);
  const rateRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return destinations
      .filter((name) => !query || name.toLowerCase().includes(query))
      .map((name) => ({ name, rates: (active?.rates || []).filter((row) => row.destination === name) }));
  }, [active, destinations, search]);
  const catalogRules = useMemo(() => {
    if (!active) return [];
    const serviceNames = active.services.map((service) => service.name.toLowerCase());
    return active.rules.filter((rule) => {
      const text = rule.description.toLowerCase();
      if (text.includes("destination & origin") && serviceNames.some((name) => name.includes("destination & origin"))) return false;
      if (text.includes("company & fuel") && !text.includes("$")) return false;
      if ((text.includes("pick up from") || text.includes("rates period") || text.includes("to area")) && !/(add|take off|reduce|ask|fee|not included)/i.test(text)) return false;
      if (/^(rates period|exceptions?)$/i.test(rule.description.trim())) return false;
      return true;
    });
  }, [active]);

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

  async function calculate(overrides?: { selected?: Record<string, boolean>; quantities?: Record<string, number>; manual?: Record<string, number> }) {
    if (!active || !destination) return;
    setError("");
    const response = await fetch(`${API_BASE}/api/pricing/${active.id}/calculate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({
        destination,
        cubic_feet: Number(cubicFeet || 0),
        move_date: jobContext?.job.move_date || "",
        selected_charges: overrides?.selected || selectedCharges,
        quantities: overrides?.quantities || quantities,
        manual_amounts: overrides?.manual || manualAmounts,
      }),
    });
    if (!response.ok) {
      setError((await response.json().catch(() => ({}))).detail || "Could not calculate pricing");
      return;
    }
    const result: Calculation = await response.json();
    setQuote(result);
    setSelectedCharges(Object.fromEntries(result.charges.map((charge) => [charge.id, charge.selected])));
  }

  useEffect(() => {
    if (!plan || !destination || editing) return;
    void calculate();
    // Load the unified selectable charge catalog whenever the pricing book changes.
    // User selections are preserved by subsequent checkbox-triggered calculations.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan?.id, destination, editing]);

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
          {jobContext && jobContext.serviceability !== "supported" ? (
            <section className="pricing-card pricing-unavailable">
              <div className="pricing-unavailable-icon" aria-hidden="true">⌖</div>
              <div>
                <span className="eyebrow">Service area check</span>
                <h2>{jobContext.serviceability === "unsupported_pickup" ? "This pickup is outside our current service area" : "We couldn’t confirm the pickup service area"}</h2>
                <p>
                  {jobContext.serviceability === "unsupported_pickup"
                    ? `We don’t currently have a pricing book for pickups in ${jobContext.job.pickup_state}. Please confirm availability with dispatch before quoting this move.`
                    : "Add a valid pickup address or five-digit ZIP code to the job, then try Calculate Price again."}
                </p>
                <Link to={`/leads/${jobContext.lead.id}?job_id=${encodeURIComponent(jobContext.job.id)}`}>Return to the lead</Link>
              </div>
            </section>
          ) : loading || !active ? <div className="pricing-card">Loading pricing…</div> : (
            <>
              {jobContext ? (
                <section className="pricing-card pricing-job-context">
                  <div>
                    <span className="eyebrow">Pricing Job {jobContext.job.job_order}</span>
                    <h2>{jobContext.lead.full_name}</h2>
                    <p>{jobContext.job.pickup_zip || "Pickup not provided"} → {jobContext.job.delivery_zip || "Delivery not provided"}</p>
                  </div>
                  <div>
                    <span>{jobContext.job.move_date || "No move date"}</span>
                    <Link to={`/leads/${jobContext.lead.id}?job_id=${encodeURIComponent(jobContext.job.id)}`}>Back to lead</Link>
                  </div>
                </section>
              ) : null}
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
                <div><span className="eyebrow">Job pricing</span><h2>Calculate price</h2></div>
                {jobContext?.job.delivery_state && !destination ? (
                  <div className="pricing-inline-unavailable">
                    <strong>Delivery area not available</strong>
                    <span>There is no destination rate for {jobContext.job.delivery_state} in this pricing book. Please confirm the route with dispatch.</span>
                  </div>
                ) : null}
                <div className="pricing-calc-fields">
                  <label>Destination<select value={destination} onChange={(e) => { setDestination(e.target.value); setQuote(null); }}><option value="">Select a supported destination</option>{destinations.map((name) => <option key={name}>{name}</option>)}</select></label>
                  <label>Cubic feet<input type="number" min="0" value={cubicFeet} onChange={(e) => { setCubicFeet(e.target.value); setQuote(null); }} placeholder="e.g. 650" /></label>
                  <button className="slds-button primary" disabled={!destination} onClick={() => void calculate()}>Calculate</button>
                </div>
                {quote ? (
                  <>
                    <div className="pricing-quote">
                      <div className="pricing-quote-header">
                        <div><span className="eyebrow">Price breakdown</span><h3>Detailed Price</h3></div>
                        <strong>{money(quote.total)}</strong>
                      </div>
                      <div className="pricing-quote-lines">
                        <div className="pricing-quote-line">
                          <div>
                            <strong>{quote.match?.destination || "Transportation"}</strong>
                            <small>
                              {quote.match
                                ? `${Number(cubicFeet || 0).toLocaleString()} cf × ${quote.match.rate == null ? quote.match.rate_text || "manual rate" : `${money(quote.match.rate)} / cf`} · ${quote.match.band_label}${quote.minimum_applied ? ` · ${money(quote.minimum)} minimum applied` : ""}`
                                : "No transportation rate matched"}
                            </small>
                          </div>
                          <b>{money(quote.base_price)}</b>
                        </div>
                        {quote.charges.filter((charge) => charge.selected).map((charge) => (
                          <div className="pricing-quote-line" key={`summary-${charge.id}`}>
                            <div><strong>{charge.name}</strong><small>{charge.description}</small></div>
                            <b className={charge.amount < 0 ? "discount" : ""}>{money(charge.amount)}</b>
                          </div>
                        ))}
                        <div className="pricing-quote-total"><strong>Total</strong><b>{money(quote.total)}</b></div>
                      </div>
                      {quote.warning ? <p>{quote.warning}</p> : null}
                    </div>
                    <div className="pricing-charge-picker">
                      <div className="pricing-charge-heading">
                        <strong>Charges and adjustments</strong>
                        <span>Default charges are already selected</span>
                      </div>
                      {quote.charges.map((charge) => (
                        <article key={charge.id} className={charge.selected ? "selected" : ""}>
                          <label>
                            <input
                              type="checkbox"
                              checked={charge.selected}
                              disabled={charge.automatic && !charge.applies}
                              onChange={(event) => {
                                const next = { ...selectedCharges, [charge.id]: event.target.checked };
                                setSelectedCharges(next);
                                void calculate({ selected: next });
                              }}
                            />
                            <span>
                              <strong>
                                {charge.name}
                                {charge.automatic ? <em>Automatic</em> : charge.default_selected ? <em>Default</em> : null}
                              </strong>
                              <small>{charge.description}</small>
                            </span>
                          </label>
                          {charge.calculation_type === "per_unit" || charge.calculation_type === "per_cf_month" ? (
                            <input
                              type="number"
                              min="0"
                              value={quantities[charge.id] ?? 1}
                              aria-label={charge.quantity_label || "Quantity"}
                              title={charge.quantity_label || "Quantity"}
                              onChange={(event) => {
                                const next = { ...quantities, [charge.id]: Number(event.target.value) };
                                setQuantities(next);
                                void calculate({ quantities: next });
                              }}
                            />
                          ) : null}
                          {charge.calculation_type === "manual" && charge.selected ? (
                            <input
                              type="number"
                              min="0"
                              value={manualAmounts[charge.id] ?? 0}
                              aria-label="Manual amount"
                              title="Manual amount"
                              onChange={(event) => {
                                const next = { ...manualAmounts, [charge.id]: Number(event.target.value) };
                                setManualAmounts(next);
                                void calculate({ manual: next });
                              }}
                            />
                          ) : null}
                          <b>{charge.selected ? money(charge.amount) : "Not added"}</b>
                        </article>
                      ))}
                    </div>
                  </>
                ) : null}
              </section>

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

              <PricingSection title="Additional services & adjustments" count={active.services.length + catalogRules.length} open={openSections.services} toggle={() => setOpenSections((s) => ({ ...s, services: !s.services }))}>
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
                  {catalogRules.map((rule) => {
                    const index = active.rules.indexOf(rule);
                    return (
                    <article key={rule.id || `rule-${index}`} className="pricing-service-rule">
                      {editing ? (
                        <>
                          <input value={rule.title} onChange={(e) => patchRule(index, { title: e.target.value })} />
                          <textarea value={rule.description} onChange={(e) => patchRule(index, { description: e.target.value })} />
                          <button className="text-danger" onClick={() => patchDraft({ rules: draft!.rules.filter((_, idx) => idx !== index) })}>Remove</button>
                        </>
                      ) : (
                        <>
                          <div><strong>{rule.title || "Pricing adjustment"} <em>Adjustment</em></strong><small>{rule.description}</small></div>
                          <b>{rule.category === "exception" ? "Conditional" : "Included rule"}</b>
                        </>
                      )}
                    </article>
                    );
                  })}
                  {editing ? <button className="add-row" onClick={() => patchDraft({ services: [...draft!.services, { name: "", rate_text: "", comments: "" }] })}>+ Add service</button> : null}
                  {editing ? <button className="add-row" onClick={() => patchDraft({ rules: [...draft!.rules, { category: "general", title: "Pricing adjustment", description: "" }] })}>+ Add adjustment</button> : null}
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
