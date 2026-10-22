import { useEffect, useId, useRef, useState } from 'react';
import './ReportHistory.css';
import ReportLinks from './ReportLinks';

export type ReportRun = {
  source?: string;
  rooms?: { name: string; items: { name: string; amount: number; cuft: number; not_shipping?: boolean }[] }[];
  id: string; status: string; created_at?: number; current: boolean; shareUrl?: string;
  cuft?: number; weight?: number;
  files?: { id: string; name: string; size?: number }[];
  inventory: { room?: string; name: string; amount: number; cuft: number; not_shipping?: boolean }[];
  processing?: { started_at: string; steps: { id: string; label: string; status: string; message?: string; error?: string }[] };
  signatures?: SignedReportEstimate[];
};
export type SignedReportEstimate = { id: string; name: string; signed_at: string };
export default function ReportHistory({ reports, onSelect, disabled = false, staff = false, fetchSignedPdf }: {
  reports: ReportRun[]; onSelect: (id: string) => Promise<void>; disabled?: boolean; staff?: boolean;
  fetchSignedPdf?: (signatureId: string) => Promise<Blob>;
}) {
  const name = useId();
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [opening, setOpening] = useState('');
  const pdfUrls = useRef<string[]>([]);
  useEffect(() => () => { pdfUrls.current.forEach(url => URL.revokeObjectURL(url)); }, []);
  if (!reports.length) return null;
  async function openSignedPdf(signatureId: string) {
    if (!fetchSignedPdf) return;
    // Open the tab during the click so pop-up blockers allow it, then load the PDF into it.
    const viewer = window.open('about:blank', '_blank');
    if (!viewer) { setError('Allow pop-ups to view the signed estimate.'); return; }
    viewer.opener = null;
    viewer.document.body.textContent = 'Loading signed estimate...';
    setOpening(signatureId); setError('');
    try {
      const url = URL.createObjectURL(await fetchSignedPdf(signatureId));
      pdfUrls.current.push(url);
      if (!viewer.closed) viewer.location.replace(url);
    } catch (err) {
      viewer.close();
      setError(err instanceof Error ? err.message : 'Could not open the signed estimate.');
    } finally { setOpening(''); }
  }
  const signedLabel = (signature: SignedReportEstimate) => `Signed ${new Date(signature.signed_at).toLocaleString()}`;
  function signatureCell(report: ReportRun) {
    const latest = report.signatures?.[0];
    if (latest) return <div className="report-history-signature">
      <span>{signedLabel(latest)}{(report.signatures?.length || 0) > 1 && <small> and {report.signatures!.length - 1} earlier</small>}</span>
      {fetchSignedPdf && <button type="button" disabled={!!opening} onClick={() => void openSignedPdf(latest.id)} aria-label={`Open signed PDF, ${signedLabel(latest)}`}>{opening === latest.id ? 'Opening...' : 'Signed PDF'}</button>}
    </div>;
    if (report.current && report.status === 'completed') return <div className="report-history-signature report-history-unsigned">Not signed</div>;
    return <div className="report-history-signature report-history-signature-none" aria-label="No signature">{'—'}</div>;
  }
  const waiting = reports.some(report => report.current && ['queued', 'running'].includes(report.status));
  async function select(id: string) {
    setPending(id); setError('');
    try { await onSelect(id); }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not select this report.'); }
    finally { setPending(''); }
  }
  return <section id="inventory-history" className={`report-history ${staff ? 'report-history-crm' : ''}`} aria-label="Inventory report history">
    <details className="report-history-disclosure">
    <summary className="report-history-heading"><strong>Report history</strong><span>{reports.length} {reports.length === 1 ? 'report' : 'reports'}</span></summary>
    <p>View previous reports or expand a row to use it for pricing. Current marks the report used for your estimate.</p>
    {waiting && <p role="status">Your new report is processing. You can choose an earlier report once it finishes.</p>}
    {error && <p className="report-history-error" role="alert">{error}</p>}
    {pending && <p role="status">Updating inventory and price...</p>}
    <div className="report-history-column-headings" aria-hidden="true"><span>Date &amp; time</span><span>Source</span><span>Volume</span><span>Status</span><span>Signature</span><span>Reports</span></div>
    {reports.map(report => <div className="report-history-run" key={report.id} data-current={report.current}>
      <div className="report-history-row">
      <button type="button" className="report-history-toggle" aria-expanded={!!expanded[report.id]} aria-controls={`${name}-${report.id}`} onClick={() => setExpanded(previous => ({ ...previous, [report.id]: !previous[report.id] }))}>
        <span className="report-history-date"><span aria-hidden="true">{expanded[report.id] ? '\u25be' : '\u25b8'}</span> {report.created_at ? new Date(report.created_at * 1000).toLocaleString() : 'Earlier report'}</span>
        <span className="report-history-summary"><span className="report-history-source">{report.source === 'manual' ? 'List' : report.source === 'combined' ? 'Virtual tour + List' : 'Virtual tour'}</span><span className="report-history-volume">{report.cuft != null ? `${report.cuft.toLocaleString()} cu ft` : '\u2014'}</span><span className="report-history-state"><span className="report-history-status">{report.status}</span>{report.current && <b>Current</b>}</span></span>
      </button>
      {signatureCell(report)}
      <ReportLinks report={report} />
      </div>
      <div id={`${name}-${report.id}`} hidden={!expanded[report.id]} className="report-history-detail">
        {report.source === 'combined' && <p>Total volume combines the virtual tour and the itemized list. The virtual tour link includes only the media report.</p>}
        <div className="report-history-actions">
          <label><input type="radio" name={name} checked={report.current} disabled={disabled || !!pending || waiting || report.status !== 'completed' || (!report.shareUrl && report.source !== 'manual')} onChange={() => void select(report.id)} />{report.current ? 'Current report for pricing' : 'Use this report for pricing'}</label>

        </div>
        {(report.signatures?.length || 0) > 1 && <div className="report-history-signatures"><h5>Signed estimates for this report</h5>{report.signatures!.map(signature => <p key={signature.id}><span>{signature.name} {'·'} {signedLabel(signature)}</span>{fetchSignedPdf && <button type="button" disabled={!!opening} onClick={() => void openSignedPdf(signature.id)} aria-label={`Open signed PDF, ${signedLabel(signature)}`}>{opening === signature.id ? 'Opening...' : 'Signed PDF'}</button>}</p>)}</div>}
        {report.source !== 'manual' && report.files && <details className="report-history-files"><summary>{report.files.length} files used in this run</summary>{report.files.map(file => <p key={file.id}>{file.name}</p>)}</details>}
        {report.inventory.length > 0 ? <div className="report-history-table"><table><thead><tr><th>Item</th><th>Qty</th><th>Cu ft</th></tr></thead><tbody>{report.inventory.map((item, index) => <tr key={index}><td>{item.name}{item.not_shipping && <small style={{ display: 'block' }}>Not shipping</small>}{item.room && <small style={{ display: 'block' }}>{item.room}</small>}</td><td>{item.amount}</td><td>{item.cuft}</td></tr>)}</tbody></table></div> : <p>Open the report to view its inventory. Saved details appear after it is imported.</p>}
        {staff && report.processing && <div className="report-history-processing"><h5>Processing steps</h5>{report.processing.steps.map(step => <div key={step.id}>{step.error ? <details><summary>{step.label} <span>Failed - view error</span></summary><pre>{step.error}</pre></details> : <p><span>{step.label}</span><span>{step.status.replace(/_/g, ' ')}</span></p>}{step.message && <small>{step.message}</small>}</div>)}</div>}
      </div>
    </div>)}
    </details>
  </section>;
}
