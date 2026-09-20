import { useId, useState } from 'react';
import './ReportHistory.css';

export type ReportRun = {
  source?: string;
  id: string; status: string; created_at?: number; current: boolean; shareUrl?: string;
  cuft?: number; weight?: number;
  files?: { id: string; name: string; size?: number }[];
  inventory: { room?: string; name: string; amount: number; cuft: number }[];
  processing?: { started_at: string; steps: { id: string; label: string; status: string; message?: string; error?: string }[] };
};
export default function ReportHistory({ reports, onSelect, disabled = false, staff = false }: {
  reports: ReportRun[]; onSelect: (id: string) => Promise<void>; disabled?: boolean; staff?: boolean;
}) {
  const name = useId();
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  if (!reports.length) return null;
  const waiting = reports.some(report => report.current && ['queued', 'running'].includes(report.status));
  async function select(id: string) {
    setPending(id); setError('');
    try { await onSelect(id); }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not select this report.'); }
    finally { setPending(''); }
  }
  return <section id="inventory-history" className={`report-history ${staff ? 'report-history-crm' : ''}`} aria-label="Inventory report history">
    <div className="report-history-heading"><h4>Report history</h4><span>{reports.length} {reports.length === 1 ? 'run' : 'runs'}</span></div>
    <p>One report is used for pricing. Each new run becomes current automatically.</p>
    {waiting && <p role="status">Your new report is processing. You can choose an earlier report once it finishes.</p>}
    {error && <p className="report-history-error" role="alert">{error}</p>}
    {pending && <p role="status">Updating inventory and price...</p>}
    {reports.map(report => <details className="report-history-run" key={report.id} data-current={report.current}>
      <summary>
        <span>{report.created_at ? new Date(report.created_at * 1000).toLocaleString() : 'Earlier report'}</span>
        <span className="report-history-summary">{report.cuft != null && <span>{report.cuft.toLocaleString()} cu ft</span>}<span className="report-history-status">{report.source === 'manual' ? 'Item list' : report.status}</span>{report.current && <b>Current</b>}</span>
      </summary>
      <div className="report-history-detail">
        <div className="report-history-actions">
          <label><input type="radio" name={name} checked={report.current} disabled={disabled || !!pending || waiting || report.status !== 'completed' || (!report.shareUrl && report.source !== 'manual')} onChange={() => void select(report.id)} />{report.current ? 'Current report for pricing' : 'Use this report for pricing'}</label>
          {report.shareUrl && <a href={report.shareUrl} target="_blank" rel="noopener noreferrer">View report &nearr;</a>}
        </div>
        {report.source !== 'manual' && report.files && <details className="report-history-files"><summary>{report.files.length} files used in this run</summary>{report.files.map(file => <p key={file.id}>{file.name}</p>)}</details>}
        {report.inventory.length > 0 ? <div className="report-history-table"><table><thead><tr><th>Item</th><th>Qty</th><th>Cu ft</th></tr></thead><tbody>{report.inventory.map((item, index) => <tr key={index}><td>{item.name}{item.room && <small style={{ display: 'block' }}>{item.room}</small>}</td><td>{item.amount}</td><td>{item.cuft}</td></tr>)}</tbody></table></div> : <p>Open the report to view its inventory. Saved details appear after it is imported.</p>}
        {staff && report.processing && <div className="report-history-processing"><h5>Processing steps</h5>{report.processing.steps.map(step => <div key={step.id}>{step.error ? <details><summary>{step.label} <span>Failed - view error</span></summary><pre>{step.error}</pre></details> : <p><span>{step.label}</span><span>{step.status.replace(/_/g, ' ')}</span></p>}{step.message && <small>{step.message}</small>}</div>)}</div>}
      </div>
    </details>)}
  </section>;
}
