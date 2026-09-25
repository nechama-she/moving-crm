import { useEffect, useRef, useState } from 'react';
import type { EditableReportFile } from './ReportFileList';
import './ReportFileGallery.css';
function Tile({ file, loadPreview, onOpen }: { file: EditableReportFile; loadPreview: (id: string) => Promise<string | null>; onOpen: (url: string) => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openError, setOpenError] = useState(false);
  const [failed, setFailed] = useState(false);
  const loader = useRef(loadPreview);
  const tile = useRef<HTMLButtonElement>(null);
  const video = file.content_type?.startsWith('video/') || /\.(mp4|mov|webm|m4v)$/i.test(file.name);
  useEffect(() => {
    let active = true;
    setUrl(null); setFailed(false);
    if (!file.content_type?.startsWith('image/') && !video) return;
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      loader.current(file.id).then(value => { if (active) setUrl(value); }).catch(() => { if (active) setFailed(true); });
    });
    if (tile.current) observer.observe(tile.current);
    return () => { active = false; observer.disconnect(); };
  }, [file.id, file.content_type, video]);
  const image = url && !failed;
  return <button ref={tile} type="button" className={`cm-gallery-preview${video ? ' cm-gallery-video' : ''}`} title={file.name} aria-label={`Open ${file.name}`} aria-busy={loading} disabled={loading} onClick={async () => {
    setLoading(true); setOpenError(false);
    try { const fresh = await loadPreview(file.id); if (!fresh) throw new Error('Unavailable'); onOpen(fresh); }
    catch { setOpenError(true); }
    finally { setLoading(false); }
  }}>
    {image ? video ? <video src={url} muted playsInline preload="metadata" aria-hidden="true" onLoadedMetadata={event => { const player = event.currentTarget; if (Number.isFinite(player.duration) && player.duration > 0) player.currentTime = Math.min(0.1, player.duration / 2); }} onError={() => setFailed(true)} /> : <img src={url} alt={file.name} loading="lazy" onError={() => setFailed(true)} /> : <span className="cm-gallery-fallback">
      {!video && <svg width="30" height="34" viewBox="0 0 24 28" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M4 1h10l6 6v20H4zM14 1v7h6M8 14h8M8 19h8" /></svg>}
      {file.content_type?.startsWith('image/') ? 'Photo' : video ? 'Video' : file.name.split('.').pop()?.toUpperCase() || 'File'}</span>}
    {video && <span className="cm-gallery-play" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8 4v16l13-8z" /></svg></span>}
    <span className="cm-gallery-name">{loading ? 'Opening...' : openError ? 'Could not open. Click to retry.' : file.name}</span>
  </button>;
}
export default function ReportFileGallery({ files, loadPreview, onRemove, disabled, newFileIds = [], selectedIds, onSelectionChange, onDownload, title = "Media" }: {
  title?: string;
  selectedIds?: string[]; onSelectionChange?: (ids: string[]) => void; onDownload?: () => void;
  newFileIds?: string[];
  files: EditableReportFile[]; loadPreview: (id: string) => Promise<string | null>; onRemove: (id: string) => Promise<void>; disabled: boolean;
}) {
  const [removing, setRemoving] = useState('');
  const [error, setError] = useState('');
  const [open, setOpen] = useState<{ url: string; name: string; type: string }>();
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(undefined); if (event.key === 'Tab') { const items = Array.from(close.current?.parentElement?.querySelectorAll<HTMLElement>('button, a[href], video, audio, iframe') || []); const first = items[0], last = items[items.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); } } };
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('keydown', escape); previous?.focus(); };
  }, [open]);
  async function remove(id: string) {
    setRemoving(id); setError('');
    try { await onRemove(id); } catch (err) { setError(err instanceof Error ? err.message : 'Could not delete file.'); } finally { setRemoving(''); }
  }
  return <section className="cm-gallery" aria-label="Files for your report">
    <div className="cm-gallery-heading"><strong>{title} <span>({files.length})</span></strong>{onSelectionChange && <div className="cm-gallery-toolbar"><button type="button" disabled={disabled} onClick={() => onSelectionChange(files.map(file => file.id))}>Select all</button><button type="button" disabled={disabled} onClick={() => onSelectionChange([])}>Deselect all</button><button type="button" disabled={disabled || !selectedIds?.length} onClick={onDownload} title="Download selected files" aria-label="Download selected files">&#8595; Download</button><small>{selectedIds?.length || 0} selected</small></div>}</div>
    {error && <p role="alert">{error}</p>}{removing && <p role="status">Deleting file...</p>}
    {!files.length && <p>No files yet. Add photos, documents, or videos above.</p>}
    <div className="cm-gallery-grid">{files.map(file => <div className="cm-gallery-tile" key={file.id}>
      <Tile file={file} loadPreview={loadPreview} onOpen={url => setOpen({ url, name: file.name, type: file.content_type || '' })} />
      {newFileIds.includes(file.id) && <span className="cm-gallery-new" title="New file for the next report">New</span>}
      {onSelectionChange ? <input className="cm-gallery-select" type="checkbox" aria-label={`Select ${file.name}`} checked={selectedIds?.includes(file.id) || false} disabled={disabled} onChange={event => onSelectionChange(event.target.checked ? [...(selectedIds || []), file.id] : (selectedIds || []).filter(id => id !== file.id))} /> : <button type="button" className="cm-gallery-delete" title={`Delete ${file.name}`} aria-label={`Delete ${file.name}`} disabled={disabled || !!removing} onClick={() => void remove(file.id)}><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg></button>}
    </div>)}</div>
    {open && <div className="cm-gallery-lightbox" role="dialog" aria-modal="true" aria-label={open.name} onClick={() => setOpen(undefined)}><button ref={close} type="button" aria-label="Close file preview" onClick={() => setOpen(undefined)}>&times;</button><figure onClick={event => event.stopPropagation()}>{open.type.startsWith('image/') && open.type !== 'image/svg+xml' ? <img src={open.url} alt={open.name} /> : open.type.startsWith('video/') || /\.(mp4|mov|webm|m4v)$/i.test(open.name) ? <video src={open.url} controls playsInline autoPlay tabIndex={0} onError={() => setError('This video format cannot play here. Use Open / download file.')} /> : open.type.startsWith('audio/') ? <audio src={open.url} controls tabIndex={0} /> : open.type === 'application/pdf' ? <iframe src={open.url} title={open.name} /> : <p>Open or download this file using the link below.</p>}
      <p><a href={open.url} target="_blank" rel="noopener noreferrer" download={open.url.startsWith('data:') ? open.name : undefined} style={{color:'white'}}>Open / download file</a></p><figcaption>{open.name}</figcaption></figure></div>}
  </section>;
}
