import { useEffect, useState } from "react";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";

interface Followup {
  note_id: string;
  title: string;
  due_date_time: string;
  completed_at_utc: string;
  notes: string;
  completed: boolean;
  type: number | null;
}

export default function FollowupPanel({ leadId }: { leadId: string }) {
  const { token } = useAuth();
  const [followups, setFollowups] = useState<Followup[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/leads/${leadId}/followups`, { headers: authHeaders(token) })
      .then((r) => r.json())
      .then((d) => setFollowups(d.followups || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [leadId, token]);

  if (loading) return <p style={{ fontSize: 13, color: "#888" }}>Loading followups…</p>;
  if (followups.length === 0) return null;

  const pending = followups.filter((f) => !f.completed);
  const completed = followups.filter((f) => f.completed);

  const formatDate = (iso: string) => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  };

  const isOverdue = (iso: string) => {
    if (!iso) return false;
    return new Date(iso) < new Date();
  };

  return (
    <div style={{ border: "1px solid #e0e0e0", borderRadius: 8, overflow: "hidden" }}>
      <div style={{ padding: "10px 16px", background: "#fff3e0", fontWeight: 700, fontSize: 15, borderBottom: "1px solid #e0e0e0", color: "#e65100" }}>
        Follow-ups {pending.length > 0 && `(${pending.length} pending)`}
      </div>
      <div style={{ padding: 12, maxHeight: 300, overflowY: "auto" }}>
        {pending.map((f) => (
          <div key={f.note_id} style={{ marginBottom: 10, padding: "8px 12px", background: isOverdue(f.due_date_time) ? "#ffebee" : "#fff8e1", borderRadius: 6, borderLeft: `3px solid ${isOverdue(f.due_date_time) ? "#d32f2f" : "#ff9800"}` }}>
            <div style={{ fontWeight: 600, fontSize: 14 }}>{f.title || "Follow-up"}</div>
            {f.due_date_time && (
              <div style={{ fontSize: 12, color: isOverdue(f.due_date_time) ? "#d32f2f" : "#666", marginTop: 2 }}>
                {isOverdue(f.due_date_time) ? "⚠ OVERDUE — " : "Due: "}{formatDate(f.due_date_time)}
              </div>
            )}
            {f.notes && <div style={{ fontSize: 12, color: "#555", marginTop: 4 }}>{f.notes}</div>}
          </div>
        ))}
        {completed.length > 0 && (
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: "pointer", fontSize: 13, color: "#888" }}>
              {completed.length} completed
            </summary>
            {completed.map((f) => (
              <div key={f.note_id} style={{ marginTop: 6, padding: "6px 12px", background: "#f5f5f5", borderRadius: 6, opacity: 0.7 }}>
                <div style={{ fontWeight: 600, fontSize: 13, textDecoration: "line-through" }}>{f.title || "Follow-up"}</div>
                {f.completed_at_utc && <div style={{ fontSize: 11, color: "#888" }}>Completed: {formatDate(f.completed_at_utc)}</div>}
              </div>
            ))}
          </details>
        )}
      </div>
    </div>
  );
}
