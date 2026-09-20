import { useEffect, useRef, useState } from 'react';
import type { EditableReportFile } from './ReportFileList';
import './ReportFileGallery.css';
function Tile({ file, loadPreview, onOpen }: { file: EditableReportFile; loadPreview: (id: string) => Promise<string | null>; onOpen: (url: string) => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const loader = useRef(loadPreview);
  useEffect(() => {
    let active = true;
    if (file.content_type?.startsWith('image/')) loader.current(file.id).then(value => { if (active) setUrl(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [file.id, file.content_type]);
  const image = url && !failed;
  return <button type="button" className="cm-gallery-preview" title={file.name} aria-label={image ? `View ${file.name}` : file.name} onClick={() => { if (image) onOpen(url); }}>
    {image ? <img src={url} alt={file.name} loading="lazy" onError={() => setFailed(true)} /> : <span className="cm-gallery-fallback">{file.content_type?.startsWith('image/') ? 'Photo' : file.content_type?.startsWith('video/') ? 'Video' : file.name.split('.').pop()?.toUpperCase() || 'File'}</span>}
    <span className="cm-gallery-name">{file.name}</span>
  </button>;
}
export default function ReportFileGallery({ files, loadPreview, onRemove, disabled }: {
  files: EditableReportFile[]; loadPreview: (id: string) => Promise<string | null>; onRemove: (id: string) => Promise<void>; disabled: boolean;
}) {
  const [removing, setRemoving] = useState('');
  const [error, setError] = useState('');
  const [open, setOpen] = useState<{ url: string; name: string }>();
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(undefined); if (event.key === 'Tab') { event.preventDefault(); close.current?.focus(); } };
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('keydown', escape); previous?.focus(); };
  }, [open]);
  async function remove(id: string) {
    setRemoving(id); setError('');
    try { await onRemove(id); } catch (err) { setError(err instanceof Error ? err.message : 'Could not delete file.'); } finally { setRemoving(''); }
  }
  return <section className="cm-gallery" aria-label="Files for your report">
    <div className="cm-gallery-heading"><strong>Media <span>({files.length})</span></strong><small>Add or delete files before generating your report.</small></div>
    {error && <p role="alert">{error}</p>}{removing && <p role="status">Deleting file...</p>}
    {!files.length && <p>No files yet. Add photos, documents, or videos above.</p>}
    <div className="cm-gallery-grid">{files.map(file => <div className="cm-gallery-tile" key={file.id}>
      <Tile file={file} loadPreview={loadPreview} onOpen={url => setOpen({ url, name: file.name })} />
      <button type="button" className="cm-gallery-delete" title={`Delete ${file.name}`} aria-label={`Delete ${file.name}`} disabled={disabled || !!removing} onClick={() => void remove(file.id)}><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg></button>
    </div>)}</div>
    {open && <div className="cm-gallery-lightbox" role="dialog" aria-modal="true" aria-label={open.name} onClick={() => setOpen(undefined)}><button ref={close} type="button" aria-label="Close photo preview" onClick={() => setOpen(undefined)}>&times;</button><figure onClick={event => event.stopPropagation()}><img src={open.url} alt={open.name} /><figcaption>{open.name}</figcaption></figure></div>}
  </section>;
}
