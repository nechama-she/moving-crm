import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { API_BASE } from './apiConfig';
import { authHeaders, useAuth } from './AuthContext';
import './CompanyDocumentsPage.css';

type Company = { id: string; name: string };
type CompanyDocument = { key: string; title: string; body_html: string; move_type: string; enabled: boolean; revision: number };

export default function CompanyDocumentsPage() {
  const { token } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [documents, setDocuments] = useState<CompanyDocument[]>([]);
  const [draft, setDraft] = useState<CompanyDocument>();
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [preview, setPreview] = useState<string | null>(null);
  const [linkUrl, setLinkUrl] = useState('');
  const [linkOpen, setLinkOpen] = useState(false);
  const editor = useRef<HTMLDivElement>(null);
  const selection = useRef<Range | null>(null);
  const base = `${API_BASE}/api/companies/${companyId}/documents`;
  async function api(url: string, method = 'GET', body?: unknown, signal?: AbortSignal) {
    const response = await fetch(url, { method, headers: { ...authHeaders(token), 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to save or load the document.');
    return data;
  }
  useEffect(() => {
    const controller = new AbortController();
    api(`${API_BASE}/api/companies`, 'GET', undefined, controller.signal).then(rows => { setCompanies(rows); setCompanyId(rows[0]?.id || ''); })
      .catch(e => { if (!controller.signal.aborted) setMessage(e.message); });
    return () => controller.abort();
  }, [token]);
  useEffect(() => {
    if (!companyId) return;
    const controller = new AbortController();
    setBusy(true); setDraft(undefined); setDocuments([]); setPreview(null); setLinkOpen(false); setMessage('');
    api(base, 'GET', undefined, controller.signal).then(data => { setDocuments(data.items); setDraft(data.items[0]); setDirty(false); })
      .catch(e => { if (!controller.signal.aborted) setMessage(e.message); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [companyId, token]);
  useEffect(() => {
    if (editor.current) editor.current.innerHTML = draft?.body_html || '';
  }, [draft?.key, draft?.revision]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  function maySwitch() { return !dirty || window.confirm('Discard your unsaved document changes?'); }
  function update(values: Partial<CompanyDocument>) {
    setDraft(current => current ? { ...current, ...values } : current); setDirty(true); setPreview(null); setMessage('');
  }
  function command(name: string, value?: string) {
    editor.current?.focus(); document.execCommand(name, false, value);
    update({ body_html: editor.current?.innerHTML || '' });
  }
  async function save() {
    if (!draft) return;
    setBusy(true); setMessage('');
    try {
      const saved = await api(`${base}/${draft.key}`, 'PUT', draft);
      setDocuments(current => [...current.filter(row => row.key !== saved.key), saved]);
      setDraft(saved); setDirty(false); setMessage('Document saved.');
    } catch (e) { setMessage((e as Error).message); }
    finally { setBusy(false); }
  }
  return <main className="company-documents">
    <Link to="/settings">Back to Settings</Link><h1>Company documents</h1>
    <p>Documents are appended to matching estimates. Signed copies keep the wording originally reviewed.</p>
    <label>Company<select value={companyId} disabled={busy} onChange={e => { if (maySwitch()) setCompanyId(e.target.value); }}>
      {companies.map(company => <option key={company.id} value={company.id}>{company.name}</option>)}
    </select></label>
    <div className="company-documents-layout"><nav aria-label="Company documents">
      {documents.map(row => <button key={row.key} type="button" disabled={busy} aria-current={draft?.key === row.key ? 'page' : undefined} onClick={() => { if (maySwitch()) { setDraft(row); setDirty(false); setPreview(null); setLinkOpen(false); } }}>{row.title}{!row.enabled && ' (disabled)'}</button>)}
      <button type="button" disabled={!companyId || busy} onClick={() => { if (maySwitch()) { setDraft({ key: crypto.randomUUID(), title: 'New document', body_html: '', move_type: 'Long Distance', enabled: true, revision: 0 }); setDirty(true); setPreview(null); setLinkOpen(false); } }}>Add document</button>
    </nav>
    {draft && <section>
      <label>Document name<input value={draft.title} maxLength={200} disabled={busy} onChange={e => update({ title: e.target.value })} /></label>
      <div className="company-documents-options"><label>Include for<select value={draft.move_type} disabled={busy} onChange={e => update({ move_type: e.target.value })}><option>Long Distance</option><option>Local</option><option value="All">All moves</option></select></label>
        <label><input type="checkbox" checked={draft.enabled} disabled={busy} onChange={e => update({ enabled: e.target.checked })} /> Include in estimate</label></div>
      <p>Use <code>{'{{company_name}}'}</code> wherever the company name should appear. Phone numbers, emails and rates are editable text.</p>
      <div className="company-documents-toolbar" role="toolbar" aria-label="Document formatting">
        {[['Bold', 'bold'], ['Italic', 'italic'], ['Underline', 'underline'], ['Bullets', 'insertUnorderedList'], ['Numbered list', 'insertOrderedList']].map(([label, action]) => <button type="button" key={action} disabled={busy} onMouseDown={e => e.preventDefault()} onClick={() => command(action)}>{label}</button>)}
        <button type="button" disabled={busy} onMouseDown={e => e.preventDefault()} onClick={() => command('formatBlock', 'h3')}>Heading</button>
        <button type="button" disabled={busy} onMouseDown={e => e.preventDefault()} onClick={() => command('formatBlock', 'p')}>Paragraph</button>
        <button type="button" disabled={busy} onMouseDown={e => e.preventDefault()} onClick={() => {
          const current = window.getSelection();
          if (!current?.rangeCount || !editor.current?.contains(current.anchorNode)) { setMessage('Select the text to turn into a link first.'); return; }
          selection.current = current.getRangeAt(0).cloneRange(); setLinkUrl(''); setLinkOpen(true);
        }}>Add link</button>
        <button type="button" disabled={busy} onMouseDown={e => e.preventDefault()} onClick={() => command('unlink')}>Remove link</button>
        <button type="button" disabled={busy} onMouseDown={e => e.preventDefault()} onClick={() => command('insertText', '{{company_name}}')}>Company name</button>
      </div>
      {linkOpen && <div className="company-documents-link"><label>Link URL<input autoFocus type="text" value={linkUrl} placeholder="https://example.com" onChange={e => setLinkUrl(e.target.value)} /></label><button type="button" onClick={() => {
        if (!/^(https?:\/\/|mailto:|tel:)/i.test(linkUrl.trim())) { setMessage('Use an https://, http://, mailto: or tel: link.'); return; }
        editor.current?.focus(); const current = window.getSelection(); current?.removeAllRanges(); if (selection.current) current?.addRange(selection.current);
        command('createLink', linkUrl.trim()); setLinkOpen(false);
      }}>Apply link</button><button type="button" onClick={() => setLinkOpen(false)}>Cancel</button></div>}
      <div ref={editor} contentEditable={!busy} suppressContentEditableWarning role="textbox" aria-label="Document text" aria-multiline="true" className="company-documents-editor"
        onInput={() => update({ body_html: editor.current?.innerHTML || '' })}
        onPaste={e => { e.preventDefault(); command('insertText', e.clipboardData.getData('text/plain')); }}
        onDrop={e => e.preventDefault()} />
      <div className="company-documents-actions"><button type="button" disabled={busy || !dirty || !draft.title.trim()} onClick={() => void save()}>{busy ? 'Working...' : 'Save document'}</button>
        <button type="button" disabled={busy || !draft.title.trim()} onClick={async () => { setBusy(true); try { const result = await api(`${base}/preview`, 'POST', draft); setPreview(result.body_html); } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); } }}>Preview</button>
        {dirty && <span>Unsaved changes</span>}</div>
      {preview !== null && <article className="company-documents-preview"><h2>Preview</h2><div dangerouslySetInnerHTML={{ __html: preview }} /></article>}
    </section>}
    </div><p role="status">{message || (busy ? 'Loading...' : '')}</p>
  </main>;
}
