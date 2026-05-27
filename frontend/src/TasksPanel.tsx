import { useEffect, useState, type FormEvent } from "react";
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

const STATUS_COLORS: Record<string, string> = {
  open: "#706e6b",
  in_progress: "#ff9900",
  done: "#2e844a",
};

interface Props {
  leadId: string;
  token: string | null;
}

export default function TasksPanel({ leadId, token }: Props) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [newTitle, setNewTitle] = useState("");
  const [newDueDate, setNewDueDate] = useState("");
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDueDate, setEditDueDate] = useState("");

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
    setAdding(true);
    await fetch(`${API_BASE}/api/leads/${leadId}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ title, due_date: newDueDate || null }),
    });
    setNewTitle("");
    setNewDueDate("");
    setAdding(false);
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

  async function setStatus(task: Task, status: string) {
    await fetch(`${API_BASE}/api/tasks/${task.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ status }),
    });
    load();
  }

  async function saveEdit(task: Task) {
    await fetch(`${API_BASE}/api/tasks/${task.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ title: editTitle.trim() || task.title, due_date: editDueDate || null }),
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
    load();
  }

  const sectionStyle: React.CSSProperties = {
    marginBottom: 16,
    border: "1px solid #dddbda",
    borderRadius: 4,
    overflow: "hidden",
    background: "#fff",
    boxShadow: "0 1px 2px rgba(0,0,0,.06)",
  };

  return (
    <div style={sectionStyle}>
      <div style={{ padding: "10px 16px", background: "#f3f2f2", fontWeight: 700, fontSize: 12, borderBottom: "1px solid #dddbda", color: "#3e3e3c", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        Tasks
      </div>

      {loading ? (
        <div style={{ padding: "12px 16px", fontSize: 13, color: "#706e6b" }}>Loading…</div>
      ) : (
        <>
          {tasks.length === 0 && (
            <div style={{ padding: "12px 16px", fontSize: 13, color: "#706e6b" }}>No tasks yet.</div>
          )}
          {tasks.map((task) => (
            <div
              key={task.id}
              style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 16px", borderBottom: "1px solid #f3f2f2" }}
            >
              {/* Done checkbox */}
              <input
                type="checkbox"
                checked={task.status === "done"}
                onChange={() => toggleDone(task)}
                title={task.status === "done" ? "Mark as not done" : "Mark as done"}
                style={{ flexShrink: 0, marginTop: 3, width: 16, height: 16, cursor: "pointer" }}
              />

              {/* Title / edit */}
              <div style={{ flex: 1, minWidth: 0 }}>
                {editingId === task.id ? (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <input
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      style={{ flex: 1, fontSize: 13, border: "1px solid #dddbda", borderRadius: 3, padding: "3px 8px" }}
                      autoFocus
                    />
                    <input
                      type="date"
                      value={editDueDate}
                      onChange={(e) => setEditDueDate(e.target.value)}
                      style={{ fontSize: 13, border: "1px solid #dddbda", borderRadius: 3, padding: "3px 8px" }}
                    />
                    <button onClick={() => saveEdit(task)} style={btnSmall("#0176d3")}>Save</button>
                    <button onClick={() => setEditingId(null)} style={btnSmall("#706e6b")}>Cancel</button>
                  </div>
                ) : (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 13, textDecoration: task.status === "done" ? "line-through" : "none", color: task.status === "done" ? "#706e6b" : "#181818" }}>
                      {task.title}
                    </span>
                    {task.due_date && (
                      <span style={{ fontSize: 11, color: "#706e6b" }}>· due {task.due_date}</span>
                    )}
                    <select
                      value={task.status}
                      onChange={(e) => setStatus(task, e.target.value)}
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: STATUS_COLORS[task.status],
                        border: `1px solid ${STATUS_COLORS[task.status]}`,
                        borderRadius: 3,
                        padding: "1px 6px",
                        background: "#fff",
                        cursor: "pointer",
                      }}
                    >
                      <option value="open">Open</option>
                      <option value="in_progress">In Progress</option>
                      <option value="done">Done</option>
                    </select>
                  </div>
                )}
              </div>

              {/* Actions */}
              {editingId !== task.id && (
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  <button
                    onClick={() => { setEditingId(task.id); setEditTitle(task.title); setEditDueDate(task.due_date); }}
                    style={btnSmall("#706e6b")}
                  >
                    Edit
                  </button>
                  <button onClick={() => deleteTask(task)} style={btnSmall("#ba0517")}>Delete</button>
                </div>
              )}
            </div>
          ))}

          {/* Add task form */}
          <form onSubmit={addTask} style={{ display: "flex", gap: 8, padding: "10px 16px", borderTop: tasks.length > 0 ? "1px solid #dddbda" : "none", flexWrap: "wrap" }}>
            <input
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="Add a task…"
              style={{ flex: 1, minWidth: 160, fontSize: 13, border: "1px solid #dddbda", borderRadius: 3, padding: "5px 10px" }}
            />
            <input
              type="date"
              value={newDueDate}
              onChange={(e) => setNewDueDate(e.target.value)}
              style={{ fontSize: 13, border: "1px solid #dddbda", borderRadius: 3, padding: "5px 8px" }}
            />
            <button
              type="submit"
              disabled={adding || !newTitle.trim()}
              style={{ ...btnSmall("#0176d3"), padding: "5px 14px", opacity: !newTitle.trim() ? 0.5 : 1 }}
            >
              {adding ? "Adding…" : "Add"}
            </button>
          </form>
        </>
      )}
    </div>
  );
}

function btnSmall(color: string): React.CSSProperties {
  return {
    fontSize: 12,
    padding: "3px 10px",
    border: `1px solid ${color}`,
    borderRadius: 3,
    color,
    background: "#fff",
    cursor: "pointer",
    whiteSpace: "nowrap",
  };
}
