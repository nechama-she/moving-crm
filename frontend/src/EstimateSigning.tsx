import { useEffect, useRef, useState, type PointerEvent } from 'react';
import './EstimateSigning.css';

type Point = [number, number];
type SignedEstimate = { id: string; name: string; signed_at: string };

export default function EstimateSigning({ base, headers, customerName, disabled, version, onClose, onSigned, hideHistory = false }: {
  base: string; headers: Record<string, string>; customerName: string; disabled: boolean; version: string; onClose: () => void;
  onSigned?: (id: string) => void; hideHistory?: boolean;
}) {
  const [name, setName] = useState(customerName);
  const [strokes, setStrokes] = useState<Point[][]>([]);
  const active = useRef<number | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [signed, setSigned] = useState<SignedEstimate[]>([]);
  const urls = useRef<string[]>([]);
  async function request(path: string, body?: unknown) {
    const response = await fetch(base + '/estimate-signatures' + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store',
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(typeof result.detail === 'string' ? result.detail : result.detail?.message || 'Unable to save or load this estimate. Please try again.');
    }
    return response;
  }
  useEffect(() => {
    if (hideHistory) return;
    let live = true;
    request('').then(r => r.json()).then(data => { if (live) setSigned(data.items); })
      .catch(e => { if (live) setError(e.message); });
    return () => { live = false; urls.current.forEach(url => URL.revokeObjectURL(url)); };
  }, [base, headers['x-public-session'], hideHistory]);
  async function preview(id: string) {
    const viewer = window.open('about:blank', '_blank');
    if (!viewer) { setError('Allow pop-ups to view the estimate.'); return; }
    viewer.opener = null;
    viewer.document.body.textContent = 'Loading estimate...';
    setBusy(true); setError('');
    try {
      const response = await request('/' + id + '/pdf');
      const url = URL.createObjectURL(await response.blob());
      urls.current.push(url);
      if (!viewer.closed) { viewer.location.replace(url);  }
    } catch (e) { viewer.close(); setError((e as Error).message); }
    finally { setBusy(false); }
  }
  useEffect(() => { setStrokes([]); setConsent(false); setError(''); }, [version]);
  async function sign() {
    setBusy(true); setError('');
    try {
      const result = await (await request('/' + version + '/sign', { name: name.trim(), consent, strokes })).json();
      setSigned(current => [{ id: result.id, name: name.trim(), signed_at: result.signed_at }, ...current.filter(row => row.id !== result.id)]);
      if (onSigned) onSigned(result.id); else onClose();
      setStrokes([]);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function point(event: PointerEvent<SVGSVGElement>): Point {
    const bounds = event.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height))];
  }
  const drawn = strokes.some(stroke => stroke.length > 1 && stroke.some(p => p[0] !== stroke[0][0] || p[1] !== stroke[0][1]));
  if (!version && !signed.length && !error) return null;
  return <section className="estimate-signing" aria-label="Estimate signature">
    {version && <h3>Sign your estimate</h3>}
    {version && <>
      <p>This saves your signature with the estimate version you review here. Later changes will not change this signed copy.</p>
      <label>Full name<input value={name} maxLength={200} disabled={busy} autoComplete="name" onChange={e => setName(e.target.value)} /></label>
      <p id="signature-help">Draw your signature below using your finger, mouse, or pen.</p>
      <svg viewBox="0 0 600 180" preserveAspectRatio="none" role="img" aria-label="Draw your signature" aria-describedby="signature-help"
        onPointerDown={e => { if (busy || active.current !== null) return; e.preventDefault(); active.current = e.pointerId; e.currentTarget.setPointerCapture(e.pointerId); const p = point(e); setStrokes(value => [...value, [p]]); }}
        onPointerMove={e => { if (busy || active.current !== e.pointerId) return; const p = point(e); setStrokes(value => value.map((stroke, i) => i === value.length - 1 && stroke.length < 1000 ? [...stroke, p] : stroke)); }}
        onPointerUp={() => { active.current = null; setStrokes(value => value.filter(stroke => stroke.length > 1)); }}
        onPointerCancel={() => { active.current = null; setStrokes(value => value.filter(stroke => stroke.length > 1)); }}>
        {strokes.map((stroke, i) => <polyline key={i} points={stroke.map(([x, y]) => `${x * 600},${y * 180}`).join(' ')} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />)}
      </svg>
      <button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => setStrokes([])}>Clear signature</button>
      <label className="estimate-signing-consent"><input type="checkbox" checked={consent} disabled={busy || disabled} onChange={e => setConsent(e.target.checked)} />I have reviewed this estimate and agree to sign it electronically.</label>
      <div className="estimate-signing-actions"><button type="button" className="cm-secondary-btn" disabled={busy || disabled || !consent || !name.trim() || !drawn} onClick={() => void sign()}>{busy ? 'Saving...' : 'Sign and save estimate'}</button>
        <button type="button" className="cm-secondary-btn" disabled={busy} onClick={onClose}>Cancel</button></div>
    </>}
    {error && <p role="alert">{error}</p>}
    {!hideHistory && !!signed.length && <div aria-live="polite"><h4>Signed estimates</h4>{signed.map(row => <div key={row.id} className="estimate-signing-history"><span>{row.name} · {new Date(row.signed_at).toLocaleString()}</span><button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => void preview(row.id)}>Download signed PDF</button></div>)}</div>}
  </section>;
}
