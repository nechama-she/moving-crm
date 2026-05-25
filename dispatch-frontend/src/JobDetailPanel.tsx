import type { Job } from "./types";
import { API_BASE } from "./apiConfig";

const STATUS_META: Record<string, { label: string; color: string }> = {
  scheduled:   { label: "Scheduled",   color: "#1589ee" },
  in_progress: { label: "In Progress", color: "#ff9900" },
  completed:   { label: "Completed",   color: "#2e844a" },
  cancelled:   { label: "Cancelled",   color: "#c23934" },
};

interface Props {
  job: Job;
  token: string;
  onClose: () => void;
  onEdit?: (job: Job) => void;
  onDeleted: () => void;
}

export function JobDetailPanel({ job, token, onClose, onEdit, onDeleted }: Props) {
  const meta = STATUS_META[job.status] ?? { label: job.status, color: "#777" };

  const handleDelete = async () => {
    if (!window.confirm(`Cancel job for "${job.client_name}"?`)) return;
    await fetch(`${API_BASE}/api/jobs/${job.id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    onDeleted();
  };

  return (
    <aside className="detail-panel">
      <div className="detail-panel-header">
        <span className="detail-panel-title">Job Details</span>
        <button className="icon-btn" onClick={onClose} title="Close">✕</button>
      </div>

      <div className="detail-top">
        <div className="detail-client">{job.client_name}</div>
        <span className="status-badge" style={{ background: meta.color }}>
          {meta.label}
        </span>
      </div>

      <dl className="detail-list">
        <dt>Company</dt>
        <dd>{job.company_name}</dd>

        <dt>Date</dt>
        <dd>{job.move_date}</dd>

        {job.start_time && (
          <>
            <dt>Time</dt>
            <dd>
              {job.start_time}
              {job.end_time ? ` – ${job.end_time}` : ""}
            </dd>
          </>
        )}

        {job.origin_address && (
          <>
            <dt>From</dt>
            <dd>{job.origin_address}</dd>
          </>
        )}

        {job.destination_address && (
          <>
            <dt>To</dt>
            <dd>{job.destination_address}</dd>
          </>
        )}

        {job.notes && (
          <>
            <dt>Notes</dt>
            <dd>{job.notes}</dd>
          </>
        )}
      </dl>

      {onEdit && (
        <div className="detail-actions">
          <button className="btn-primary" onClick={() => onEdit(job)}>
            Edit
          </button>
          <button className="btn-danger" onClick={handleDelete}>
            Cancel Job
          </button>
        </div>
      )}
    </aside>
  );
}
