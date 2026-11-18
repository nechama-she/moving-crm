import { useEffect, useRef, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Company = { id: string; name: string };
type Template = { id: string; name: string; body: string; override: string | null; sort_order: number };
type Placeholder = { token: string; label: string; group: string };
// A field of the Fields tab: whether the @ list offers it.
type Field = Placeholder & { enabled: boolean };
// The field list open while typing @ in a text box: which box, where the @ is, and what follows it.
type Mention = { id: string; start: number; query: string; active: number };

const DEFAULT_ID = "__default__";
const GROUPS = ["Lead info", "Company info", "Rep info"];

// "@" right before the caret, starting a word (not inside an email address), and the letters typed after it.
function mentionAt(text: string, caret: number): { start: number; query: string } | null {
  const match = /(^|[^A-Za-z0-9])@([A-Za-z]*)$/.exec(text.slice(0, caret));
  return match ? { start: caret - match[2].length - 1, query: match[2] } : null;
}

// Message templates users pick when writing to a lead. Each has a default text; a company can have its own.
export default function MessageTemplatesPage() {
  const { token, user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState(DEFAULT_ID);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [placeholders, setPlaceholders] = useState<Placeholder[]>([]);
  // What is being edited, per template: name and text (the company's own text when a company is chosen).
  const [drafts, setDrafts] = useState<Record<string, { name: string; text: string }>>({});
  const [newName, setNewName] = useState("");
  const [newBody, setNewBody] = useState("");
  const [loading, setLoading] = useState(false);
  const [savingId, setSavingId] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [mention, setMention] = useState<Mention | null>(null);
  const [tab, setTab] = useState<"templates" | "fields">("templates");
  // Every field there is, loaded each time the Fields tab opens.
  const [allFields, setAllFields] = useState<Field[] | null>(null);
  const boxes = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const editingDefault = companyId === DEFAULT_ID;

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/companies/mine`, { headers: authHeaders(token) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as Company[];
        setCompanies((data || []).sort((a, b) => a.name.localeCompare(b.name)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load companies");
      }
    })();
  }, [token]);

  useEffect(() => {
    void load(companyId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  function showTemplates(items: Template[], forDefault: boolean) {
    setTemplates(items);
    setDrafts(Object.fromEntries(items.map((item) => [item.id, { name: item.name, text: forDefault ? item.body : item.override || "" }])));
  }

  async function load(cid: string) {
    setLoading(true);
    setError("");
    setInfo("");
    try {
      const query = cid === DEFAULT_ID ? "" : `?company_id=${encodeURIComponent(cid)}`;
      const res = await fetch(`${API_BASE}/api/message-templates${query}`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { templates: Template[]; placeholders: Placeholder[] };
      setPlaceholders(data.placeholders || []);
      showTemplates(data.templates || [], cid === DEFAULT_ID);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load templates");
    } finally {
      setLoading(false);
    }
  }

  async function request(path: string, method: string, body?: unknown) {
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { ...authHeaders(token), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
    }
    return res.json();
  }

  async function run(id: string, action: () => Promise<void>, done: string) {
    setSavingId(id);
    setError("");
    setInfo("");
    try {
      await action();
      setInfo(done);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSavingId("");
    }
  }

  const addTemplate = () => run("new", async () => {
    const created = (await request("/api/message-templates", "POST", { name: newName.trim(), body: newBody })) as Template;
    // Only the new one is added: unsaved edits in the others stay.
    setTemplates((current) => [...current, created]);
    setDrafts((current) => ({ ...current, [created.id]: { name: created.name, text: created.body } }));
    setNewName("");
    setNewBody("");
  }, "Template added.");

  const saveTemplate = (template: Template) => run(template.id, async () => {
    const draft = drafts[template.id];
    const saved = (editingDefault
      ? await request(`/api/message-templates/${template.id}`, "PUT", { name: draft.name.trim(), body: draft.text })
      : await request(`/api/message-templates/${template.id}/companies/${companyId}`, "PUT", { body: draft.text })) as Template;
    setTemplates((current) => current.map((item) => (item.id === saved.id ? saved : item)));
    if (!editingDefault && !saved.override) setDrafts((current) => ({ ...current, [saved.id]: { ...current[saved.id], text: "" } }));
  }, "Saved.");

  // The company goes back to the default text at once (its own version is removed).
  const switchToDefault = (template: Template) => run(template.id, async () => {
    const saved = (await request(`/api/message-templates/${template.id}/companies/${companyId}`, "PUT", { body: "" })) as Template;
    setTemplates((current) => current.map((item) => (item.id === saved.id ? saved : item)));
    setDrafts((current) => ({ ...current, [saved.id]: { ...current[saved.id], text: "" } }));
  }, "This company now uses the default.");

  const deleteTemplate = (template: Template) => {
    if (!window.confirm(`Delete the template "${template.name}" for every company?`)) return;
    void run(template.id, async () => {
      await request(`/api/message-templates/${template.id}`, "DELETE");
      // Only this one is removed: unsaved edits in the others stay.
      setTemplates((current) => current.filter((item) => item.id !== template.id));
      setDrafts((current) => Object.fromEntries(Object.entries(current).filter(([id]) => id !== template.id)));
    }, "Template deleted.");
  };

  async function openFields() {
    setTab("fields");
    setAllFields(null);
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/message-templates/fields`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { fields: Field[] };
      setAllFields(data.fields || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load fields");
    }
  }

  // On or off at once; the @ list follows. A failed save puts the switch back.
  async function switchField(field: Field, enabled: boolean) {
    const apply = (value: boolean) => setAllFields((current) => (current || []).map((item) => (item.token === field.token ? { ...item, enabled: value } : item)));
    apply(enabled);
    setError("");
    setInfo("");
    try {
      await request(`/api/message-templates/fields/${encodeURIComponent(field.token)}`, "PUT", { enabled });
      setPlaceholders((current) => {
        const others = current.filter((item) => item.token !== field.token);
        if (!enabled) return others;
        const order = (allFields || []).map((item) => item.token);
        return [...others, { token: field.token, label: field.label, group: field.group }]
          .sort((a, b) => order.indexOf(a.token) - order.indexOf(b.token));
      });
    } catch (err) {
      apply(!enabled);
      setError(err instanceof Error ? err.message : "Failed to save");
    }
  }

  const fieldsPanel = allFields === null ? <div style={{ padding: 24, color: "#706e6b" }}>Loading...</div> : (
    <div style={{ display: "grid", gap: 14 }}>
      {GROUPS.map((group) => {
        const items = allFields.filter((item) => item.group === group);
        if (!items.length) return null;
        return (
          <section key={group} style={card}>
            <h2 style={sectionHeader}>{group}</h2>
            <div style={{ marginTop: 6 }}>
              {items.map((item) => (
                <label key={item.token} style={fieldRow}>
                  <span style={{ minWidth: 0 }}>
                    <span style={{ display: "block", fontSize: 13, fontWeight: 600, color: "#0f172a" }}>{item.label}</span>
                    <span style={fieldToken}>@{item.token}</span>
                  </span>
                  <input type="checkbox" role="switch" checked={item.enabled} disabled={!isAdmin}
                    onChange={(event) => void switchField(item, event.target.checked)}
                    aria-label={`Offer ${group} ${item.label} in the @ list`} style={{ width: 18, height: 18, flex: "0 0 auto", cursor: "pointer" }} />
                </label>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );

  // The fields matching what follows the @, in the list's order: Lead info, Company info, Rep info.
  const matches = (query: string) => {
    const needle = query.toLowerCase();
    return GROUPS.flatMap((group) => placeholders.filter((item) => item.group === group
      && (!needle || item.token.toLowerCase().includes(needle) || item.label.toLowerCase().includes(needle))));
  };

  // After each change or caret move: the list opens on "@", follows what is typed after it, and closes otherwise.
  function followCaret(id: string, element: HTMLTextAreaElement) {
    const found = mentionAt(element.value, element.selectionStart);
    setMention((current) => (found ? { id, ...found, active: current && current.id === id && current.start === found.start ? current.active : 0 } : null));
  }

  function pick(id: string, value: string, onChange: (value: string) => void, item: Placeholder) {
    const element = boxes.current[id];
    if (!element || !mention) return;
    const caret = element.selectionStart;
    const inserted = `@${item.token} `;
    onChange(value.slice(0, mention.start) + inserted + value.slice(caret));
    setMention(null);
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(mention.start + inserted.length, mention.start + inserted.length);
    });
  }

  const textBox = (id: string, value: string, onChange: (value: string) => void, placeholder = "") => {
    const open = mention && mention.id === id ? mention : null;
    const options = open ? matches(open.query) : [];
    const active = open ? Math.min(open.active, Math.max(0, options.length - 1)) : 0;
    return (
      <div style={{ position: "relative" }}>
        <textarea
          ref={(element) => { boxes.current[id] = element; }}
          value={value}
          onChange={(event) => { onChange(event.target.value); followCaret(id, event.currentTarget); }}
          onClick={(event) => followCaret(id, event.currentTarget)}
          onKeyUp={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key === "Home" || event.key === "End") followCaret(id, event.currentTarget); }}
          onKeyDown={(event) => {
            if (!open || !options.length) return;
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              const step = event.key === "ArrowDown" ? 1 : options.length - 1;
              setMention({ ...open, active: (active + step) % options.length });
            } else if (event.key === "Enter" || event.key === "Tab") {
              event.preventDefault();
              pick(id, value, onChange, options[active]);
            } else if (event.key === "Escape") {
              event.preventDefault();
              setMention(null);
            }
          }}
          // Closed a moment after leaving the box: on a touch screen the box can lose focus before the tap on a
          // field registers, and the list must still be there to receive it.
          onBlur={() => window.setTimeout(() => setMention((current) => (current && current.id === id ? null : current)), 200)}
          disabled={!isAdmin}
          placeholder={placeholder}
          rows={6}
          role="combobox"
          aria-expanded={!!open && options.length > 0}
          aria-autocomplete="list"
          style={textarea}
        />
        {open && options.length > 0 && (
          <div role="listbox" aria-label="Fields" style={fieldList}>
            {GROUPS.map((group) => {
              const items = options.filter((item) => item.group === group);
              if (!items.length) return null;
              return (
                <div key={group}>
                  <div style={fieldGroup}>{group}</div>
                  {items.map((item) => {
                    const selected = options[active] === item;
                    return (
                      <button key={item.token} type="button" role="option" aria-selected={selected}
                        onMouseDown={(event) => event.preventDefault()} onClick={() => pick(id, value, onChange, item)}
                        style={{ ...fieldOption, background: selected ? "#e8f1fb" : "#fff" }}>
                        <span>{item.label}</span>
                        <span style={fieldToken}>@{item.token}</span>
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ padding: "20px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Message Templates</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b", fontSize: 13 }}>
        Messages to pick from when texting a lead. Write the default for all companies, or give one company its own version.
      </p>

      <div role="tablist" aria-label="Message templates" style={{ display: "flex", gap: 4, borderBottom: "1px solid #dddbda", marginBottom: 14 }}>
        <button type="button" role="tab" aria-selected={tab === "templates"} className="slds-button"
          onClick={() => { setTab("templates"); setError(""); setInfo(""); }} style={tab === "templates" ? tabActive : tabButton}>Templates</button>
        <button type="button" role="tab" aria-selected={tab === "fields"} className="slds-button"
          onClick={() => void openFields()} style={tab === "fields" ? tabActive : tabButton}>Fields</button>
      </div>

      {tab === "fields" ? (
        <p style={{ ...desc, marginBottom: 14 }}>
          Choose which fields the @ list offers when writing a template. A field added to the system later starts off. Turning one off does not change templates already using it.
        </p>
      ) : (<>
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 12 }}>
        <label htmlFor="message-template-company" style={{ fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>Company</label>
        <select id="message-template-company" value={companyId} onChange={(event) => setCompanyId(event.target.value)}
          style={{ padding: "6px 8px", border: "1px solid #c9c7c5", borderRadius: 4, fontSize: 13, minWidth: 240, maxWidth: "100%" }}>
          <option value={DEFAULT_ID}>Default (all companies)</option>
          {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
        </select>
        {!isAdmin && <span style={{ color: "#ba0517", fontSize: 12 }}>Read-only: admin required to save.</span>}
      </div>

      <p style={{ ...desc, marginBottom: 14 }}>
        Type @ in a message to add lead, company or rep info. It is filled in with the lead's details when the template is picked.
      </p>
      </>)}

      {error && <div style={errorBox}>{error}</div>}
      {info && <div style={infoBox}>{info}</div>}

      {tab === "fields" ? fieldsPanel : loading ? <div style={{ padding: 24, color: "#706e6b" }}>Loading...</div> : (
        <div style={{ display: "grid", gap: 14 }}>
          {templates.length === 0 && <div style={{ ...card, color: "#706e6b", fontSize: 13 }}>No templates yet.{editingDefault && isAdmin ? " Add the first one below." : ""}</div>}
          {templates.map((template) => {
            const draft = drafts[template.id] || { name: template.name, text: "" };
            const ownText = !editingDefault && !!template.override;
            return (
              <section key={template.id} style={card}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                  {editingDefault ? (
                    <input value={draft.name} disabled={!isAdmin} aria-label="Template name" maxLength={120}
                      onChange={(event) => setDrafts((current) => ({ ...current, [template.id]: { ...draft, name: event.target.value } }))}
                      style={nameInput} />
                  ) : (
                    <div>
                      <h2 style={sectionHeader}>{template.name}</h2>
                      <p style={desc}>{ownText ? "This company's own version." : "Uses the default. Write here to give this company its own version."}</p>
                    </div>
                  )}
                  {isAdmin && (
                    <div style={{ display: "flex", gap: 6 }}>
                      {editingDefault && <button type="button" className="slds-button" disabled={savingId === template.id} onClick={() => deleteTemplate(template)} style={dangerButton}>Delete</button>}
                      {ownText && <button type="button" className="slds-button" disabled={savingId === template.id}
                        onClick={() => void switchToDefault(template)} style={ghostButton}>Use default</button>}
                      <button type="button" className="slds-button" disabled={savingId === template.id || (editingDefault && (!draft.name.trim() || !draft.text.trim()))}
                        onClick={() => void saveTemplate(template)} style={primaryButton}>{savingId === template.id ? "Saving..." : "Save"}</button>
                    </div>
                  )}
                </div>
                {textBox(template.id, draft.text, (text) => setDrafts((current) => ({ ...current, [template.id]: { ...draft, text } })),
                  editingDefault ? "" : "Same as the default. Leave blank to keep using it.")}
                {!editingDefault && (
                  <details style={{ marginTop: 6 }}>
                    <summary style={{ fontSize: 12, color: "#0176d3", cursor: "pointer" }}>{ownText ? "View default" : "View default (in use)"}</summary>
                    <pre style={defaultPre}>{template.body}</pre>
                  </details>
                )}
              </section>
            );
          })}

          {editingDefault && isAdmin && (
            <section style={card}>
              <h2 style={sectionHeader}>New template</h2>
              <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="Name, e.g. Follow-up after estimate"
                aria-label="New template name" maxLength={120} style={{ ...nameInput, marginTop: 6 }} />
              {textBox("new", newBody, setNewBody, "Message text")}
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                <button type="button" className="slds-button" disabled={savingId === "new" || !newName.trim() || !newBody.trim()} onClick={() => void addTemplate()} style={primaryButton}>
                  {savingId === "new" ? "Adding..." : "Add template"}
                </button>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

const card: React.CSSProperties = { border: "1px solid #dddbda", borderRadius: 4, background: "#fff", padding: 14, boxShadow: "0 1px 2px rgba(0,0,0,.06)" };
const sectionHeader: React.CSSProperties = { margin: "0 0 4px", fontSize: 13, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#3e3e3c" };
const desc: React.CSSProperties = { margin: 0, fontSize: 12, color: "#706e6b" };
const nameInput: React.CSSProperties = { flex: "1 1 240px", minWidth: 0, width: "100%", maxWidth: 420, padding: "6px 8px", border: "1px solid #c9c7c5", borderRadius: 4, fontSize: 13, fontWeight: 600, boxSizing: "border-box" };
const textarea: React.CSSProperties = { marginTop: 10, width: "100%", fontFamily: "inherit", fontSize: 13, lineHeight: 1.45, padding: 10, border: "1px solid #c9c7c5", borderRadius: 4, resize: "vertical", boxSizing: "border-box" };
const defaultPre: React.CSSProperties = { marginTop: 6, background: "#f3f3f3", border: "1px solid #e5e5e5", borderRadius: 4, padding: 10, fontSize: 12, whiteSpace: "pre-wrap", fontFamily: "inherit", color: "#3e3e3c" };
const fieldList: React.CSSProperties = { position: "absolute", left: 0, top: "100%", marginTop: 4, width: "min(320px, 100%)", maxHeight: 280, overflowY: "auto", background: "#fff", border: "1px solid #d8dde6", borderRadius: 6, boxShadow: "0 6px 18px rgba(15,23,42,.12)", zIndex: 10 };
const fieldGroup: React.CSSProperties = { padding: "8px 12px 4px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#706e6b" };
const fieldOption: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, width: "100%", padding: "7px 12px", border: "none", textAlign: "left", fontSize: 13, color: "#0f172a", cursor: "pointer" };
const fieldToken: React.CSSProperties = { fontSize: 12, color: "#0176d3", fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" };
const fieldRow: React.CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "8px 0", borderTop: "1px solid #eef1f5", cursor: "pointer" };
const tabButton: React.CSSProperties = { background: "transparent", color: "#3e3e3c", border: "none", borderBottom: "2px solid transparent", borderRadius: 0, padding: "8px 14px", fontSize: 13, fontWeight: 600, cursor: "pointer", marginBottom: -1 };
const tabActive: React.CSSProperties = { ...tabButton, color: "#0176d3", borderBottom: "2px solid #0176d3" };
const ghostButton: React.CSSProperties = { background: "#fff", color: "#0176d3", border: "1px solid #0176d3", borderRadius: 4, padding: "6px 12px", fontSize: 12, fontWeight: 600, cursor: "pointer" };
const dangerButton: React.CSSProperties = { ...ghostButton, color: "#ba0517", border: "1px solid #ba0517" };
const primaryButton: React.CSSProperties = { background: "#0176d3", color: "#fff", border: "none", borderRadius: 4, padding: "7px 14px", fontSize: 13, fontWeight: 600, cursor: "pointer" };
const errorBox: React.CSSProperties = { marginBottom: 12, padding: 10, background: "#fdecea", border: "1px solid #f5b7b1", borderRadius: 4, color: "#ba0517", fontSize: 13 };
const infoBox: React.CSSProperties = { marginBottom: 12, padding: 10, background: "#e8f4fd", border: "1px solid #b6dffb", borderRadius: 4, color: "#0176d3", fontSize: 13 };
