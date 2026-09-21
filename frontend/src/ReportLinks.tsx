import { useRef } from 'react';
import type { ReportRun } from './ReportHistory';
export default function ReportLinks({ report }: { report: ReportRun }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const rooms = report.rooms?.length ? report.rooms : report.source === 'manual' ? [{ name: 'Items', items: report.inventory }] : [];
  return <div className="report-links">
    {report.shareUrl && <a href={report.shareUrl} target="_blank" rel="noopener noreferrer">View virtual tour report &#8599;</a>}
    {rooms.length > 0 && <button type="button" onClick={() => dialog.current?.showModal()}>View itemized list</button>}
    <dialog aria-label="Saved itemized list" ref={dialog} className="report-list-dialog" onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      <header><div><h3>Itemized list</h3><small>{report.created_at ? new Date(report.created_at * 1000).toLocaleString() : 'Saved report'}</small></div><button type="button" aria-label="Close itemized list" onClick={() => dialog.current?.close()} autoFocus>&times;</button></header>
      <p>Items entered in the list for this report. Photos and videos are shown in the virtual tour report.</p>
      {rooms.map((room, index) => <section key={index}><h4>{room.name}</h4><table><thead><tr><th>Item</th><th>Qty</th><th>Cu ft</th></tr></thead><tbody>{room.items.map((item, i) => <tr key={i}><td>{item.name}</td><td>{item.amount}</td><td>{item.cuft.toLocaleString()}</td></tr>)}</tbody></table></section>)}
      <p><strong>List total: {rooms.reduce((sum, room) => sum + room.items.reduce((n, item) => n + item.cuft, 0), 0).toLocaleString()} cu ft</strong></p>
    </dialog>
  </div>;
}
