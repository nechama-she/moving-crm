import { useEffect, useMemo, useState, type FormEvent } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders } from "./AuthContext";

interface Task {
  id: string;
  title: string;
  due_date: string;
  status: "open" | "in_progress" | "done";
  assigned_to: string;
  created_by: string;
  created_at: string;
}

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_progress: "In Progress",
  done: "Completed",
};

const STATUS_COLORS: Record<string, string> = {
  open: "#706e6b",
  in_progress: "#ff9900",
  done: "#2e844a",
};

interface Props {
  leadId: string;
  token: string | null;
}

// ─── Date helpers ──────────────────────────────────────────────────────────
function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dateBucket(task: Task): string {
  if (task.status === "done") return "Completed";
  if (!task.due_date) return "No Due Date";
  const today = todayISO();
  if (task.due_date < today) return "Overdue";
  if (task.due_date === today) return "Today";
  return "Upcoming";
}

const BUCKET_ORDER = ["Overdue", "Today", "Upcoming", "No Due Date", "Completed"];

const BUCKET_COLORS: Record<string, string> = {
  Overdue: "#c23934",
  Today: "#0176d3",
  Upcoming: "#3e3e3c",
  "No Due Date": "#706e6b",
  Completed: "#2e844a",
};

function formatDueLabel(due: string): string {
  if (!due) return "";
  const today = todayISO();
  if (due === today) return "Today";
  const t = new Date();
  t.setDate(t.getDate() + 1);
  const tomorrow = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
  if (due === tomorrow) return "Tomorrow";
  const d = new Date(`${due}T00:00:00`);
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  });
}

// ─── Component ─────────────────────────────────────────────────────────────
export default function TasksPanel({ leadId, token }: Props) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDueDate, setEditDueDate] = useState("");
  const [editStatus, setEditStatus] = useState<Task["status"]>("open");
  const [newTitle, setNewTitle] = useState("");
  const [newDueDate, setNewDueDate] = useState("");
  const [saving, setSaving] = useState(false);

  function load() {
    setLoading(true);
    fetch(`${API_BASE}/api/leads/${leadId}/tasks`, { headers: authHeaders(token) })
      .then((r) => r.json() as Promise<Task[]>)
      .then(setTasks)
      .catch(console.error)
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, [leadId]);

  async function addTask(e: FormEvent) {
    e.preventDefault();
    const title = newTitle.trim();
    if (!title) return;
    setSaving(true);
    await fetch(`${API_BASE}/api/leads/${leadId}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ title, due_date: newDueDate || null }),
    });
    setNewTitle("");
    setNewDueDate("");
    setShowNewForm(false);
    setSaving(false);
    load();
  }

  async function toggleDone(task: Task) {
    const newStatus = task.status === "done" ? "open" : "done";
    await fetch(`${API_BASE}/api/tasks/${task.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ status: newStatus }),
    });
    load();
  }

  async function saveEdit(task: Task) {
    await fetch(`${API_BASE}/api/tasks/${task.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({
        title: editTitle.trim() || task.title,
        due_date: editDueDate || null,
        status: editStatus,
      }),
    });
    setEditingId(null);
    load();
  }

  async function deleteTask(task: Task) {
    if (!window.confirm(`Delete task "${task.title}"?`)) return;
    await fetch(`${API_BASE}/api/tasks/${task.id}`, {
      method: "DELETE",
      headers: authHeaders(token),
    });
    setExpandedId(null);
    load();
  }

  function startEdit(task: Task) {
    setEditingId(task.id);
    setEditTitle(task.title);
    setEditDueDate(task.due_date);
    setEditStatus(task.status);
  }

  const grouped = useMemo(() => {
    const map: Record<string, Task[]> = {};
    for (const t of tasks) {
      const b = dateBucket(t);
      (map[b] ||= []).push(t);
    }
    for (const key of Object.keys(map)) {
      map[key].sort((a, b) => {
        if (a.due_date && b.due_date && a.due_date !== b.due_date) return a.due_date.localeCompare(b.due_date);
        if (a.due_date && !b.due_date) return -1;
        if (!a.due_date && b.due_date) return 1;
        return a.created_at.localeCompare(b.created_at);
      });
    }
    return map;
  }, [tasks]);

  const openCount = tasks.filter((t) => t.status !== "done").length;

  return (
    <div style={cardStyle}>
      {/* Header */}
      <div style={headerStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: "#032d60" }}>Activity</span>
          <span style={{ fontSize: 12, color: "#706e6b" }}>· {openCount} open</span>
        </div>
        <button
          onClick={() => { setShowNewForm(true); setExpandedId(null); }}
          style={newBtnStyle}
        >
          + New Task
        </button>
      </div>

      {/* Inline new task form */}
      {showNewForm && (
        <form onSubmit={addTask} style={newFormStyle}>
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="What needs to be done?"
            autoFocus
            style={inputStyle}
          />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <label style={{ flex: 1, fontSize: 11, color: "#706e6b" }}>
              Due date
              <input
                type="date"
                value={newDueDate}
                onChange={(e) => setNewDueDate(e.target.value)}
                style={{ ...inputStyle, marginTop: 3 }}
              />
            </label>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10, justifyContent: "flex-end" }}>
            <button type="button" onClick={() => { setShowNewForm(false); setNewTitle(""); setNewDueDate(""); }} style={btnGhost}>
              Cancel
            </button>
            <button type="submit" disabled={saving || !newTitle.trim()} style={{ ...btnPrimary, opacity: !newTitle.trim() ? 0.5 : 1 }}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      )}

      {/* Body */}
      {loading ? (
        <div style={emptyStyle}>Loading…</div>
      ) : tasks.length === 0 && !showNewForm ? (
        <div style={emptyStyle}>
          <div style={{ fontSize: 13, color: "#706e6b", marginBottom: 6 }}>No activity yet</div>
          <div style={{ fontSize: 12, color: "#706e6b" }}>Add a task to get started.</div>
        </div>
      ) : (
        <div>
          {BUCKET_ORDER.filter((b) => grouped[b]?.length).map((bucket) => (
            <div key={bucket}>
              <div style={bucketHeader(BUCKET_COLORS[bucket])}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: BUCKET_COLORS[bucket], display: "inline-block" }} />
                {bucket}
                <span style={{ color: "#706e6b", fontWeight: 400, marginLeft: 4 }}>· {grouped[bucket].length}</span>
              </div>
              {grouped[bucket].map((task) => {
                const isExpanded = expandedId === task.id;
                const isEditing = editingId === task.id;
                return (
                  <div key={task.id} style={taskRow(isExpanded)}>
                    <div
                      style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 16px", cursor: "pointer" }}
                      onClick={() => { if (!isEditing) setExpandedId(isExpanded ? null : task.id); }}
                    >
                      <input
                        type="checkbox"
                        checked={task.status === "done"}
                        onChange={() => toggleDone(task)}
                        onClick={(e) => e.stopPropagation()}
                        style={{ marginTop: 3, width: 15, height: 15, cursor: "pointer", accentColor: "#2e844a" }}
                      />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: 13,
                          color: task.status === "done" ? "#706e6b" : "#181818",
                          textDecoration: task.status === "done" ? "line-through" : "none",
                          fontWeight: 500,
                        }}>
                          {task.title}
                        </div>
                        <div style={{ display: "flex", gap: 10, marginTop: 3, fontSize: 11, color: "#706e6b", alignItems: "center" }}>
                          {task.due_date && (
                            <span style={{ color: bucket === "Overdue" ? "#c23934" : "#706e6b", fontWeight: bucket === "Overdue" ? 600 : 400 }}>
                              📅 {formatDueLabel(task.due_date)}
                            </span>
                          )}
                          <span style={{ color: STATUS_COLORS[task.status], fontWeight: 600 }}>
                            {STATUS_LABELS[task.status]}
                          </span>
                        </div>
                      </div>
                      <span style={{ fontSize: 11, color: "#706e6b" }}>{isExpanded ? "▾" : "▸"}</span>
                    </div>

                    {isExpanded && (
                      <div style={detailStyle}>
                        {isEditing ? (
                          <>
                            <label style={fieldLabel}>
                              Subject
                              <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} style={inputStyle} />
                            </label>
                            <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
                              <label style={{ ...fieldLabel, flex: 1 }}>
                                Due Date
                                <input type="date" value={editDueDate} onChange={(e) => setEditDueDate(e.target.value)} style={inputStyle} />
                              </label>
                              <label style={{ ...fieldLabel, flex: 1 }}>
                                Status
                                <select value={editStatus} onChange={(e) => setEditStatus(e.target.value as Task["status"])} style={inputStyle}>
                                  <option value="open">Open</option>
                                  <option value="in_progress">In Progress</option>
                                  <option value="done">Completed</option>
                                </select>
                              </label>
                            </div>
                            <div style={{ display: "flex", gap: 8, marginTop: 10, justifyContent: "flex-end" }}>
                              <button onClick={() => setEditingId(null)} style={btnGhost}>Cancel</button>
                              <button onClick={() => saveEdit(task)} style={btnPrimary}>Save</button>
                            </div>
                          </>
                        ) : (
                          <>
                            <dl style={dlStyle}>
                              <dt style={dtStyle}>Status</dt>
                              <dd style={ddStyle}>{STATUS_LABELS[task.status]}</dd>
                              <dt style={dtStyle}>Due Date</dt>
                              <dd style={ddStyle}>{task.due_date ? formatDueLabel(task.due_date) : "—"}</dd>
                              <dt style={dtStyle}>Created</dt>
                              <dd style={ddStyle}>{new Date(task.created_at).toLocaleString()}</dd>
                            </dl>
                            <div style={{ display: "flex", gap: 8, marginTop: 10, justifyContent: "flex-end" }}>
                              <button onClick={(e) => { e.stopPropagation(); deleteTask(task); }} style={btnDanger}>Delete</button>
                              <button onClick={(e) => { e.stopPropagation(); startEdit(task); }} style={btnPrimary}>Edit</button>
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Styles ────────────────────────────────────────────────────────────────
const cardStyle: React.CSSProperties = {
  border: "1px solid #dddbda",
  borderRadius: 4,
  overflow: "hidden",
  background: "#fff",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "10px 16px",
  background: "#f3f2f2",
  borderBottom: "1px solid #dddbda",
};

const newBtnStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  padding: "5px 12px",
  border: "1px solid #0176d3",
  borderRadius: 4,
  background: "#fff",
  color: "#0176d3",
  cursor: "pointer",
};

const newFormStyle: React.CSSProperties = {
  padding: "14px 16px",
  background: "#f9f9f9",
  borderBottom: "1px solid #dddbda",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  fontSize: 13,
  border: "1px solid #c9c7c5",
  borderRadius: 3,
  padding: "5px 8px",
  boxSizing: "border-box",
};

const fieldLabel: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  color: "#706e6b",
  fontWeight: 600,
};

const btnPrimary: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  padding: "5px 14px",
  border: "none",
  borderRadius: 4,
  background: "#0176d3",
  color: "#fff",
  cursor: "pointer",
};

const btnGhost: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  padding: "5px 12px",
  border: "1px solid #c9c7c5",
  borderRadius: 4,
  background: "#fff",
  color: "#3e3e3c",
  cursor: "pointer",
};

const btnDanger: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  padding: "5px 12px",
  border: "1px solid #ba0517",
  borderRadius: 4,
  background: "#fff",
  color: "#ba0517",
  cursor: "pointer",
};

const emptyStyle: React.CSSProperties = {
  padding: "24px 16px",
  textAlign: "center",
};

function bucketHeader(color: string): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "8px 16px",
    background: "#fafaf9",
    fontSize: 11,
    fontWeight: 700,
    color,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    borderTop: "1px solid #f3f2f2",
    borderBottom: "1px solid #f3f2f2",
  };
}

function taskRow(expanded: boolean): React.CSSProperties {
  return {
    borderBottom: "1px solid #f3f2f2",
    background: expanded ? "#f9fbff" : "#fff",
  };
}

const detailStyle: React.CSSProperties = {
  padding: "12px 16px 14px 41px",
  background: "#f9fbff",
  borderTop: "1px solid #eef4fb",
};

const dlStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "100px 1fr",
  rowGap: 6,
  columnGap: 12,
  margin: 0,
  fontSize: 12,
};

const dtStyle: React.CSSProperties = {
  color: "#706e6b",
  fontWeight: 600,
};

const ddStyle: React.CSSProperties = {
  color: "#181818",
  margin: 0,
};
