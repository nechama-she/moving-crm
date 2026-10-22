import { useEffect, useRef, useState } from 'react';
import EstimateSigning from './EstimateSigning';
import './EstimateViewer.css';

export default function EstimateViewer({ base, headers, customerName, version, url, error, onClose }: {
  base: string; headers: Record<string, string>; customerName: string; version: string;
  url: string; error: string; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [signing, setSigning] = useState(false);
  const [signed, setSigned] = useState(false);
  const [signedUrl, setSignedUrl] = useState('');
  const [loadError, setLoadError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => () => { if (signedUrl) URL.revokeObjectURL(signedUrl); }, [signedUrl]);
  async function showSigned(id: string) {
    setSigned(true); setSigning(false); setLoadError('');
    try {
      const response = await fetch(`${base}/estimate-signatures/${encodeURIComponent(id)}/pdf`, { headers, cache: 'no-store' });
      if (!response.ok) throw new Error('Your signature is saved, but the signed PDF could not load. Try again.');
      setSignedUrl(URL.createObjectURL(await response.blob()));
    } catch (e) { setLoadError((e as Error).message); }
  }
  return <dialog ref={dialog} className="estimate-viewer" aria-labelledby="estimate-viewer-title" onCancel={e => { e.preventDefault(); if (!signing) onClose(); }}>
    <header className="estimate-viewer-header">
      <div><h2 id="estimate-viewer-title">Your estimate</h2><p>{signed ? 'Your signature has been saved.' : 'Review your estimate, then sign here.'}</p></div>
      <div className="estimate-viewer-actions">
        {url && version && !signed && <button className="cm-primary" onClick={() => setSigning(true)}>Sign estimate</button>}
        {(signedUrl || (!signed && url)) && <a className="cm-secondary-btn" href={signedUrl || url} download={signed ? 'signed-estimate.pdf' : 'estimate.pdf'}>Download PDF</a>}
        <button className="cm-secondary-btn" disabled={signing} onClick={onClose} aria-label="Close estimate">Close</button>
      </div>
    </header>
    {error && <p role="alert">{error}</p>}
    {loadError && <p role="alert">{loadError} <button className="cm-secondary-btn" onClick={() => void showSigned(version)}>Retry signed PDF</button></p>}
    <div className="estimate-viewer-content">
      {url ? <iframe title={signedUrl ? 'Signed estimate PDF' : 'Estimate PDF'} src={signedUrl || url} /> : !error && <p role="status">Preparing your latest estimate...</p>}
      {signing && <aside><EstimateSigning base={base} headers={headers} customerName={customerName} disabled={false} version={version} hideHistory onClose={() => setSigning(false)} onSigned={id => void showSigned(id)} /></aside>}
    </div>
  </dialog>;
}
