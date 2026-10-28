import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";
import { displayPhone } from "./leadUtils";
import { readRecentLeads, type RecentLead } from "./recentLeads";
import "./GlobalLeadSearch.css";

type SearchLead = RecentLead;

const MIN_LENGTH = 2;
const PAGE_SIZE = 8;

function isTypingTarget(target: EventTarget | null) {
  const element = target as HTMLElement | null;
  return !!element && (element.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName));
}

// Marks the first match of the query. Digit-only queries also match through phone formatting.
function Highlight({ text, query }: { text: string; query: string }) {
  const needle = query.trim().toLowerCase();
  if (!needle || !text) return <>{text}</>;
  let start = text.toLowerCase().indexOf(needle);
  let end = start + needle.length;
  const digits = needle.replace(/\D/g, "");
  if (start < 0 && digits.length >= MIN_LENGTH && digits === needle.replace(/[\s()+.-]/g, "")) {
    const positions: number[] = [];
    for (let index = 0; index < text.length; index += 1) if (/\d/.test(text[index])) positions.push(index);
    const found = positions.map((index) => text[index]).join("").indexOf(digits);
    if (found >= 0) {
      start = positions[found];
      end = positions[found + digits.length - 1] + 1;
    }
  }
  if (start < 0) return <>{text}</>;
  return <>{text.slice(0, start)}<mark>{text.slice(start, end)}</mark>{text.slice(end)}</>;
}

// Uses the leads list endpoint, which only returns leads the signed-in user may access.
export default function GlobalLeadSearch() {
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchLead[]>([]);
  const [recent, setRecent] = useState<SearchLead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const text = query.trim();
  const searching = text.length >= MIN_LENGTH;
  const items = searching ? results : recent;
  const showAll = searching && total > 0;
  const optionCount = items.length + (showAll ? 1 : 0);

  useEffect(() => {
    if (!searching) {
      setResults([]);
      setTotal(0);
      setLoading(false);
      setError("");
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({ search: text, limit: String(PAGE_SIZE) });
        const res = await fetch(`${API_BASE}/api/leads?${params}`, { headers: authHeaders(token), signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setResults(Array.isArray(data.items) ? data.items : []);
        setTotal(Number(data.total) || 0);
        setActive(0);
        setError("");
      } catch (reason) {
        if (controller.signal.aborted) return;
        setResults([]);
        setTotal(0);
        setError(reason instanceof Error ? reason.message : "Search failed");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 300);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [text, searching, token]);

  useEffect(() => {
    function onMouseDown(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    }
    // "/" or Ctrl/Cmd+K jumps to search from any page.
    function onKeyDown(event: KeyboardEvent) {
      const shortcut = (event.key === "k" && (event.ctrlKey || event.metaKey)) || (event.key === "/" && !isTypingTarget(event.target));
      if (!shortcut) return;
      event.preventDefault();
      inputRef.current?.focus();
      inputRef.current?.select();
    }
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  function openPanel() {
    setRecent(readRecentLeads(user?.id));
    setActive(0);
    setOpen(true);
  }

  function close() {
    setOpen(false);
    setQuery("");
    inputRef.current?.blur();
  }

  const leadUrl = (lead: SearchLead) => `/leads/${lead.id}`;
  const allResultsUrl = `/?${new URLSearchParams({ search: text })}`;

  // Results are real links, so Ctrl/Cmd+click, middle-click and "Open in new tab" work natively.
  function go(url: string, newTab: boolean) {
    if (newTab) {
      window.open(url, "_blank", "noopener");
      return;
    }
    close();
    navigate(url);
  }

  // A plain click navigates in place and closes the panel; modified clicks are left to the browser.
  function onLinkClick(event: React.MouseEvent, url: string) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    go(url, false);
  }

  function choose(index: number, newTab: boolean) {
    if (index < items.length) go(leadUrl(items[index]), newTab);
    else if (showAll) go(allResultsUrl, newTab);
  }

  const showPanel = open && (searching || recent.length > 0);

  return (
    <div className="global-search" ref={boxRef}>
      <svg className="global-search-icon" aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
      <input
        ref={inputRef}
        type="text"
        value={query}
        placeholder="Search leads"
        aria-label="Search leads by name, phone, email or quote number"
        aria-expanded={showPanel}
        aria-controls="global-search-results"
        aria-activedescendant={showPanel && optionCount ? `global-search-option-${active}` : undefined}
        aria-autocomplete="list"
        role="combobox"
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => { setQuery(event.target.value); setActive(0); setOpen(true); }}
        onFocus={openPanel}
        onKeyDown={(event) => {
          if (event.key === "Escape") close();
          else if (event.key === "ArrowDown") { event.preventDefault(); setActive((i) => Math.min(i + 1, optionCount - 1)); }
          else if (event.key === "ArrowUp") { event.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
          else if (event.key === "Enter") {
            event.preventDefault();
            const newTab = event.ctrlKey || event.metaKey;
            if (optionCount) choose(active, newTab);
            else if (searching) go(allResultsUrl, newTab);
          }
        }}
      />
      {loading ? <span className="global-search-spinner" role="status" aria-label="Searching" /> : null}
      {query && !loading ? (
        <button type="button" className="global-search-clear" aria-label="Clear search" onClick={() => { setQuery(""); inputRef.current?.focus(); }}>
          <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M2 2l8 8M10 2l-8 8" /></svg>
        </button>
      ) : null}
      {!query && !open ? <kbd className="global-search-hint" aria-hidden="true">/</kbd> : null}

      {showPanel ? (
        <div className="global-search-panel" id="global-search-results" role="listbox" aria-label={searching ? "Search results" : "Recent leads"}>
          {!searching ? <div className="global-search-heading">Recent leads</div> : null}
          {searching && loading && !results.length ? <div className="global-search-note">Searching...</div> : null}
          {searching && error ? <div className="global-search-note global-search-error">Search failed. Try again.</div> : null}
          {searching && !loading && !error && !results.length ? <div className="global-search-note">No leads match "{text}".</div> : null}
          {items.map((lead, index) => {
            const details = [
              lead.quote_number ? `#${lead.quote_number}` : "",
              lead.phone_number ? displayPhone(lead.phone_number) : "",
              lead.email || "",
              lead.company_name || "",
            ].filter(Boolean);
            return (
              <Link
                key={lead.id}
                id={`global-search-option-${index}`}
                to={leadUrl(lead)}
                role="option"
                aria-selected={index === active}
                className={`global-search-result${index === active ? " is-active" : ""}`}
                onMouseEnter={() => setActive(index)}
                onClick={(event) => onLinkClick(event, leadUrl(lead))}
              >
                <span className="global-search-name"><Highlight text={lead.full_name || "Unnamed lead"} query={searching ? text : ""} /></span>
                {lead.status ? <span className={`global-search-status is-${lead.status}`}>{lead.status}</span> : null}
                {details.length ? (
                  <span className="global-search-meta">
                    {details.map((detail, detailIndex) => (
                      <Fragment key={detailIndex}>
                        {detailIndex ? <span className="global-search-dot" aria-hidden="true" /> : null}
                        <span className="global-search-detail"><Highlight text={detail} query={searching ? text : ""} /></span>
                      </Fragment>
                    ))}
                  </span>
                ) : null}
              </Link>
            );
          })}
          {showAll ? (
            <Link
              id={`global-search-option-${items.length}`}
              to={allResultsUrl}
              role="option"
              aria-selected={active === items.length}
              className={`global-search-all${active === items.length ? " is-active" : ""}`}
              onMouseEnter={() => setActive(items.length)}
              onClick={(event) => onLinkClick(event, allResultsUrl)}
            >
              See all {total.toLocaleString()} {total === 1 ? "result" : "results"} for "{text}"
              <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 2l4 4-4 4" /></svg>
            </Link>
          ) : null}
          <div className="global-search-footer" aria-hidden="true">
            <span><kbd>&uarr;</kbd><kbd>&darr;</kbd> to move</span>
            <span><kbd>Enter</kbd> to open</span>
            <span><kbd>Ctrl</kbd>+<kbd>Enter</kbd> new tab</span>
            <span><kbd>Esc</kbd> to close</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
