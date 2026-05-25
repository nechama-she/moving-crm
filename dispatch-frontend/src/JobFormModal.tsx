import { useState, type FormEvent } from "react";
import { API_BASE } from "./apiConfig";
import type { Company, Job } from "./types";

interface Props {
  job: Job | null; // null = create new
  companies: Company[];
  token: string;
  onClose: () => void;
  onSaved: () => void;
}

export function JobFormModal({ job, companies, token, onClose, onSaved }: Props) {
  const [clientName, setClientName] = useState(job?.client_name ?? "");
  const [companyId, setCompanyId] = useState(job?.company_id ?? companies[0]?.id ?? "");
  const [moveDate, setMoveDate] = useState(job?.move_date ?? "");
  const [startTime, setStartTime] = useState(job?.start_time ?? "");
  const [endTime, setEndTime] = useState(job?.end_time ?? "");
  const [originAddress, setOriginAddress] = useState(job?.origin_address ?? "");
  const [destAddress, setDestAddress] = useState(job?.destination_address ?? "");
  const [status, setStatus] = useState<string>(job?.status ?? "scheduled");
  const [notes, setNotes] = useState(job?.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError("");

    const body = {
      company_id: companyId,
      client_name: clientName,
      move_date: moveDate,
      start_time: startTime || null,
      end_time: endTime || null,
      origin_address: originAddress || null,
      destination_address: destAddress || null,
      status,
      notes: notes || null,
    };

    const url = job ? `${API_BASE}/api/jobs/${job.id}` : `${API_BASE}/api/jobs`;
    const method = job ? "PUT" : "POST";

    const res = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });

    setSaving(false);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Save failed" }));
      setError((err as { detail?: string }).detail ?? "Save failed");
      return;
    }
    onSaved();
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-box">
        <div className="modal-header">
          <span>{job ? "Edit Job" : "New Job"}</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          <label className="form-label">
            Company
            <select
              className="form-input"
              value={companyId}
              onChange={(e) => setCompanyId(e.target.value)}
              required
            >
              {companies.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>

          <label className="form-label">
            Client Name
            <input
              className="form-input"
              type="text"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              required
            />
          </label>

          <label className="form-label">
            Move Date
            <input
              className="form-input"
              type="date"
              value={moveDate}
              onChange={(e) => setMoveDate(e.target.value)}
              required
            />
          </label>

          <div className="form-row">
            <label className="form-label" style={{ flex: 1 }}>
              Start Time
              <input
                className="form-input"
                type="time"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
              />
            </label>
            <label className="form-label" style={{ flex: 1 }}>
              End Time
              <input
                className="form-input"
                type="time"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
              />
            </label>
          </div>

          <label className="form-label">
            Status
            <select
              className="form-input"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="scheduled">Scheduled</option>
              <option value="in_progress">In Progress</option>
              <option value="completed">Completed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>

          <label className="form-label">
            Origin Address
            <input
              className="form-input"
              type="text"
              value={originAddress}
              onChange={(e) => setOriginAddress(e.target.value)}
            />
          </label>

          <label className="form-label">
            Destination Address
            <input
              className="form-input"
              type="text"
              value={destAddress}
              onChange={(e) => setDestAddress(e.target.value)}
            />
          </label>

          <label className="form-label">
            Notes
            <textarea
              className="form-input"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>

          {error && <div className="form-error">{error}</div>}

          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
