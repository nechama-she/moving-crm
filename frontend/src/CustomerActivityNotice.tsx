import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useRealtimeUpdates } from "./useRealtimeUpdates";
import { activityActor, activityLabel, type ActivityRow } from "./customerActivity";

/** For admins, on every page: each new Customer Activity event as a notice until closed. Clicking it opens Customer
 *  Activity with its row marked. */
export default function CustomerActivityNotice({ token }: { token: string }) {
  const [notices, setNotices] = useState<ActivityRow[]>([]);
  const navigate = useNavigate();
  useRealtimeUpdates(token, (event) => {
    const activity = event.type === "customer_activity" ? event.activity as ActivityRow | null | undefined : null;
    if (activity?.id) setNotices((current) => [activity, ...current.filter((row) => row.id !== activity.id)].slice(0, 4));
  });
  const close = (id: string) => setNotices((current) => current.filter((row) => row.id !== id));
  if (!notices.length) return null;
  return <div className="activity-notices" role="status" aria-live="polite">
    {notices.map((row) => <div key={row.id} className="activity-notice">
      <button type="button" className="activity-notice-open" onClick={() => { close(row.id); navigate(`/sales-work-queue?activity=${encodeURIComponent(row.id)}`); }}>
        <strong>{row.client || "Unnamed lead"}</strong>
        <span>{activityLabel(row)}{activityActor(row) ? ` · ${activityActor(row)}` : ""}</span>
        <small>Job {row.job_number}</small>
      </button>
      <button type="button" className="activity-notice-close" aria-label="Close notice" onClick={() => close(row.id)}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </div>)}
  </div>;
}
