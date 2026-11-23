import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { RealtimeEvent, useRealtimeUpdates } from "./useRealtimeUpdates";
import { activityActor, activityLabel, type ActivityRow } from "./customerActivity";
import { CUSTOMER_PAGE_EVENT, customerPageQueueTab, customerPageStateLabel, type CustomerPageRow } from "./customerPageStates";

type Notice = { key: string; client: string; line: string; jobNumber: string; to: string };

const activityNotice = (row: ActivityRow): Notice => ({
  key: `activity:${row.id}`, client: row.client, jobNumber: row.job_number,
  line: `${activityLabel(row)}${activityActor(row) ? ` · ${activityActor(row)}` : ""}`,
  to: `/sales-work-queue?activity=${encodeURIComponent(row.id)}`,
});

// One notice per lead: its next step replaces the one before.
const customerPageNotice = (row: CustomerPageRow): Notice => ({
  key: `customer-page:${row.lead_id}`, client: row.client, jobNumber: row.job_number,
  line: `Customer page · ${customerPageStateLabel(row)}`,
  to: `/sales-work-queue?queue=${customerPageQueueTab(row)}&customer_page=${encodeURIComponent(row.lead_id)}`,
});

/** For admins, on every page: each new Customer Activity event, and each new or moved Customer Page / Customer Chat
 *  row, as a notice until closed. Clicking it opens its work queue tab with its row marked. */
export default function CustomerActivityNotice({ token }: { token: string }) {
  const [notices, setNotices] = useState<Notice[]>([]);
  const navigate = useNavigate();
  const show = (notice: Notice) => setNotices((current) => [notice, ...current.filter((item) => item.key !== notice.key)].slice(0, 4));
  const take = (event: RealtimeEvent) => {
    const activity = event.type === "customer_activity" ? event.activity as ActivityRow | null | undefined : null;
    if (activity?.id) show(activityNotice(activity));
    const row = event.type === CUSTOMER_PAGE_EVENT ? event.row as CustomerPageRow | null | undefined : null;
    if (row?.lead_id) show(customerPageNotice(row));
  };
  useRealtimeUpdates(token, (event) => {
    // The customer's chat comes in the work queue's batch of message stream changes.
    if (event.type === "sales_work_queue_batch") ((event.events || []) as RealtimeEvent[]).forEach(take);
    else take(event);
  });
  const close = (key: string) => setNotices((current) => current.filter((item) => item.key !== key));
  if (!notices.length) return null;
  return <div className="activity-notices" role="status" aria-live="polite">
    {notices.map((notice) => <div key={notice.key} className="activity-notice">
      <button type="button" className="activity-notice-open" onClick={() => { close(notice.key); navigate(notice.to); }}>
        <strong>{notice.client || "Unnamed lead"}</strong>
        <span>{notice.line}</span>
        <small>Job {notice.jobNumber}</small>
      </button>
      <button type="button" className="activity-notice-close" aria-label="Close notice" onClick={() => close(notice.key)}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </div>)}
  </div>;
}
