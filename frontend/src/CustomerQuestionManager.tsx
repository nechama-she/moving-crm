import CatalogItemDialog from "./CatalogItemDialog";
import { useEffect, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import "./CustomerQuestionManager.css";
type Answer = { id: string; label: string; action: string; notice: string; acknowledge: boolean };
type Rule = { id: string; title: string; question: string; enabled: boolean; all_items?: boolean; item_ids: string[]; words: string[]; photo: boolean; answers: Answer[] };
type Item = { id: string; name: string; cuft: number };
const normalize = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const actions = { none: "Keep item included", notice: "Show instructions", exclude: "Exclude from shipment and volume", prepare: "Preparation required", review: "Flag for staff review" };
export default function CustomerQuestionManager() {
 const { token } = useAuth();
 const [companies, setCompanies] = useState<{ id: string; name: string }[]>([]);
 const [company, setCompany] = useState("");
 const [rules, setRules] = useState<Rule[]>([]);
 const [catalog, setCatalog] = useState<Item[]>([]);
 const [revision, setRevision] = useState("");
 const [selected, setSelected] = useState("");
 const [search, setSearch] = useState("");
 const [addingCatalogItem, setAddingCatalogItem] = useState(false);
 const [testName, setTestName] = useState("");
 const [dirty, setDirty] = useState(false);
 const [busy, setBusy] = useState(false);
 const [notice, setNotice] = useState("");
 useEffect(() => { const abort = new AbortController(); fetch(`${API_BASE}/api/companies/mine`, { headers: authHeaders(token), signal: abort.signal }).then(async r => { if (!r.ok) throw new Error("Could not load companies"); return r.json(); }).then(rows => { setCompanies(rows); setCompany(rows[0]?.id || ""); }).catch(e => { if (!abort.signal.aborted) setNotice(e.message); }); return () => abort.abort(); }, [token]);
 useEffect(() => { if (!company) return; const abort = new AbortController(); setRules([]); setCatalog([]); setRevision(""); setSelected(""); setBusy(true); setNotice(""); fetch(`${API_BASE}/api/customer-questions/${company}`, { headers: authHeaders(token), signal: abort.signal }).then(async r => { if (!r.ok) throw new Error("Could not load questions"); return r.json(); }).then(body => { setRules(body.rules); setCatalog(body.catalog); setRevision(body.revision); setSelected(body.rules[0]?.id || ""); setDirty(false); }).catch(e => { if (!abort.signal.aborted) setNotice(e.message); }).finally(() => { if (!abort.signal.aborted) setBusy(false); }); return () => abort.abort(); }, [company, token]);
 useEffect(() => { const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } }; window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn); }, [dirty]);
 const current = rules.find(rule => rule.id === selected);
 function change(next: Rule[]) { setRules(next); setDirty(true); setNotice(""); }
 function patch(value: Partial<Rule>) { change(rules.map(rule => rule.id === selected ? { ...rule, ...value } : rule)); }
 function add(copy?: Rule) { const id = crypto.randomUUID(); change([...rules, copy ? { ...structuredClone(copy), id, title: `${copy.title} (copy)`, enabled: false } : { id, title: "New question", question: "", enabled: false, item_ids: [], words: [], photo: true, answers: ["Yes", "No"].map(label => ({ id: crypto.randomUUID(), label, action: "none", notice: "", acknowledge: false })) }]); setSelected(id); }
 function move(index: number, direction: number) { const next = [...rules]; [next[index], next[index + direction]] = [next[index + direction], next[index]]; change(next); }
 async function save() { setBusy(true); setNotice(""); try { const r = await fetch(`${API_BASE}/api/customer-questions/${company}`, { method: "PUT", headers: { ...authHeaders(token), "Content-Type": "application/json" }, body: JSON.stringify({ rules, revision }) }); const body = await r.json(); if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Check each question: select matching items and add explanations for answer actions."); setRules(body.rules); setRevision(body.revision); setDirty(false); setNotice("Moving terms saved."); } catch (e) { setNotice((e as Error).message); } finally { setBusy(false); } }
 const matches = (item: Item) => !!current && (current.item_ids.includes(item.id) || current.item_ids.some(id => normalize(catalog.find(row => row.id === id)?.name || "") === normalize(item.name)) || current.words.some(word => normalize(word) && ` ${normalize(item.name)} `.includes(` ${normalize(word)} `)));
 return <section className="cq-manager">
  <header className="cq-toolbar"><div><h2>Moving terms</h2><p>Item restrictions, preparation requirements, and acknowledgments shown after service choices.</p></div><button className="slds-button slds-button_brand" disabled={busy || !dirty || !revision} onClick={() => void save()}>{busy ? "Please wait..." : "Save moving terms"}</button></header>
  <label className="cq-company">Company<select value={company} disabled={busy} onChange={e => { if (!dirty || window.confirm("Discard unsaved question changes?")) setCompany(e.target.value); }}>{companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
  {notice && <p role="status" className="cq-notice">{notice}</p>}
  <div className="cq-layout"><aside><button className="slds-button slds-button_neutral" disabled={busy || !company || !revision} onClick={() => add()}>+ Add question</button>{rules.map((rule, index) => <div className={`cq-rule ${rule.id === selected ? "is-selected" : ""}`} key={rule.id}><button className="slds-button" onClick={() => setSelected(rule.id)}>{rule.title}<small>{rule.enabled ? "Enabled" : "Disabled"}</small></button><div><button className="slds-button" aria-label={`Move ${rule.title} up`} disabled={busy || index === 0} onClick={() => move(index, -1)}>Up</button><button className="slds-button" aria-label={`Move ${rule.title} down`} disabled={busy || index === rules.length - 1} onClick={() => move(index, 1)}>Down</button></div></div>)}</aside>
  {current ? <fieldset disabled={busy} className="cq-editor"><div className="cq-toolbar"><label><input type="checkbox" checked={current.enabled} onChange={e => patch({ enabled: e.target.checked })} /> Enabled</label><div><button type="button" className="slds-button" onClick={() => add(current)}>Duplicate</button><button type="button" className="slds-button" onClick={() => { if (window.confirm("Delete this question?")) { change(rules.filter(r => r.id !== current.id)); setSelected(""); } }}>Delete</button></div></div>
    <label>Internal title<input value={current.title} maxLength={200} onChange={e => patch({ title: e.target.value })} placeholder="Live plants" /></label>
    <label>Customer question<textarea value={current.question} maxLength={500} onChange={e => patch({ question: e.target.value })} placeholder="Is this a live plant?" /></label>
    <div className="cq-block"><div className="cq-toolbar"><h3>Which items?</h3><label><input type="checkbox" checked={!!current.all_items} onChange={e => patch({ all_items: e.target.checked })} /> All items</label></div>{current.all_items ? <p>Ask once for the whole move. Customers select the applicable inventory items when an answer includes instructions or an action.</p> : <><p>Pick catalog items. Reports with the same item name also match.</p><input aria-label="Search inventory catalog" type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search catalog, e.g. plant" />
    <button type="button" className="slds-button cq-add-catalog" onClick={() => setAddingCatalogItem(true)}>+ Add catalog item</button>
    <div className="cq-chips">{catalog.filter(item => current.item_ids.includes(item.id)).map(item => <button className="slds-button" key={item.id} onClick={() => patch({ item_ids: current.item_ids.filter(id => id !== item.id) })}>{item.name} - Remove</button>)}</div>
    <div className="cq-catalog">{catalog.filter(item => normalize(item.name).includes(normalize(search))).map(item => <label key={item.id}><input type="checkbox" checked={current.item_ids.includes(item.id)} onChange={e => patch({ item_ids: e.target.checked ? [...current.item_ids, item.id] : current.item_ids.filter(id => id !== item.id) })} />{item.name}<small>{item.cuft} cu ft</small></label>)}</div>
    <label>Optional matching words, separated by commas<input value={current.words.join(",")} onChange={e => patch({ words: e.target.value.split(",") })} placeholder="plant, potted tree" /></label><p>Matches whole words or phrases in custom items and report names.</p>
    <details><summary>Preview catalog matches ({catalog.filter(matches).length})</summary><div className="cq-catalog">{catalog.filter(matches).map(item => <div key={item.id}>{item.name}</div>)}</div></details>
    <label>Test a custom or report item name<input value={testName} onChange={e => setTestName(e.target.value)} placeholder="Large potted plant" /></label>{testName && <p>{matches({ id: "", name: testName, cuft: 0 }) ? "This item matches." : "This item does not match."}</p>}</>}</div>
    {!current.all_items && <label><input type="checkbox" checked={current.photo} onChange={e => patch({ photo: e.target.checked })} /> Show the item's report photo when available</label>}
    <h3>Answers and next steps</h3>{current.answers.map((answer, index) => { const update = (value: Partial<Answer>) => patch({ answers: current.answers.map((a, i) => i === index ? { ...a, ...value } : a) }); return <div className="cq-block" key={answer.id}><label>Answer<input value={answer.label} maxLength={100} onChange={e => update({ label: e.target.value })} /></label><label>What happens?<select value={answer.action} onChange={e => update({ action: e.target.value })}>{Object.entries(actions).map(([value, label]) => <option value={value} key={value}>{current.all_items && value === "none" ? "No instructions needed" : label}</option>)}</select></label>{answer.action !== "none" && <label>Explanation shown to the customer<textarea value={answer.notice} maxLength={2000} onChange={e => update({ notice: e.target.value })} placeholder="Explain your company policy and what the customer needs to do." /></label>}<label><input type="checkbox" checked={answer.acknowledge} onChange={e => update({ acknowledge: e.target.checked })} /> Customer must acknowledge the instructions</label>{current.answers.length > 2 && <button className="slds-button" onClick={() => patch({ answers: current.answers.filter(a => a.id !== answer.id) })}>Remove answer</button>}</div>; })}
    {current.answers.length < 8 && <button className="slds-button slds-button_neutral" onClick={() => patch({ answers: [...current.answers, { id: crypto.randomUUID(), label: "New answer", action: "none", notice: "", acknowledge: false }] })}>+ Add answer choice</button>}
    <details className="cq-preview"><summary>Customer preview</summary>{!current.all_items && <p><strong>{catalog.find(item => current.item_ids.includes(item.id))?.name || testName || "Matching item"}</strong> - Living Room</p>}<h3>{current.question || "Your question appears here"}</h3>{current.answers.map(answer => <details key={answer.id}><summary>{answer.label}</summary>{answer.notice && <p>{answer.notice}</p>}{answer.acknowledge && <small>I understand these instructions.</small>}</details>)}</details>
  </fieldset> : <p className="cq-empty">Add a question or select one to edit. New questions start disabled.</p>}</div>
 {addingCatalogItem && <CatalogItemDialog initialName={search} onClose={() => setAddingCatalogItem(false)} onSaved={item => {
   setCatalog(rows => [...rows.filter(row => row.id !== item.id), item]);
   if (current) patch({ item_ids: [...current.item_ids, item.id] });
   setSearch(item.name); setAddingCatalogItem(false);
   setNotice(`${item.name} added to the catalog and selected. Save moving terms to keep this question's selection.`);
 }} />}
 </section>;
}
