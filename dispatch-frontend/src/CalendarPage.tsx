import { useCallback, useEffect, useRef, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import type { DatesSetArg, EventClickArg, EventInput } from "@fullcalendar/core";
import { API_BASE } from "./apiConfig";
import { useAuth } from "./AuthContext";
import type { Company, Job } from "./types";
import { JobDetailPanel } from "./JobDetailPanel";
import { JobFormModal } from "./JobFormModal";

// Salesforce-inspired company color palette
const PALETTE = [
  "#1589ee",
  "#4bc076",
  "#ff9900",
  "#9c59d1",
  "#e44d26",
  "#00a1e0",
  "#f6538a",
  "#54698d",
  "#16a0a0",
  "#e65c00",
];

function companyColor(companies: Company[], companyId: string): string {
  const idx = companies.findIndex((c) => c.id === companyId);
  return PALETTE[idx >= 0 ? idx % PALETTE.length : 0];
}

function jobsToEvents(jobs: Job[], companies: Company[]): EventInput[] {
  return jobs.map((job) => {
    const color = companyColor(companies, job.company_id);
    const allDay = !job.start_time;
    const start = allDay ? job.move_date : `${job.move_date}T${job.start_time}`;
    const end =
      !allDay && job.end_time ? `${job.move_date}T${job.end_time}` : undefined;
    return {
      id: job.id,
      title: job.client_name,
      start,
      end,
      allDay,
      backgroundColor: color,
      borderColor: color,
      textColor: "#ffffff",
      extendedProps: job,
    };
  });
}

export default function CalendarPage() {
  const { token, user } = useAuth();
  const calRef = useRef<InstanceType<typeof FullCalendar>>(null);

  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [jobs, setJobs] = useState<Job[]>([]);
  const [dateRange, setDateRange] = useState<{ start: string; end: string } | null>(null);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editJob, setEditJob] = useState<Job | null>(null);

  // Load companies the user is allowed to see
  useEffect(() => {
    fetch(`${API_BASE}/api/companies/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json() as Promise<Company[]>)
      .then((data) => {
        setCompanies(data);
        setSelectedIds(new Set(data.map((c) => c.id)));
      })
      .catch(console.error);
  }, [token]);

  // Fetch jobs for the visible date range and selected companies
  const fetchJobs = useCallback(() => {
    if (!dateRange || selectedIds.size === 0) {
      setJobs([]);
      return;
    }
    const params = new URLSearchParams({ start: dateRange.start, end: dateRange.end });
    selectedIds.forEach((id) => params.append("company_ids", id));
    fetch(`${API_BASE}/api/jobs?${params.toString()}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json() as Promise<Job[]>)
      .then(setJobs)
      .catch(console.error);
  }, [token, dateRange, selectedIds]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const handleDatesSet = (arg: DatesSetArg) => {
    setDateRange({
      start: arg.startStr.slice(0, 10),
      end: arg.endStr.slice(0, 10),
    });
  };

  const handleEventClick = (arg: EventClickArg) => {
    setSelectedJob(arg.event.extendedProps as Job);
  };

  const toggleCompany = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const canEdit = user?.role === "admin" || user?.role === "dispatch";
  const events = jobsToEvents(jobs, companies);

  return (
    <div className={`calendar-layout${selectedJob ? " panel-open" : ""}`}>
      {/* ── Sidebar ───────────────────────────────────────────── */}
      <aside className="calendar-sidebar">
        <div className="sidebar-section-title">Companies</div>
        {companies.map((c, i) => (
          <label key={c.id} className="company-filter-item">
            <input
              type="checkbox"
              checked={selectedIds.has(c.id)}
              onChange={() => toggleCompany(c.id)}
              style={{ accentColor: PALETTE[i % PALETTE.length] }}
            />
            <span
              className="company-dot"
              style={{ background: PALETTE[i % PALETTE.length] }}
            />
            {c.name}
          </label>
        ))}
      </aside>

      {/* ── Calendar ─────────────────────────────────────────── */}
      <div className="calendar-main">
        <FullCalendar
          ref={calRef}
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          initialView="dayGridMonth"
          headerToolbar={{
            left: "prev,next today",
            center: "title",
            right: canEdit
              ? "newJob dayGridMonth,timeGridWeek,timeGridDay"
              : "dayGridMonth,timeGridWeek,timeGridDay",
          }}
          customButtons={
            canEdit
              ? {
                  newJob: {
                    text: "+ New Job",
                    click: () => {
                      setEditJob(null);
                      setShowForm(true);
                    },
                  },
                }
              : {}
          }
          events={events}
          datesSet={handleDatesSet}
          eventClick={handleEventClick}
          height="100%"
          eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: true }}
          dayMaxEvents={4}
        />
      </div>

      {/* ── Detail panel ─────────────────────────────────────── */}
      {selectedJob && (
        <JobDetailPanel
          job={selectedJob}
          token={token!}
          onClose={() => setSelectedJob(null)}
          onEdit={
            canEdit
              ? (j) => {
                  setEditJob(j);
                  setShowForm(true);
                }
              : undefined
          }
          onDeleted={() => {
            setSelectedJob(null);
            fetchJobs();
          }}
        />
      )}

      {/* ── Job form modal ───────────────────────────────────── */}
      {showForm && (
        <JobFormModal
          job={editJob}
          companies={companies}
          token={token!}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false);
            fetchJobs();
          }}
        />
      )}
    </div>
  );
}
