import { useEffect, useMemo, useState, type FormEvent } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders } from "./AuthContext";

interface Task {
  id: string;
  title: string;
  due_date: string;
  status: "open" | "in_progress" | "done";
  task_type: TaskType;
  notes: string;
  created_by: string;
  created_at: string;
}

type TaskType = "call" | "email" | "text" | "messenger" | "instagram" | "other";

const TYPE_LABELS: Record<TaskType, string> = {
  call: "Call",
  email: "Email",
  text: "Text",
  messenger: "Messenger",
  instagram: "Instagram",
  other: "Other",
};

const TYPE_ICONS: Record<TaskType, string> = {
  call: "📞",
  email: "✉️",
  text: "💬",
  messenger: "Ⓜ️",
  instagram: "📷",
  other: "📝",
};

const TYPE_OPTIONS: TaskType[] = ["call", "email", "text", "messenger", "instagram", "other"];

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



function formatDateHeader(key: string): string {
  if (key === "No Due Date") return "No Due Date";
  const today = todayISO();
  const d = new Date(`${key}T00:00:00`);
  const base = d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  });
  if (key < today) return `${base} · Overdue`;
  if (key === today) return `${base} · Today`;
  return base;
}

function dateHeaderColor(key: string): string {
  if (key === "No Due Date") return "#706e6b";
  const today = todayISO();
  if (key < today) return "#c23934";
  if (key === today) return "#0176d3";
  return "#3e3e3c";
}

// ─── Component ─────────────────────────────────────────────────────────────
export default function TasksPanel({ leadId, token }: Props) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [completedCollapsed, setCompletedCollapsed] = useState(true);
  const [collapsedDates, setCollapsedDates] = useState<Record<string, boolean>>({});
  const toggleDate = (key: string) => setCollapsedDates((m) => ({ ...m, [key]: !m[key] }));
  const [showNewForm, setShowNewForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDueDate, setEditDueDate] = useState("");
  const [editStatus, setEditStatus] = useState<Task["status"]>("open");
  const [editType, setEditType] = useState<TaskType>("call");
  const [editNotes, setEditNotes] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newDueDate, setNewDueDate] = useState("");
  const [newType, setNewType] = useState<TaskType>("call");
  const [newNotes, setNewNotes] = useState("");
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
      body: JSON.stringify({ title, due_date: newDueDate || null, task_type: newType, notes: newNotes }),
    });
    setNewTitle("");
    setNewDueDate("");
    setNewType("call");
    setNewNotes("");
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
        task_type: editType,
        notes: editNotes,
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
    setEditType(task.task_type || "other");
    setEditNotes(task.notes || "");
  }

  function groupByDate(list: Task[]): Record<string, Task[]> {
    const map: Record<string, Task[]> = {};
    for (const t of list) {
      const key = t.due_date || "No Due Date";
      (map[key] ||= []).push(t);
    }
    for (const key of Object.keys(map)) {
      map[key].sort((a, b) => a.created_at.localeCompare(b.created_at));
    }
    return map;
  }

  function sortKeys(map: Record<string, Task[]>, descending = false): string[] {
    const dated = Object.keys(map).filter((k) => k !== "No Due Date").sort();
    if (descending) dated.reverse();
    return map["No Due Date"] ? [...dated, "No Due Date"] : dated;
  }

  const upcomingGrouped = useMemo(() => groupByDate(tasks.filter((t) => t.status !== "done")), [tasks]);
  const completedGrouped = useMemo(() => groupByDate(tasks.filter((t) => t.status === "done")), [tasks]);
  const upcomingKeys = useMemo(() => sortKeys(upcomingGrouped), [upcomingGrouped]);
  const completedKeys = useMemo(() => sortKeys(completedGrouped, true), [completedGrouped]);

  const openCount = tasks.filter((t) => t.status !== "done").length;
  const doneCount = tasks.length - openCount;

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
              Type
              <select
                value={newType}
                onChange={(e) => setNewType(e.target.value as TaskType)}
                style={{ ...inputStyle, marginTop: 3 }}
              >
                {TYPE_OPTIONS.map((t) => (
                  <option key={t} value={t}>{TYPE_ICONS[t]} {TYPE_LABELS[t]}</option>
                ))}
              </select>
            </label>
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
          <label style={{ display: "block", fontSize: 11, color: "#706e6b", marginTop: 8 }}>
            Notes
            <textarea
              value={newNotes}
              onChange={(e) => setNewNotes(e.target.value)}
              placeholder="Add details (optional)…"
              rows={3}
              style={{ ...inputStyle, marginTop: 3, resize: "vertical", fontFamily: "inherit" }}
            />
          </label>
          <div style={{ display: "flex", gap: 8, marginTop: 10, justifyContent: "flex-end" }}>
            <button type="button" onClick={() => { setShowNewForm(false); setNewTitle(""); setNewDueDate(""); setNewNotes(""); }} style={btnGhost}>
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
          {/* Upcoming tasks grouped by date (flat, no wrapper) */}
          {upcomingKeys.map((dateKey) => {
            const key = `up-${dateKey}`;
            const collapsed = !!collapsedDates[key];
            return (
              <div key={key}>
                <div
                  style={{ ...bucketHeader(dateHeaderColor(dateKey)), cursor: "pointer" }}
                  onClick={() => toggleDate(key)}
                >
                  <span style={{ fontSize: 10, color: "#706e6b" }}>{collapsed ? "▸" : "▾"}</span>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: dateHeaderColor(dateKey), display: "inline-block" }} />
                  {formatDateHeader(dateKey)}
                  <span style={{ color: "#706e6b", fontWeight: 400, marginLeft: 4 }}>· {upcomingGrouped[dateKey].length}</span>
                </div>
                {!collapsed && upcomingGrouped[dateKey].map((task) => renderTaskRow(task, dateKey))}
              </div>
            );
          })}

          {/* Completed (collapsible) */}
          {doneCount > 0 && (
            <div>
              <div
                onClick={() => setCompletedCollapsed((v) => !v)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 16px",
                  background: "#fafaf9",
                  borderBottom: "1px solid #dddbda",
                  borderTop: "1px solid #dddbda",
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: 700,
                  color: "#2e844a",
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                <span style={{ fontSize: 11, color: "#706e6b" }}>{completedCollapsed ? "▸" : "▾"}</span>
                Completed
                <span style={{ color: "#706e6b", fontWeight: 500 }}>· {doneCount}</span>
              </div>
              {!completedCollapsed && completedKeys.map((dateKey) => {
                const key = `done-${dateKey}`;
                const collapsed = !!collapsedDates[key];
                return (
                  <div key={key}>
                    <div
                      style={{ ...bucketHeader("#2e844a"), cursor: "pointer" }}
                      onClick={() => toggleDate(key)}
                    >
                      <span style={{ fontSize: 10, color: "#706e6b" }}>{collapsed ? "▸" : "▾"}</span>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#2e844a", display: "inline-block" }} />
                      {formatDateHeader(dateKey)}
                      <span style={{ color: "#706e6b", fontWeight: 400, marginLeft: 4 }}>· {completedGrouped[dateKey].length}</span>
                    </div>
                    {!collapsed && completedGrouped[dateKey].map((task) => renderTaskRow(task, dateKey))}
                  </div>
                );
              })}
            </div>
          )}

          {upcomingKeys.length === 0 && doneCount === 0 && !showNewForm && (
            <div style={emptyStyle}>
              <div style={{ fontSize: 13, color: "#706e6b" }}>No activity yet</div>
            </div>
          )}
        </div>
      )}
    </div>
  );

  function renderTaskRow(task: Task, dateKey: string) {
    const isExpanded = expandedId === task.id;
    const isEditing = editingId === task.id;
    const isOverdue = dateKey !== "No Due Date" && dateKey < todayISO() && task.status !== "done";
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
              <span style={{ marginRight: 6 }} title={TYPE_LABELS[task.task_type || "other"]}>
                {TYPE_ICONS[task.task_type || "other"]}
              </span>
              {task.title}
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 3, fontSize: 11, color: "#706e6b", alignItems: "center" }}>
              {task.due_date && (
                <span style={{ color: isOverdue ? "#c23934" : "#706e6b", fontWeight: isOverdue ? 600 : 400 }}>
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
                    Type
                    <select value={editType} onChange={(e) => setEditType(e.target.value as TaskType)} style={inputStyle}>
                      {TYPE_OPTIONS.map((t) => (
                        <option key={t} value={t}>{TYPE_ICONS[t]} {TYPE_LABELS[t]}</option>
                      ))}
                    </select>
                  </label>
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
                <label style={{ ...fieldLabel, display: "block", marginTop: 8 }}>
                  Notes
                  <textarea
                    value={editNotes}
                    onChange={(e) => setEditNotes(e.target.value)}
                    rows={4}
                    placeholder="Add details (optional)…"
                    style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
                  />
                </label>
                <div style={{ display: "flex", gap: 8, marginTop: 10, justifyContent: "flex-end" }}>
                  <button onClick={() => setEditingId(null)} style={btnGhost}>Cancel</button>
                  <button onClick={() => saveEdit(task)} style={btnPrimary}>Save</button>
                </div>
              </>
            ) : (
              <>
                <dl style={dlStyle}>
                  <dt style={dtStyle}>Type</dt>
                  <dd style={ddStyle}>{TYPE_ICONS[task.task_type || "other"]} {TYPE_LABELS[task.task_type || "other"]}</dd>
                  <dt style={dtStyle}>Status</dt>
                  <dd style={ddStyle}>{STATUS_LABELS[task.status]}</dd>
                  <dt style={dtStyle}>Due Date</dt>
                  <dd style={ddStyle}>{task.due_date ? formatDueLabel(task.due_date) : "—"}</dd>
                  <dt style={dtStyle}>Created</dt>
                  <dd style={ddStyle}>{new Date(task.created_at).toLocaleString()}</dd>
                </dl>
                {task.notes && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ ...dtStyle, marginBottom: 4 }}>Notes</div>
                    <div style={{ fontSize: 13, color: "#181818", whiteSpace: "pre-wrap", background: "#fff", padding: "8px 10px", border: "1px solid #e5e9ed", borderRadius: 4 }}>
                      {task.notes}
                    </div>
                  </div>
                )}
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
  }
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
