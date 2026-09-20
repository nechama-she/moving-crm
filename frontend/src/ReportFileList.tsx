import { useState } from 'react';
import './ReportFileList.css';
export type EditableReportFile = { id: string; name: string; size?: number; content_type?: string };
export default function ReportFileList({ files, onRemove, disabled = false }: {
  files: EditableReportFile[]; onRemove: (id: string) => Promise<void>; disabled?: boolean;
}) {
  const [removing, setRemoving] = useState('');
  const [error, setError] = useState('');
  async function remove(id: string) {
    setRemoving(id); setError('');
    try { await onRemove(id); }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not delete file.'); }
    finally { setRemoving(''); }
  }
  return <section className="report-file-list" aria-label="Files for the next report">
    <div className="report-file-heading"><strong>Files for your report</strong><span>{files.length}</span></div>
    <p>Add or delete files, then generate your report. Previous reports keep their files.</p>
    {error && <p role="alert">{error}</p>}
    {removing && <p role="status">Deleting file...</p>}
    {!files.length && <p>No files selected. Add photos, documents, or videos above.</p>}
    {files.map(file => <div className="report-file-row" key={file.id}>
      <span title={file.name}>{file.name}</span>
      <button type="button" className="slds-button" title={`Delete ${file.name}`} aria-label={`Delete ${file.name}`} disabled={disabled || !!removing} onClick={() => void remove(file.id)}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg>
      </button>
    </div>)}
  </section>;
}
