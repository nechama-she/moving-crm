import { Link, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type SalesCalendarJob = {
  id: string;
  lead_id: string;
  company_id: string;
  company_name: string;
  company_color: string;
  job_order: number;
  full_name: string;
  move_date: string;
  booked_move_date: string;
  pickup_zip: string;
  delivery_zip: string;
  price: number | null;
  status: string;
  assigned_to: string;
  assigned_to_name: string;
  assigned_to_role: string;
};

type AssigneeOption = {
  key: string;
  id: string;
  name: string;
  role: string;
};

const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const UNASSIGNED_KEY = "__unassigned__";

function monthKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function parseCalendarDate(raw: string): Date | null {
  const value = (raw || "").trim();
  if (!value) return null;
  const ymd = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (ymd) {
    const year = Number(ymd[1]);
    const month = Number(ymd[2]);
    const day = Number(ymd[3]);
    const date = new Date(year, month - 1, day);
    if (Number.isNaN(date.getTime())) return null;
    return date;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function assigneeKey(job: SalesCalendarJob): string {
  return String(job.assigned_to || "").trim() || UNASSIGNED_KEY;
}

function roleLabel(role: string): string {
  if (role === "admin") return "Admin";
  if (role === "sales_rep") return "Rep";
  return "";
}

export default function SalesCalendarPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { token, user } = useAuth();

  const [viewMonth, setViewMonth] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [jobs, setJobs] = useState<SalesCalendarJob[]>([]);
  const [selectedAssigneeKeys, setSelectedAssigneeKeys] = useState<string[]>([]);

  const isAdmin = user?.role === "admin";

  const assigneeOptions = useMemo(() => {
    const map = new Map<string, AssigneeOption>();
    let hasUnassigned = false;

    for (const job of jobs) {
      const key = assigneeKey(job);
      if (key === UNASSIGNED_KEY) {
        hasUnassigned = true;
        continue;
      }
      if (!map.has(key)) {
        map.set(key, {
          key,
          id: job.assigned_to,
          name: job.assigned_to_name || "Unknown",
          role: job.assigned_to_role || "",
        });
      }
    }

    const options = Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
    if (isAdmin && hasUnassigned) {
      options.push({ key: UNASSIGNED_KEY, id: "", name: "Unassigned", role: "" });
    }

    if (!isAdmin && user?.id) {
      const own = options.find((o) => o.id === user.id);
      if (own) return [own];
      return [{ key: user.id, id: user.id, name: user.name || "Me", role: user.role || "sales_rep" }];
    }

    return options;
  }, [jobs, isAdmin, user?.id, user?.name, user?.role]);

  useEffect(() => {
    if (!assigneeOptions.length) {
      setSelectedAssigneeKeys([]);
      return;
    }

    if (!isAdmin && user?.id) {
      setSelectedAssigneeKeys([user.id]);
      return;
    }

    setSelectedAssigneeKeys((prev) => {
      const valid = prev.filter((key) => assigneeOptions.some((opt) => opt.key === key));
      if (valid.length > 0) return valid;
      return assigneeOptions.map((opt) => opt.key);
    });
  }, [assigneeOptions, isAdmin, user?.id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    void (async () => {
      try {
        const params = new URLSearchParams({ move_month: monthKey(viewMonth) });
        const res = await fetch(`${API_BASE}/api/sales-calendar?${params.toString()}`, { headers: authHeaders(token) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const payload = (await res.json()) as { items?: Array<Record<string, unknown>> };
        const rows = Array.isArray(payload.items) ? payload.items : [];
        const mapped: SalesCalendarJob[] = rows.map((item) => ({
          id: String(item.id || ""),
          lead_id: String(item.lead_id || ""),
          company_id: String(item.company_id || ""),
          company_name: String(item.company_name || ""),
          company_color: String(item.company_color || ""),
          job_order: Number(item.job_order || 0),
          full_name: String(item.full_name || "Unnamed"),
          move_date: String(item.move_date || ""),
          booked_move_date: String(item.booked_move_date || ""),
          pickup_zip: String(item.pickup_zip || ""),
          delivery_zip: String(item.delivery_zip || ""),
          price: item.price == null ? null : Number(item.price),
          status: String(item.status || ""),
          assigned_to: String(item.assigned_to || ""),
          assigned_to_name: String(item.assigned_to_name || ""),
          assigned_to_role: String(item.assigned_to_role || ""),
        }));
        if (!cancelled) setJobs(mapped);
      } catch (err: unknown) {
        if (!cancelled) {
          setJobs([]);
          setError(err instanceof Error ? err.message : "Failed to load sales calendar");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, viewMonth]);

  const monthlyCountByAssignee = useMemo(() => {
    const counts = new Map<string, number>();
    for (const job of jobs) {
      const key = assigneeKey(job);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return counts;
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    if (selectedAssigneeKeys.length === 0) return [];
    const selected = new Set(selectedAssigneeKeys);
    return jobs.filter((job) => selected.has(assigneeKey(job)));
  }, [jobs, selectedAssigneeKeys]);

  const year = viewMonth.getFullYear();
  const month = viewMonth.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const monthLabel = viewMonth.toLocaleString(undefined, { month: "long", year: "numeric" });

  const jobsByDay = useMemo(() => {
    const map = new Map<number, SalesCalendarJob[]>();
    for (const job of filteredJobs) {
      const parsed = parseCalendarDate(job.booked_move_date || job.move_date);
      if (!parsed) continue;
      if (parsed.getFullYear() !== year || parsed.getMonth() !== month) continue;
      const day = parsed.getDate();
      const bucket = map.get(day) || [];
      bucket.push(job);
      map.set(day, bucket);
    }
    return map;
  }, [filteredJobs, year, month]);

  const backState = useMemo(
    () => ({
      backTo: `${location.pathname}${location.search}`,
      backLabel: "← Back to Sales Calendar",
      backOrigin: "sales-calendar",
    }),
    [location.pathname, location.search]
  );

  return (
    <div style={{ padding: "20px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Sales Calendar</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Jobs grouped by booked move date and assignee for the selected month.
      </p>

      {error ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{error}</p> : null}

      {!loading ? (
        <div style={{ marginBottom: 12, display: "grid", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
            <div style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>Assignees</div>
            <div style={{ fontSize: 12, color: "#334155", fontWeight: 600 }}>
              Total jobs this month: {jobs.length}
              {selectedAssigneeKeys.length > 0 && selectedAssigneeKeys.length !== assigneeOptions.length
                ? ` • Showing ${filteredJobs.length}`
                : ""}
            </div>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <button
              type="button"
              onClick={() => {
                const allKeys = assigneeOptions.map((a) => a.key);
                const isAllSelected = selectedAssigneeKeys.length > 0 && selectedAssigneeKeys.length === assigneeOptions.length;
                setSelectedAssigneeKeys(isAllSelected ? [] : allKeys);
              }}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                border: selectedAssigneeKeys.length > 0 && selectedAssigneeKeys.length === assigneeOptions.length
                  ? "1px solid #0f766e"
                  : "1px solid #cbd5e1",
                background: selectedAssigneeKeys.length > 0 && selectedAssigneeKeys.length === assigneeOptions.length
                  ? "#ccfbf1"
                  : "#fff",
                color: selectedAssigneeKeys.length > 0 && selectedAssigneeKeys.length === assigneeOptions.length
                  ? "#115e59"
                  : "#334155",
                borderRadius: 999,
                padding: "5px 10px",
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: 999, background: "#0f766e", display: "inline-block" }} />
              All ({jobs.length})
            </button>

            {assigneeOptions.map((assignee) => {
              const checked = selectedAssigneeKeys.includes(assignee.key);
              const count = monthlyCountByAssignee.get(assignee.key) || 0;
              const role = roleLabel(assignee.role);
              return (
                <button
                  key={assignee.key}
                  type="button"
                  onClick={() => {
                    setSelectedAssigneeKeys((prev) => checked ? prev.filter((key) => key !== assignee.key) : [...prev, assignee.key]);
                  }}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    border: checked ? "1px solid #2563eb" : "1px solid #cbd5e1",
                    background: checked ? "#dbeafe" : "#fff",
                    color: checked ? "#1e40af" : "#334155",
                    borderRadius: 999,
                    padding: "5px 10px",
                    fontSize: 12,
                    fontWeight: checked ? 700 : 600,
                    cursor: "pointer",
                  }}
                >
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: checked ? "#2563eb" : "#94a3b8", display: "inline-block" }} />
                  {assignee.name}{role ? ` (${role})` : ""} ({count})
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      <section style={{ border: "1px solid #dddbda", borderRadius: 4, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)", marginBottom: 14 }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid #dddbda", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 15, color: "#032d60" }}>Sales Jobs</h2>
            <p style={{ margin: "2px 0 0", fontSize: 12, color: "#64748b" }}>Filtered by booked move date</p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button type="button" onClick={() => setViewMonth((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1))} style={calendarNavBtn}>◀</button>
            <strong style={{ minWidth: 150, textAlign: "center", fontSize: 13, color: "#0f172a" }}>{monthLabel}</strong>
            <button type="button" onClick={() => setViewMonth((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1))} style={calendarNavBtn}>▶</button>
          </div>
        </div>

        {loading ? <p style={{ padding: 10, color: "#3e3e3c", fontSize: 13 }}>Loading calendar...</p> : null}

        <div style={{ padding: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 6, marginBottom: 6 }}>
            {weekdayLabels.map((label) => (
              <div key={label} style={{ fontSize: 11, color: "#64748b", fontWeight: 700, textTransform: "uppercase", textAlign: "center" }}>
                {label}
              </div>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 6 }}>
            {Array.from({ length: firstWeekday }).map((_, i) => (
              <div key={`blank-${i}`} style={calendarBlankCell} />
            ))}

            {Array.from({ length: daysInMonth }).map((_, i) => {
              const day = i + 1;
              const dayJobs = jobsByDay.get(day) || [];
              const visibleJobs = dayJobs.slice(0, 3);
              const overflowCount = Math.max(dayJobs.length - visibleJobs.length, 0);
              return (
                <div key={day} style={calendarDayCell}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#1e293b" }}>{day}</div>
                    {dayJobs.length > 0 ? <span style={{ fontSize: 10, color: "#475569", fontWeight: 700 }}>{dayJobs.length}</span> : null}
                  </div>
                  {dayJobs.length > 0 ? (
                    <div style={{ display: "grid", gap: 6 }}>
                      {visibleJobs.map((job, idx) => (
                        <Link
                          key={job.id}
                          to={`/leads/${job.lead_id || job.id}?job_id=${encodeURIComponent(job.id)}`}
                          state={backState}
                          style={{
                            display: "block",
                            fontSize: 11,
                            color: "#0f172a",
                            textDecoration: "none",
                            background: "#f8fafc",
                            border: "1px solid #dbe4ef",
                            borderRadius: 4,
                            padding: "4px 5px",
                            overflow: "hidden",
                          }}
                          title={`${job.full_name} • ${job.pickup_zip || "?"} -> ${job.delivery_zip || "?"} • ${job.status}`}
                        >
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 600 }}>{job.full_name}</div>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#334155" }}>{job.assigned_to_name || "Unassigned"}</div>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#475569" }}>{job.pickup_zip || "?"} {" -> "} {job.delivery_zip || "?"}</div>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#475569", fontSize: 11 }}>{`Job ${job.job_order || idx + 1}`}</div>
                        </Link>
                      ))}
                      {overflowCount > 0 ? (
                        <div style={{ border: "1px solid #cbd5e1", background: "#f8fafc", borderRadius: 4, color: "#0f172a", fontSize: 11, fontWeight: 700, padding: "4px 6px", textAlign: "left" }}>
                          More +{overflowCount}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}

const calendarNavBtn: React.CSSProperties = {
  border: "1px solid #cbd5e1",
  background: "#fff",
  color: "#0f172a",
  borderRadius: 4,
  width: 28,
  height: 28,
  cursor: "pointer",
  fontSize: 12,
};

const calendarBlankCell: React.CSSProperties = {
  minHeight: 90,
  border: "1px dashed #e2e8f0",
  borderRadius: 4,
  background: "#fafcff",
};

const calendarDayCell: React.CSSProperties = {
  minHeight: 90,
  border: "1px solid #e2e8f0",
  borderRadius: 4,
  background: "#fff",
  padding: 6,
  boxSizing: "border-box",
};
