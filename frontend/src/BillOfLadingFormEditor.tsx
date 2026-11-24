import { useEffect, useRef, useState } from 'react';

// One part of the Bill of Lading's front page (bill_of_lading_form.py): the CRM draws the page from these, in order.
export type FormBlock = { area: string; kind: string; title: string; text: string; fill: string; note: string; align: string;
  size: number | null; height: number | null; width: number | null; space: number; spot: number | null };
type Option = { key: string; label: string };

const AREAS: [string, string][] = [['company', 'Company header (top left)'], ['order', 'Order boxes (top right)'], ['header', 'Title'], ['origin', 'Origin'], ['destination', 'Destination'],
  ['agent', 'Agent row'], ['left', 'Left column'], ['right', 'Right column']];
const KIND_LABELS: Record<string, string> = { field: 'Box', title: 'Title', bar: 'Black bar', paragraph: 'Paragraph', signature: 'Signature line',
  total: 'Total box', heading: 'Bold line', line: 'Line', option: 'Checkbox option', caption: 'Caption', charge: 'Charges row', summary: 'Summary row' };
// The kinds each area takes (bill_of_lading_form.KINDS), and what a new one starts with.
const AREA_KINDS: Record<string, string[]> = { company: ['line', 'heading'], order: ['field'], header: ['title'], origin: ['bar', 'field'], destination: ['bar', 'field'],
  agent: ['field'], left: ['paragraph', 'signature', 'total', 'heading', 'option', 'bar'], right: ['caption', 'bar', 'charge', 'paragraph', 'summary', 'signature'] };
const blank = (area: string, kind: string): FormBlock => ({ area, kind, title: '', text: '', fill: '', note: kind === 'charge' ? '$' : kind === 'signature' ? 'Date:' : '',
  align: kind === 'summary' ? 'right' : '', size: kind === 'paragraph' ? (area === 'left' ? 6 : 5.5) : kind === 'title' ? 14 : area === 'company' ? 8.5 : null,
  height: kind === 'signature' ? (area === 'left' ? 24 : 20) : kind === 'charge' ? 10.2 : kind === 'bar' && area !== 'origin' && area !== 'destination' ? (area === 'left' ? 13 : 10.5) : null,
  width: null, space: kind === 'paragraph' ? 4 : 0, spot: null });

/** The Bill of Lading's front page, part by part: change the wording and boxes, add, move or remove parts, and read a
 * mover's PDF once for its wording (a draft to check before saving). */
export default function BillOfLadingFormEditor({ blocks, fields, busy, onSave, onRead }: {
  blocks: FormBlock[]; fields: Option[]; busy: boolean; onSave: (blocks: FormBlock[]) => Promise<void>;
  onRead: (file: File) => Promise<{ blocks: FormBlock[]; unmatched: string[] } | null>;
}) {
  const [draft, setDraft] = useState(blocks);
  const [adding, setAdding] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState('');
  const file = useRef<HTMLInputElement>(null);
  // A saved form replaces the draft, unless the draft has changes of its own (the document's text saved meanwhile).
  const shown = useRef(blocks);
  useEffect(() => {
    setDraft(current => JSON.stringify(current) === JSON.stringify(shown.current) ? blocks : current);
    shown.current = blocks;
  }, [blocks]);
  const changed = JSON.stringify(draft) !== JSON.stringify(blocks);
  const update = (index: number, values: Partial<FormBlock>) => setDraft(current => current.map((row, at) => at === index ? { ...row, ...values } : row));
  // Up or down among its area's parts.
  const move = (index: number, step: -1 | 1) => setDraft(current => {
    const same = current.map((row, at) => [row, at] as const).filter(([row]) => row.area === current[index].area).map(([, at]) => at);
    const other = same[same.indexOf(index) + step];
    if (other === undefined) return current;
    const next = [...current];
    [next[index], next[other]] = [next[other], next[index]];
    return next;
  });
  // A layout number in points; blank for the part's usual one.
  const number = (title: string, key: 'size' | 'height' | 'width' | 'space', row: FormBlock, index: number) => <label className="bol-form-number">{title}
    <input type="number" step="0.1" min={0} value={row[key] ?? ''} disabled={busy}
      onChange={e => update(index, { [key]: e.target.value === '' ? (key === 'space' ? 0 : null) : Number(e.target.value) })} /></label>;
  const fillSelect = (row: FormBlock, index: number) => <label>Filled with<select value={row.fill} disabled={busy} onChange={e => update(index, { fill: e.target.value })}>
    <option value="">Blank, filled by hand</option>{fields.map(field => <option key={field.key} value={field.key}>{field.label}</option>)}</select></label>;

  return <section className="bol-form" aria-label="Bill of Lading form">
    <h2>Bill of Lading form</h2>
    <p>The first page, part by part. Words can show the company&apos;s details: {'{{company_name}}'}, {'{{company_office_street}}'}, {'{{company_office_city}}'}, {'{{company_phone}}'}, {'{{company_dot_number}}'}, {'{{company_mc_number}}'}. In paragraphs, &lt;b&gt;bold&lt;/b&gt;. The form must fit on one page.</p>
    <div className="company-documents-actions">
      <input ref={file} type="file" accept="application/pdf,.pdf" hidden onChange={async e => {
        const picked = e.target.files?.[0]; e.target.value = '';
        if (!picked) return;
        const result = await onRead(picked);
        if (!result) return;
        setDraft(result.blocks);
        setNotice(result.unmatched.length ? `Not matched to a paragraph here (add them by hand if needed): ${result.unmatched.join('; ')}` : 'All the PDF\'s paragraphs were matched.');
      }} />
      <button type="button" disabled={busy} title="Reads the mover's PDF once for its wording; the PDF is not kept" onClick={() => file.current?.click()}>Read wording from PDF</button>
      <button type="button" disabled={busy || !changed} onClick={() => void onSave(draft)}>{busy ? 'Working...' : 'Save form'}</button>
      {changed && <span>Unsaved form changes</span>}
    </div>
    {notice && <p role="status">{notice}</p>}
    {AREAS.map(([area, areaLabel]) => <fieldset key={area} className="bol-form-area"><legend>{areaLabel}</legend>
      {draft.map((row, index) => row.area === area && <div key={index} className="bol-form-block">
        <strong>{KIND_LABELS[row.kind] || row.kind}</strong>
        {row.kind === 'paragraph'
          ? <label className="bol-form-text">Wording<textarea value={row.text} rows={4} disabled={busy} onChange={e => update(index, { text: e.target.value })} /></label>
          : <label>{row.kind === 'field' || row.kind === 'total' ? 'Label' : 'Words'}<input value={row.title} disabled={busy} onChange={e => update(index, { title: e.target.value })} /></label>}
        {(row.kind === 'field' || row.kind === 'total') && fillSelect(row, index)}
        {row.kind === 'total' && <label>Small print<input value={row.note} disabled={busy} onChange={e => update(index, { note: e.target.value })} /></label>}
        {row.kind === 'total' && <label>Shows when empty<input value={row.text} disabled={busy} onChange={e => update(index, { text: e.target.value })} /></label>}
        {row.kind === 'charge' && <label>Amount box<input value={row.note} disabled={busy} onChange={e => update(index, { note: e.target.value })} /></label>}
        {row.kind === 'signature' && <label>Date label<input value={row.note} disabled={busy} onChange={e => update(index, { note: e.target.value })} /></label>}
        {row.kind === 'signature' && area === 'left' && <label>Signed by<select value={row.spot ?? ''} disabled={busy} onChange={e => update(index, { spot: e.target.value ? Number(e.target.value) : null })}>
          <option value="">By hand</option><option value="1">Customer, spot 1</option><option value="2">Customer, spot 2</option></select></label>}
        {row.kind === 'summary' && <label>Label side<select value={row.align} disabled={busy} onChange={e => update(index, { align: e.target.value })}><option value="left">Left</option><option value="right">Right</option></select></label>}
        {['paragraph', 'title', 'bar', 'heading', 'line'].includes(row.kind) && number('Text size', 'size', row, index)}
        {['signature', 'charge', 'bar'].includes(row.kind) && number('Height', 'height', row, index)}
        {row.area === 'agent' && number('Width', 'width', row, index)}
        {number('Space after', 'space', row, index)}
        <span className="bol-form-moves">
          <button type="button" disabled={busy} aria-label="Move up" onClick={() => move(index, -1)}>Up</button>
          <button type="button" disabled={busy} aria-label="Move down" onClick={() => move(index, 1)}>Down</button>
          <button type="button" disabled={busy} onClick={() => setDraft(current => current.filter((_, at) => at !== index))}>Remove</button>
        </span>
      </div>)}
      <div className="bol-form-add">
        <select aria-label={`Add to ${areaLabel}`} value={adding[area] || AREA_KINDS[area][0]} disabled={busy} onChange={e => setAdding(current => ({ ...current, [area]: e.target.value }))}>
          {AREA_KINDS[area].map(kind => <option key={kind} value={kind}>{KIND_LABELS[kind]}</option>)}</select>
        <button type="button" disabled={busy} onClick={() => setDraft(current => {
          // Added after the area's last part.
          const last = current.map(row => row.area).lastIndexOf(area);
          const next = [...current];
          next.splice(last + 1, 0, blank(area, adding[area] || AREA_KINDS[area][0]));
          return next;
        })}>Add</button>
      </div>
    </fieldset>)}
  </section>;
}
