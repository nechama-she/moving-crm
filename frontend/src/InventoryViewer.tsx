import { useEffect, useRef } from 'react';
import './EstimateViewer.css';

// Shows a PDF to read and download: the inventory, or with its own title and text, the work order.
export default function InventoryViewer({ url, filename, onClose, title = 'Your inventory', description = 'Review your inventory. Download it if you want a copy.' }: {
  url: string; filename: string; onClose: () => void; title?: string; description?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="estimate-viewer" aria-labelledby="inventory-viewer-title" onCancel={e => { e.preventDefault(); onClose(); }}>
    <header className="estimate-viewer-header">
      <div><h2 id="inventory-viewer-title">{title}</h2><p>{description}</p></div>
      <div className="estimate-viewer-actions">
        <a className="cm-secondary-btn" href={url} download={filename}>Download PDF</a>
        <button className="cm-secondary-btn" onClick={onClose} aria-label={`Close ${title.toLowerCase()}`}>Close</button>
      </div>
    </header>
    <div className="estimate-viewer-content">
      <iframe title={`${title} PDF`} src={url} />
    </div>
  </dialog>;
}
