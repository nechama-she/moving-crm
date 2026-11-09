import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE } from "../apiConfig";
import { authHeaders, useAuth } from "../AuthContext";
import { displayPhone } from "../leadUtils";
import { readRecentLeads, type RecentLead } from "../recentLeads";
import Icon from "./Icon";
import { initials } from "./initials";
import type { NavItem } from "./navItems";

type AskItem = { id: string; name: string; detail: string; value: string; flag: string; tone: "good" | "warn" };
type AskResult = { answer: string; detail?: string; items?: AskItem[]; actions?: string[] };
type AskState = { status: "idle" } | { status: "loading"; question: string } | { status: "done"; question: string; result: AskResult } | { status: "unavailable"; question: string };

const LEAD_MIN_LENGTH = 2;
const LEAD_LIMIT = 6;

const SUGGESTIONS = [
  "Which quotes should I chase today?",
  "Who is waiting longest for a reply?",
  "Quoted leads moving next week over $5k",
];

// Whether the server has the assistant. Its route takes POST only, so once it exists a plain GET answers
// 405 (Method Not Allowed); until then it is 404 and the "Ask the CRM" part stays hidden. Checked once per visit.
let assistantCheck: Promise<boolean> | null = null;
function hasAssistant(token: string | null) {
  assistantCheck ||= fetch(`${API_BASE}/api/ai/ask`, { headers: authHeaders(token) })
    .then(r => r.status === 405 || (r.ok && (r.headers.get("content-type") || "").includes("json")))
    .catch(() => false);
  return assistantCheck;
}

export default function CommandPalette({ open, onClose, pages }: { open: boolean; onClose: () => void; pages: NavItem[] }) {
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const [ask, setAsk] = useState<AskState>({ status: "idle" });
  const [assistant, setAssistant] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // Leads come from the leads list endpoint, which only returns leads the signed-in user may access.
  const [recent, setRecent] = useState<RecentLead[]>([]);
  const [leadResults, setLeadResults] = useState<{ text: string; items: RecentLead[]; total: number; failed?: boolean } | null>(null);
  const text = query.trim();
  const searchingLeads = text.length >= LEAD_MIN_LENGTH;

  useEffect(() => {
    if (!open) return;
    setQuery(""); setSelected(0); setAsk({ status: "idle" }); setLeadResults(null);
    setRecent(readRecentLeads(user?.id));
    void hasAssistant(token).then(setAssistant);
    const id = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open, user?.id, token]);

  useEffect(() => {
    if (!open || !searchingLeads) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({ search: text, limit: String(LEAD_LIMIT) });
        const res = await fetch(`${API_BASE}/api/leads?${params}`, { headers: authHeaders(token), signal: controller.signal });
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        setLeadResults({ text, items: Array.isArray(data.items) ? data.items : [], total: Number(data.total) || 0 });
      } catch {
        if (!controller.signal.aborted) setLeadResults({ text, items: [], total: 0, failed: true });
      }
    }, 250);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [open, searchingLeads, text, token]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return pages.filter(p => !q || `${p.label} ${p.keywords || ""}`.toLowerCase().includes(q)).slice(0, 6);
  }, [pages, query]);

  async function runAsk(question: string) {
    const text = question.trim();
    if (!text) return;
    setQuery(text);
    setAsk({ status: "loading", question: text });
    try {
      const res = await fetch(`${API_BASE}/api/ai/ask`, {
        method: "POST",
        headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setAsk({ status: "done", question: text, result: await res.json() });
    } catch {
      setAsk({ status: "unavailable", question: text });
    }
  }

  function go(to: string, newTab = false) {
    if (newTab) { window.open(to, "_blank", "noopener"); return; }
    onClose(); navigate(to);
  }

  if (!open) return null;
  const leadsLoading = searchingLeads && leadResults?.text !== text;
  const leads = searchingLeads ? (leadsLoading ? [] : leadResults?.items || []) : recent;
  const leadTotal = searchingLeads && !leadsLoading ? leadResults?.total || 0 : 0;
  const allLeadsUrl = `/?${new URLSearchParams({ search: text })}`;
  // One list for the arrow keys: leads, "see all", pages, then the question.
  const options = [
    ...leads.map(lead => ({ to: `/leads/${encodeURIComponent(lead.id)}` })),
    ...(leadTotal > leads.length ? [{ to: allLeadsUrl }] : []),
    ...matches.map(p => ({ to: p.to })),
    ...(text && assistant ? [{ to: "" }] : []),
  ];
  const optionCount = options.length;
  const pageStart = leads.length + (leadTotal > leads.length ? 1 : 0);

  return (
    <div className="aur-palette-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="aur-palette" role="dialog" aria-modal="true" aria-label={assistant ? "Search and ask the CRM" : "Search the CRM"}
        onKeyDown={e => {
          if (e.key === "Escape") { e.preventDefault(); onClose(); }
          if (e.key === "ArrowDown") { e.preventDefault(); setSelected(s => Math.min(s + 1, Math.max(optionCount - 1, 0))); }
          if (e.key === "ArrowUp") { e.preventDefault(); setSelected(s => Math.max(s - 1, 0)); }
          // Ctrl/Cmd+Enter opens the selected lead or page in a new tab.
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && ask.status === "idle" && options[selected]?.to) { e.preventDefault(); go(options[selected].to, true); }
        }}>
        <form className="aur-palette-input" onSubmit={e => {
          e.preventDefault();
          const option = ask.status === "idle" ? options[selected] : undefined;
          if (option?.to) go(option.to);
          else if (assistant) runAsk(query);
        }}>
          <span className="aur-palette-mark"><Icon name="spark" /></span>
          <input ref={inputRef} value={query} aria-label={assistant ? "Search leads and pages, or ask a question" : "Search leads and pages"}
            placeholder={assistant ? "Find a lead or page, or ask a question" : "Find a lead or page"}
            onChange={e => { setQuery(e.target.value); setSelected(0); if (ask.status !== "loading") setAsk({ status: "idle" }); }} />
          <kbd>Esc</kbd>
        </form>

        {ask.status === "idle" && (
          <div className="aur-palette-body">
            {(searchingLeads || leads.length > 0) && <div className="aur-palette-group" aria-live="polite">
              <span className="aur-palette-heading">{searchingLeads ? "Leads" : "Recent leads"}</span>
              {leadsLoading && <p className="aur-palette-status">Searching leads…</p>}
              {searchingLeads && !leadsLoading && leadResults?.failed && <p className="aur-palette-status">Lead search failed. Try again.</p>}
              {searchingLeads && !leadsLoading && !leadResults?.failed && !leads.length && <p className="aur-palette-status">{`No leads match “${text}”.`}</p>}
              {leads.map((lead, i) => {
                const details = [lead.quote_number ? `#${lead.quote_number}` : "", lead.phone_number ? displayPhone(lead.phone_number) : "", lead.email || "", lead.company_name || ""].filter(Boolean);
                return (
                  <button type="button" key={lead.id} className={`aur-palette-option is-lead${i === selected ? " is-selected" : ""}`} onMouseEnter={() => setSelected(i)}
                    onClick={e => go(options[i].to, e.ctrlKey || e.metaKey)}>
                    <span className="aur-avatar is-sm">{initials(lead.full_name || "")}</span>
                    <span className="aur-palette-lead"><strong>{lead.full_name || "Unnamed lead"}</strong>{details.length > 0 && <small>{details.join(" · ")}</small>}</span>
                    {lead.status && <span className={`aur-stage stage-${lead.status.toLowerCase()}`}>{lead.status}</span>}
                  </button>
                );
              })}
              {leadTotal > leads.length && (
                <button type="button" className={`aur-palette-option is-all${selected === leads.length ? " is-selected" : ""}`} onMouseEnter={() => setSelected(leads.length)} onClick={e => go(allLeadsUrl, e.ctrlKey || e.metaKey)}>
                  <Icon name="search" /><span>{`See all ${leadTotal.toLocaleString()} results for “${text}”`}</span><Icon name="arrow" size={16} />
                </button>
              )}
            </div>}
            {matches.length > 0 && <div className="aur-palette-group">
              <span className="aur-palette-heading">Go to</span>
              {matches.map((p, i) => (
                <button type="button" key={p.to} className={`aur-palette-option${pageStart + i === selected ? " is-selected" : ""}`} onMouseEnter={() => setSelected(pageStart + i)} onClick={() => go(p.to)}>
                  <Icon name={p.icon} /><span>{p.label}</span><Icon name="arrow" size={16} />
                </button>
              ))}
            </div>}
            {assistant && <div className="aur-palette-group">
              <span className="aur-palette-heading">Ask the CRM</span>
              {query.trim() ? (
                <button type="button" className={`aur-palette-option is-ask${selected === optionCount - 1 ? " is-selected" : ""}`} onMouseEnter={() => setSelected(optionCount - 1)} onClick={() => runAsk(query)}>
                  <Icon name="spark" /><span>{"Ask: “" + query.trim() + "”"}</span><kbd>Enter</kbd>
                </button>
              ) : SUGGESTIONS.map(s => (
                <button type="button" key={s} className="aur-palette-option is-ask" onClick={() => runAsk(s)}>
                  <Icon name="spark" /><span>{s}</span>
                </button>
              ))}
            </div>}
          </div>
        )}

        {ask.status === "loading" && <div className="aur-palette-body aur-palette-thinking" aria-live="polite"><span className="aur-dots" aria-hidden="true"><i /><i /><i /></span>{"Looking through leads, quotes and messages…"}</div>}

        {ask.status === "unavailable" && (
          <div className="aur-palette-body" aria-live="polite">
            <p className="aur-palette-note"><strong>{"The assistant isn’t connected yet."}</strong> Answers will appear here once it is enabled on the server.</p>
          </div>
        )}

        {ask.status === "done" && (
          <div className="aur-palette-body" aria-live="polite">
            <span className="aur-palette-heading is-accent">Answer</span>
            <p className="aur-answer">{ask.result.answer}</p>
            {ask.result.detail && <p className="aur-answer-detail">{ask.result.detail}</p>}
            {!!ask.result.items?.length && <ul className="aur-answer-list">
              {ask.result.items.map(item => (
                <li key={item.id}>
                  <button type="button" onClick={() => go(`/leads/${encodeURIComponent(item.id)}`)}>
                    <span className="aur-avatar is-sm">{initials(item.name)}</span>
                    <span className="aur-answer-name"><strong>{item.name}</strong><small>{item.detail}</small></span>
                    <span className={`aur-pill tone-${item.tone}`}>{item.flag}</span>
                    <span className="aur-answer-value">{item.value}</span>
                  </button>
                </li>
              ))}
            </ul>}
            {!!ask.result.actions?.length && <div className="aur-answer-actions">
              {ask.result.actions.map((a, i) => <button type="button" key={a} className={i === 0 ? "aur-btn is-primary" : "aur-btn"}>{a}</button>)}
            </div>}
          </div>
        )}

        <div className="aur-palette-foot"><span>{"↑ ↓ move"}</span><span>Enter open</span><span>Ctrl+Enter new tab</span>{assistant && <span className="aur-palette-foot-note">{"Answers use only your CRM data · actions always ask before sending"}</span>}</div>
      </div>
    </div>
  );
}

