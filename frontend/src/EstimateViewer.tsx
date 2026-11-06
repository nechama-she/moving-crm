import { useEffect, useRef, useState } from 'react';
import Signing, { type SignResult } from './Signing';

// The Re-sign answer: the signature removed, and the estimate's status without it.
export type SignatureRemoved = { removed_id: string; signature_status: 'unsigned' | 'signed' | 'changed'; work_order_available: boolean;
  bill_of_lading: { signed: boolean } | null };
import './PdfViewer.css';

export default function EstimateViewer({ base, headers, customerName, version, url, error, onClose, alreadySigned = false, approved = true, rep = false, onApproved, filename, onSignatureRemoved, onSigned }: {
  base: string; headers: Record<string, string>; customerName: string; version: string; filename: string;
  url: string; error: string; onClose: () => void;
  alreadySigned?: boolean;
  // Signing needs a rep's approval of this exact estimate; the rep view can give it.
  approved?: boolean; rep?: boolean; onApproved?: () => void;
  // Called once Re-sign removes the saved signature: the page opens the current estimate in its place,
  // so what is signed next is what the estimate is now, even if it changed elsewhere.
  onSignatureRemoved: (result: SignatureRemoved) => void;
  // Called once the signature is saved: the page shows the estimate signed right away.
  onSigned: (signature: SignResult) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [signing, setSigning] = useState(false);
  const [savedHere, setSigned] = useState(false);
  const [cleared, setCleared] = useState(false);
  const [clearing, setClearing] = useState(false);
  const signed = (!cleared && alreadySigned) || savedHere;
  const [signedUrl, setSignedUrl] = useState('');
  const [loadError, setLoadError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => () => { if (signedUrl) URL.revokeObjectURL(signedUrl); }, [signedUrl]);
  async function resign() {
    setClearing(true); setLoadError('');
    try {
      const response = await fetch(`${base}/estimate-signatures/${encodeURIComponent(version)}/resign`, { method: 'POST', headers, cache: 'no-store' });
      if (!response.ok) throw new Error('Could not remove the signature. Please try Re-sign again.');
      setCleared(true); setSigned(false);
      onSignatureRemoved(await response.json());
    } catch (e) { setLoadError((e as Error).message); }
    finally { setClearing(false); }
  }
  const [approving, setApproving] = useState(false);
  async function approve() {
    setApproving(true); setLoadError('');
    try {
      const response = await fetch(`${base}/estimate-signatures/${encodeURIComponent(version)}/approve`, { method: 'POST', headers, cache: 'no-store' });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not approve the estimate. Please try again.');
      onApproved?.();
    } catch (e) { setLoadError((e as Error).message); }
    finally { setApproving(false); }
  }
  async function showSigned(id: string) {
    setSigned(true); setSigning(false); setLoadError('');
    try {
      const response = await fetch(`${base}/estimate-signatures/${encodeURIComponent(id)}/pdf`, { headers, cache: 'no-store' });
      if (!response.ok) throw new Error('Your signature is saved, but the signed PDF could not load. Try again.');
      setSignedUrl(URL.createObjectURL(await response.blob()));
    } catch (e) { setLoadError((e as Error).message); }
  }
  return <dialog ref={dialog} className="pdf-viewer" aria-labelledby="estimate-viewer-title" onCancel={e => { e.preventDefault(); if (!signing && !clearing) onClose(); }}>
    <header className="pdf-viewer-header">
      <div><h2 id="estimate-viewer-title">Your estimate</h2><p>{signed ? 'Your signature has been saved.' : !approved ? (rep ? 'Review this estimate, then approve it for signing.' : 'Your moving team is reviewing this estimate. You can sign it once they approve it.') : 'Review your estimate, then sign here.'}</p></div>
      <div className="pdf-viewer-actions">
        {url && version && signed && <button className="cm-secondary-btn" disabled={clearing} onClick={() => void resign()} title="Remove the saved signature and sign this estimate again">{clearing ? 'Removing signature...' : 'Re-sign'}</button>}
        {url && version && !signed && !approved && rep && <button className="cm-primary" disabled={approving} onClick={() => void approve()}>{approving ? 'Approving...' : 'Approve for signing'}</button>}
        {url && version && !signed && approved && <button className="cm-primary" onClick={() => setSigning(true)}>Sign estimate</button>}
        {(signedUrl || ((!signed || alreadySigned) && url)) && <a className="cm-secondary-btn" href={signedUrl || url} download={filename}>Download PDF</a>}
        <button className="cm-secondary-btn" disabled={signing || clearing} onClick={onClose} aria-label="Close estimate">Close</button>
      </div>
    </header>
    {error && <p role="alert">{error}</p>}
    {loadError && <p role="alert">{loadError} <button className="cm-secondary-btn" onClick={() => void showSigned(version)}>Retry signed PDF</button></p>}
    <div className="pdf-viewer-content">
      {url ? <iframe title={signed ? 'Signed estimate PDF' : 'Estimate PDF'} src={signedUrl || url} /> : !error && <p role="status">Preparing your latest estimate...</p>}
      {signing && <aside><Signing base={base} headers={headers} customerName={customerName} disabled={false} version={version} hideHistory onClose={() => setSigning(false)} onSigned={signature => { onSigned(signature); void showSigned(signature.id); }} /></aside>}
    </div>
  </dialog>;
}
