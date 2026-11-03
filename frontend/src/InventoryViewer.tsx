import { useEffect, useRef } from 'react';
import './EstimateViewer.css';

export default function InventoryViewer({ url, filename, onClose }: { url: string; filename: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="estimate-viewer" aria-labelledby="inventory-viewer-title" onCancel={e => { e.preventDefault(); onClose(); }}>
    <header className="estimate-viewer-header">
      <div><h2 id="inventory-viewer-title">Your inventory</h2><p>Review your inventory. Download it if you want a copy.</p></div>
      <div className="estimate-viewer-actions">
        <a className="cm-secondary-btn" href={url} download={filename}>Download PDF</a>
        <button className="cm-secondary-btn" onClick={onClose} aria-label="Close inventory">Close</button>
      </div>
    </header>
    <div className="estimate-viewer-content">
      <iframe title="Inventory PDF" src={url} />
    </div>
  </dialog>;
}
