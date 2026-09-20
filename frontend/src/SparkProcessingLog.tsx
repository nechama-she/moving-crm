import { useCallback, useEffect, useState } from 'react';
import { authHeaders } from './AuthContext';

type Step = { id: string; label: string; status: 'pending' | 'running' | 'success' | 'error' | 'skipped' | 'rolled_back'; message?: string; error?: string; at?: string };
type Processing = { report_id: string; started_at: string; finished_at?: string; status: string; steps: Step[] };
const labels: Record<Step['status'], string> = { pending: 'Waiting', running: 'Running', success: 'Done', error: 'Failed', skipped: 'Not run', rolled_back: 'Rolled back' };
export default function SparkProcessingLog({ base, token, reportId }: { base: string; token: string; reportId: string }) {
  const [processing, setProcessing] = useState<Processing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const response = await fetch(`${base}/spark-processing`, { headers: authHeaders(token), cache: 'no-store', signal });
      if (!response.ok) throw new Error('Could not load processing steps.');
      const result = await response.json();
      if (!signal?.aborted) { setProcessing(result.processing?.report_id === reportId ? result.processing : null); setError(''); }
    } catch (err) {
      if (!signal?.aborted) setError(err instanceof Error ? err.message : 'Could not load processing steps.');
    } finally { if (!signal?.aborted) setLoading(false); }
  }, [base, token, reportId]);
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    if (processing?.status !== 'running') return;
    const controller = new AbortController();
    const timer = setInterval(() => void refresh(controller.signal), 3000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [processing?.status, refresh]);
  return <div className="ls-processing" aria-label="Report processing steps">
    <div className="ls-processing-heading"><strong>Processing steps</strong><button type="button" title="Refresh processing log" aria-label="Refresh processing log" disabled={loading} onClick={() => void refresh()}>&#8635;</button></div>
    {error && <small role="alert" className="ls-processing-load-error">{error}</small>}
    {processing ? <>
      <ol>
        {processing.steps.map(step => <li key={step.id} className={`ls-processing-${step.status}`}>
          {step.error ? <details><summary><span>{step.label}</span><span className="ls-processing-status">Failed - view error</span></summary><pre>{step.error}</pre></details> : <div className="ls-processing-step"><span>{step.label}{step.message && <small>{step.message}</small>}</span><span className="ls-processing-status">{labels[step.status]}</span></div>}
        </li>)}
      </ol>
      <small className="ls-processing-time">Latest attempt: {new Date(processing.started_at).toLocaleString()}</small>
    </> : <small>{loading ? 'Loading processing steps...' : 'No processing attempt recorded for this report. Steps will appear after the next import attempt.'}</small>}
  </div>;
}
