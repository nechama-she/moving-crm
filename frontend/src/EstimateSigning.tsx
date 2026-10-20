import { useEffect, useRef, useState, type PointerEvent } from 'react';
import './EstimateSigning.css';

type Point = [number, number];
type SignedEstimate = { id: string; name: string; signed_at: string };

export default function EstimateSigning({ base, headers, customerName, disabled }: {
  base: string; headers: Record<string, string>; customerName: string; disabled: boolean;
}) {
  const [version, setVersion] = useState('');
  const [name, setName] = useState(customerName);
  const [strokes, setStrokes] = useState<Point[][]>([]);
  const active = useRef<number | null>(null);
  const [reviewed, setReviewed] = useState(false);
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
    let live = true;
    request('').then(r => r.json()).then(data => { if (live) setSigned(data.items); })
      .catch(e => { if (live) setError(e.message); });
    return () => { live = false; urls.current.forEach(url => URL.revokeObjectURL(url)); };
  }, [base, headers['x-public-session']]);
  async function preview(id: string, signing = false) {
    const viewer = window.open('about:blank', '_blank');
    if (!viewer) { setError('Allow pop-ups to view the estimate.'); return; }
    viewer.opener = null;
    viewer.document.body.textContent = 'Loading estimate...';
    setBusy(true); setError('');
    try {
      const response = await request('/' + id + '/pdf');
      const url = URL.createObjectURL(await response.blob());
      urls.current.push(url);
      if (!viewer.closed) { viewer.location.replace(url); if (signing) setReviewed(true); }
    } catch (e) { viewer.close(); setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function prepare() {
    setBusy(true); setError('');
    try {
      const data = await (await request('', {})).json();
      setVersion(data.id); setStrokes([]); setReviewed(false); setConsent(false);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function sign() {
    setBusy(true); setError('');
    try {
      const result = await (await request('/' + version + '/sign', { name: name.trim(), consent, strokes })).json();
      setSigned(current => [{ id: result.id, name: name.trim(), signed_at: result.signed_at }, ...current.filter(row => row.id !== result.id)]);
      setVersion(''); setStrokes([]);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function point(event: PointerEvent<SVGSVGElement>): Point {
    const bounds = event.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height))];
  }
  const drawn = strokes.some(stroke => stroke.length > 1 && stroke.some(p => p[0] !== stroke[0][0] || p[1] !== stroke[0][1]));
  return <section className="estimate-signing" aria-label="Estimate signature">
    <h3>Sign your estimate</h3>
    {!version ? <button type="button" className="cm-secondary-btn" disabled={disabled || busy} onClick={() => void prepare()}>Review and sign estimate</button> : <>
      <p>This saves your signature with the estimate version you review here. Later changes will not change this signed copy.</p>
      <button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => void preview(version, true)}>Review this estimate PDF</button>
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
      <label className="estimate-signing-consent"><input type="checkbox" checked={consent} disabled={busy || !reviewed} onChange={e => setConsent(e.target.checked)} />I have reviewed this estimate and agree to sign it electronically.</label>
      {!reviewed && <p>Open the estimate PDF before signing.</p>}
      <div className="estimate-signing-actions"><button type="button" className="cm-secondary-btn" disabled={busy || !reviewed || !consent || !name.trim() || !drawn} onClick={() => void sign()}>{busy ? 'Saving...' : 'Sign and save estimate'}</button>
        <button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => setVersion('')}>Cancel</button></div>
    </>}
    {error && <p role="alert">{error}</p>}
    {!!signed.length && <div aria-live="polite"><h4>Signed estimates</h4>{signed.map(row => <div key={row.id} className="estimate-signing-history"><span>{row.name} · {new Date(row.signed_at).toLocaleString()}</span><button type="button" className="cm-secondary-btn" disabled={busy} onClick={() => void preview(row.id)}>Download signed PDF</button></div>)}</div>}
  </section>;
}
