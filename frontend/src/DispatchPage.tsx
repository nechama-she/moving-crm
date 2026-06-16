import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type DispatchPageMode = "calendar" | "manage";

type Company = {
  id: string;
  name: string;
};

type UserCompany = {
  id: string;
  name: string;
};

type AppUser = {
  id: string;
  name: string;
  email: string;
  phone?: string;
  role: string;
  companies?: UserCompany[];
};

type LeadJob = {
  id: string;
  lead_id: string;
  full_name: string;
  move_date: string;
  booked_move_date: string;
  pickup_zip: string;
  delivery_zip: string;
  status: string;
  price?: number | null;
};

type DispatchJobSearchResult = LeadJob & {
  company_id: string;
  company_name: string;
  leadgen_id: string;
};

type DispatchCalendarDaySetting = {
  day_date: string;
  is_full: boolean;
  note: string;
};

function monthKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function parseCalendarDate(raw: string): Date | null {
  const value = (raw || "").trim();
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

export default function DispatchPage({ mode }: { mode?: DispatchPageMode }) {
  const { token, user } = useAuth();
  const isAdmin = user?.role === "admin";
  const isDispatch = user?.role === "dispatch";
  const effectiveMode: DispatchPageMode = mode || (isDispatch ? "calendar" : "manage");
  const showCalendar = effectiveMode === "calendar";
  const showManage = effectiveMode === "manage";

  const [users, setUsers] = useState<AppUser[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const [dispatchCompanies, setDispatchCompanies] = useState<Company[]>([]);
  const [selectedDispatchCompanyId, setSelectedDispatchCompanyId] = useState("");
  const [dispatchMonth, setDispatchMonth] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const [calendarJobs, setCalendarJobs] = useState<LeadJob[]>([]);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [calendarError, setCalendarError] = useState("");
  const [daySettings, setDaySettings] = useState<Record<string, DispatchCalendarDaySetting>>({});
  const [daySettingsError, setDaySettingsError] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [jobSearch, setJobSearch] = useState("");
  const [jobSearchResults, setJobSearchResults] = useState<DispatchJobSearchResult[]>([]);
  const [jobSearchLoading, setJobSearchLoading] = useState(false);
  const [jobSearchError, setJobSearchError] = useState("");
  const [jobSearchOpen, setJobSearchOpen] = useState(false);
  const jobSearchRef = useRef<HTMLDivElement | null>(null);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [selectedCompanyIds, setSelectedCompanyIds] = useState<string[]>([]);

  const dispatchUsers = useMemo(
    () => users.filter((u) => u.role === "dispatch").sort((a, b) => a.name.localeCompare(b.name)),
    [users]
  );

  useEffect(() => {
    if (!isAdmin || !showManage) {
      setLoading(false);
      return;
    }
    void loadData();
  }, [token, isAdmin, showManage]);

  useEffect(() => {
    if (!showCalendar) return;
    void loadDispatchCompanies(isAdmin);
  }, [token, showCalendar, isAdmin]);

  useEffect(() => {
    if (!showCalendar || !selectedDispatchCompanyId) return;
    void loadDispatchCalendarJobs(selectedDispatchCompanyId, dispatchMonth);
    void loadDispatchCalendarDaySettings(selectedDispatchCompanyId, dispatchMonth);
  }, [token, showCalendar, selectedDispatchCompanyId, dispatchMonth]);

  useEffect(() => {
    function onDocMouseDown(event: MouseEvent) {
      if (!jobSearchRef.current) return;
      const target = event.target as Node;
      if (!jobSearchRef.current.contains(target)) {
        setJobSearchOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  useEffect(() => {
    if (!showCalendar) return;
    const q = jobSearch.trim();
    if (q.length < 2) {
      setJobSearchResults([]);
      setJobSearchLoading(false);
      setJobSearchError("");
      return;
    }

    const timeout = setTimeout(() => {
      void (async () => {
        setJobSearchLoading(true);
        setJobSearchError("");
        try {
          const params = new URLSearchParams({ query: q, limit: "10" });
          const res = await fetch(`${API_BASE}/api/dispatch-job-search?${params.toString()}`, { headers: authHeaders(token) });
          if (!res.ok) throw new Error(`Dispatch job search HTTP ${res.status}`);
          const data = (await res.json()) as { items?: Array<Record<string, unknown>> };
          const items = Array.isArray(data.items) ? data.items : [];
          setJobSearchResults(
            items.map((item) => ({
              id: String(item.id || ""),
              lead_id: String(item.lead_id || ""),
              full_name: String(item.full_name || "Unnamed"),
              move_date: String(item.move_date || ""),
              booked_move_date: String(item.booked_move_date || ""),
              pickup_zip: String(item.pickup_zip || ""),
              delivery_zip: String(item.delivery_zip || ""),
              status: String(item.status || ""),
              price: item.price == null ? null : Number(item.price),
              company_id: String(item.company_id || ""),
              company_name: String(item.company_name || ""),
              leadgen_id: String(item.leadgen_id || ""),
            }))
          );
          setJobSearchOpen(true);
        } catch (err: unknown) {
          setJobSearchError(err instanceof Error ? err.message : "Failed to search jobs");
          setJobSearchResults([]);
        } finally {
          setJobSearchLoading(false);
        }
      })();
    }, 250);

    return () => clearTimeout(timeout);
  }, [jobSearch, token, showCalendar]);

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const [usersRes, companiesRes] = await Promise.all([
        fetch(`${API_BASE}/api/users`, { headers: authHeaders(token) }),
        fetch(`${API_BASE}/api/companies`, { headers: authHeaders(token) }),
      ]);
      if (!usersRes.ok) throw new Error(`Users HTTP ${usersRes.status}`);
      if (!companiesRes.ok) throw new Error(`Companies HTTP ${companiesRes.status}`);
      const usersData = (await usersRes.json()) as AppUser[];
      const companiesData = (await companiesRes.json()) as Company[];
      setUsers(usersData || []);
      setCompanies((companiesData || []).sort((a, b) => a.name.localeCompare(b.name)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load dispatch users and companies");
    } finally {
      setLoading(false);
    }
  }

  async function loadDispatchCompanies(forAdmin: boolean) {
    setCalendarError("");
    try {
      const endpoint = forAdmin ? "/api/companies" : "/api/companies/mine";
      const companiesRes = await fetch(`${API_BASE}${endpoint}`, { headers: authHeaders(token) });
      if (!companiesRes.ok) throw new Error(`Companies HTTP ${companiesRes.status}`);

      const companiesData = (await companiesRes.json()) as Company[];
      const assignedCompanies = (companiesData || []).sort((a, b) => a.name.localeCompare(b.name));
      setDispatchCompanies(assignedCompanies);

      if (assignedCompanies.length > 0) {
        setSelectedDispatchCompanyId((prev) =>
          prev && assignedCompanies.some((c) => c.id === prev) ? prev : assignedCompanies[0].id
        );
      } else {
        setSelectedDispatchCompanyId("");
        setCalendarJobs([]);
      }
    } catch (err: unknown) {
      setCalendarError(err instanceof Error ? err.message : "Failed to load companies");
    }
  }

  async function loadDispatchCalendarJobs(companyId: string, month: Date) {
    setCalendarLoading(true);
    setCalendarError("");
    try {
      const params = new URLSearchParams({
        company_id: companyId,
        move_month: monthKey(month),
      });
      const res = await fetch(`${API_BASE}/api/dispatch-calendar?${params.toString()}`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`Dispatch calendar HTTP ${res.status}`);
      const data = (await res.json()) as { items?: Array<Record<string, unknown>> };
      const items = Array.isArray(data.items) ? data.items : [];
      setCalendarJobs(
        items.map((item) => ({
          id: String(item.id || ""),
          lead_id: String(item.lead_id || ""),
          full_name: String(item.full_name || "Unnamed"),
          move_date: String(item.move_date || ""),
          booked_move_date: String(item.booked_move_date || ""),
          pickup_zip: String(item.pickup_zip || ""),
          delivery_zip: String(item.delivery_zip || ""),
          status: String(item.status || ""),
          price: item.price == null ? null : Number(item.price),
        }))
      );
    } catch (err: unknown) {
      setCalendarError(err instanceof Error ? err.message : "Failed to load dispatch jobs");
      setCalendarJobs([]);
    } finally {
      setCalendarLoading(false);
    }
  }

  async function loadDispatchCalendarDaySettings(companyId: string, month: Date) {
    setDaySettingsError("");
    try {
      const params = new URLSearchParams({
        company_id: companyId,
        move_month: monthKey(month),
      });
      const res = await fetch(`${API_BASE}/api/dispatch-calendar-days?${params.toString()}`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`Dispatch day settings HTTP ${res.status}`);
      const data = (await res.json()) as { items?: Array<Record<string, unknown>> };
      const items = Array.isArray(data.items) ? data.items : [];
      const nextMap: Record<string, DispatchCalendarDaySetting> = {};
      for (const item of items) {
        const dayDate = String(item.day_date || "");
        if (!dayDate) continue;
        nextMap[dayDate] = {
          day_date: dayDate,
          is_full: Boolean(item.is_full),
          note: String(item.note || ""),
        };
      }
      setDaySettings(nextMap);
    } catch (err: unknown) {
      setDaySettingsError(err instanceof Error ? err.message : "Failed to load day settings");
      setDaySettings({});
    }
  }

  async function saveDispatchCalendarDaySetting(dayDate: string, isFull: boolean, note: string) {
    if (!selectedDispatchCompanyId) return;
    const cleanNote = note.trim();
    const res = await fetch(`${API_BASE}/api/dispatch-calendar-days`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({
        company_id: selectedDispatchCompanyId,
        day_date: dayDate,
        is_full: isFull,
        note: cleanNote,
      }),
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const err = (await res.json()) as { detail?: string };
        detail = err.detail || detail;
      } catch {
        // keep default detail
      }
      throw new Error(detail);
    }
    const payload = (await res.json()) as { ok?: boolean; item?: Record<string, unknown> | null };
    const item = payload.item;
    setDaySettings((prev) => {
      const next = { ...prev };
      if (!item) {
        delete next[dayDate];
        return next;
      }
      const storedDayDate = String(item.day_date || dayDate);
      next[storedDayDate] = {
        day_date: storedDayDate,
        is_full: Boolean(item.is_full),
        note: String(item.note || ""),
      };
      return next;
    });
  }

  function selectDispatchJob(job: DispatchJobSearchResult) {
    const parsed = parseCalendarDate(job.move_date);
    if (!parsed) return;
    setSelectedJobId(job.id);
    setSelectedDispatchCompanyId(job.company_id);
    setDispatchMonth(new Date(parsed.getFullYear(), parsed.getMonth(), 1));
    setJobSearch(job.full_name);
    setJobSearchResults([]);
    setJobSearchOpen(false);
  }

  function toggleCompany(companyId: string) {
    setSelectedCompanyIds((prev) =>
      prev.includes(companyId) ? prev.filter((id) => id !== companyId) : [...prev, companyId]
    );
  }

  async function copyPassword() {
    if (!password) return;
    try {
      await navigator.clipboard.writeText(password);
      setInfo("Temporary password copied.");
    } catch {
      setError("Could not copy password. Please copy manually.");
    }
  }

  async function createDispatchUser() {
    setError("");
    setInfo("");
    if (!name.trim() || !email.trim() || !password.trim()) {
      setError("Name, email, and password are required.");
      return;
    }

    setSaving(true);
    try {
      const createRes = await fetch(`${API_BASE}/api/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          phone: phone.trim(),
          password,
          role: "dispatch",
        }),
      });
      if (!createRes.ok) {
        const err = await createRes.json().catch(() => ({ detail: "Failed to create dispatch user" }));
        throw new Error(err.detail || "Failed to create dispatch user");
      }

      const created = (await createRes.json()) as AppUser;

      for (const companyId of selectedCompanyIds) {
        const assignRes = await fetch(`${API_BASE}/api/users/${created.id}/companies`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders(token) },
          body: JSON.stringify({ company_id: companyId }),
        });
        if (!assignRes.ok) {
          const err = await assignRes.json().catch(() => ({ detail: "Company assignment failed" }));
          throw new Error(`Created dispatch user but failed assigning company: ${err.detail || assignRes.status}`);
        }
      }

      setInfo("Dispatch user created.");
      setName("");
      setEmail("");
      setPhone("");
      setPassword("");
      setShowPassword(false);
      setSelectedCompanyIds([]);
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create dispatch user");
    } finally {
      setSaving(false);
    }
  }

  async function assignCompany(userId: string, companyId: string) {
    if (!companyId) return;
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/${userId}/companies`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ company_id: companyId }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to assign company" }));
        throw new Error(err.detail || "Failed to assign company");
      }
      setInfo("Company assigned.");
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to assign company");
    }
  }

  async function unassignCompany(userId: string, companyId: string) {
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/${userId}/companies/${companyId}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to remove company" }));
        throw new Error(err.detail || "Failed to remove company");
      }
      setInfo("Company removed from dispatch user.");
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to remove company");
    }
  }

  if (showCalendar) {
    return (
      <div style={{ padding: "20px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
        <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Dispatcher Console</h1>
        <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
          Jobs grouped by booked move date for the selected company and month.
        </p>

        {calendarError ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{calendarError}</p> : null}
        {daySettingsError ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{daySettingsError}</p> : null}

        {!calendarLoading && dispatchCompanies.length > 1 ? (
          <div style={{ marginBottom: 12, maxWidth: 340 }}>
            <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569", fontWeight: 600 }}>
              Company
              <select
                value={selectedDispatchCompanyId}
                onChange={(e) => setSelectedDispatchCompanyId(e.target.value)}
                style={inputStyle}
              >
                {dispatchCompanies.map((company) => (
                  <option key={company.id} value={company.id}>{company.name}</option>
                ))}
              </select>
            </label>
          </div>
        ) : null}

        {calendarLoading ? <p style={{ color: "#3e3e3c", fontSize: 13 }}>Loading calendar...</p> : null}

        {!calendarLoading && dispatchCompanies.length === 0 ? (
          <div style={{ border: "1px solid #dddbda", borderRadius: 4, background: "#fff", padding: 14 }}>
            <p style={{ margin: 0, color: "#3e3e3c", fontSize: 13 }}>
              No companies are assigned to your dispatch user yet.
            </p>
          </div>
        ) : null}

        <div ref={jobSearchRef} style={{ marginBottom: 12, maxWidth: 520, position: "relative" }}>
          <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569", fontWeight: 600 }}>
            Search dispatch jobs
            <input
              value={jobSearch}
              onChange={(e) => {
                setJobSearch(e.target.value);
                setJobSearchOpen(true);
              }}
              onFocus={() => setJobSearchOpen(true)}
              placeholder="Search jobs by name, lead id, zip, or SmartMoving id..."
              style={inputStyle}
            />
          </label>
          {jobSearchLoading ? <div style={{ marginTop: 4, fontSize: 12, color: "#64748b" }}>Searching...</div> : null}
          {jobSearchError ? <div style={{ marginTop: 4, fontSize: 12, color: "#ba0517" }}>{jobSearchError}</div> : null}
          {jobSearchOpen && jobSearch.trim().length >= 2 ? (
            <div
              style={{
                position: "absolute",
                top: "calc(100% + 4px)",
                left: 0,
                right: 0,
                zIndex: 30,
                background: "#fff",
                border: "1px solid #cbd5e1",
                borderRadius: 6,
                boxShadow: "0 12px 24px rgba(15,23,42,.12)",
                maxHeight: 320,
                overflowY: "auto",
              }}
            >
              {jobSearchResults.length === 0 && !jobSearchLoading ? (
                <div style={{ padding: 10, fontSize: 13, color: "#64748b" }}>No jobs found.</div>
              ) : null}
              {jobSearchResults.map((job) => (
                <button
                  key={job.id}
                  type="button"
                  onClick={() => selectDispatchJob(job)}
                  style={{
                    width: "100%",
                    display: "grid",
                    gap: 2,
                    textAlign: "left",
                    border: "none",
                    background: "#fff",
                    padding: "10px 12px",
                    cursor: "pointer",
                    borderBottom: "1px solid #e2e8f0",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <strong style={{ fontSize: 13, color: "#0f172a" }}>{job.full_name || "Unnamed"}</strong>
                    <span style={{ fontSize: 11, color: "#475569", fontWeight: 600 }}>{job.move_date}</span>
                  </div>
                  <div style={{ fontSize: 12, color: "#334155" }}>
                    {job.company_name || "Company"} • {job.pickup_zip || "?"} → {job.delivery_zip || "?"}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b" }}>
                    {job.leadgen_id ? `Lead ${job.leadgen_id} • ` : ""}{job.status || "booked"}
                  </div>
                </button>
              ))}
            </div>
          ) : null}
        </div>

        {!calendarLoading && selectedDispatchCompanyId ? (
          <CompanyCalendar
            companyName={dispatchCompanies.find((c) => c.id === selectedDispatchCompanyId)?.name || "Company"}
            jobs={calendarJobs}
            daySettings={daySettings}
            viewDate={dispatchMonth}
            selectedJobId={selectedJobId}
            onPrevMonth={() => setDispatchMonth((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1))}
            onNextMonth={() => setDispatchMonth((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1))}
            onSaveDaySetting={saveDispatchCalendarDaySetting}
          />
        ) : null}
      </div>
    );
  }

  if (showManage && !isAdmin) {
    return (
      <div style={{ padding: "20px 24px" }}>
        <h1 style={{ fontSize: 20, color: "#032d60", marginBottom: 8 }}>Dispatcher Setup</h1>
        <p style={{ color: "#ba0517" }}>You do not have access to this page.</p>
      </div>
    );
  }

  if (!showManage) {
    return (
      <div style={{ padding: "20px 24px" }}>
        <h1 style={{ fontSize: 20, color: "#032d60", marginBottom: 8 }}>Dispatcher Page</h1>
        <p style={{ color: "#ba0517" }}>Unknown dispatch page mode.</p>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Dispatcher Setup</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Create dispatch users and map them to the companies they can access.
      </p>

      <div style={{ border: "1px solid #dddbda", borderRadius: 4, padding: 16, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)", marginBottom: 14 }}>
        <h2 style={sectionHeader}>Create Dispatch User</h2>
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <label style={fieldLabel}>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Phone (optional)
            <input value={phone} onChange={(e) => setPhone(e.target.value)} style={inputStyle} />
          </label>
          <label style={fieldLabel}>
            Temporary Password
            <div style={{ display: "grid", gap: 4 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  style={{ ...inputStyle, flex: 1, height: 34 }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "0 10px", fontSize: 12, height: 34 }}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
                <button
                  type="button"
                  onClick={() => void copyPassword()}
                  disabled={!password}
                  style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "0 10px", fontSize: 12, height: 34 }}
                >
                  Copy
                </button>
              </div>
              <span style={{ display: "block", width: "100%", marginTop: 0, fontSize: 11, lineHeight: 1.35, color: "#706e6b", paddingLeft: 10 }}>
                This is the password the dispatch user will use for first login.
              </span>
            </div>
          </label>
        </div>

        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#3e3e3c", marginBottom: 6 }}>Assign Companies</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {companies.map((company) => {
              const checked = selectedCompanyIds.includes(company.id);
              return (
                <button
                  type="button"
                  key={company.id}
                  onClick={() => toggleCompany(company.id)}
                  style={{
                    border: checked ? "1px solid #0176d3" : "1px solid #c9c7c5",
                    background: checked ? "#eaf5fe" : "#fff",
                    color: checked ? "#014486" : "#3e3e3c",
                    borderRadius: 16,
                    padding: "5px 10px",
                    fontSize: 12,
                  }}
                >
                  {company.name}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ marginTop: 14 }}>
          <button
            type="button"
            onClick={createDispatchUser}
            disabled={saving}
            style={{ border: "none", background: saving ? "#5a9fd4" : "#0176d3", color: "#fff", borderRadius: 4, padding: "8px 14px", fontWeight: 600 }}
          >
            {saving ? "Creating..." : "Create Dispatch User"}
          </button>
        </div>
      </div>

      {error ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{error}</p> : null}
      {info ? <p style={{ marginBottom: 10, color: "#2e844a", fontSize: 13 }}>{info}</p> : null}

      <div style={{ border: "1px solid #dddbda", borderRadius: 4, overflow: "auto", background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 900 }}>
          <thead>
            <tr>
              <th style={th}>Name</th>
              <th style={th}>Email</th>
              <th style={th}>Phone</th>
              <th style={th}>Companies</th>
              <th style={th}>Assign Company</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td style={td} colSpan={5}>Loading...</td>
              </tr>
            ) : null}
            {!loading && dispatchUsers.length === 0 ? (
              <tr>
                <td style={td} colSpan={5}>No dispatch users yet.</td>
              </tr>
            ) : null}

            {!loading && dispatchUsers.map((dispatchUser) => (
              <DispatchRow
                key={dispatchUser.id}
                dispatchUser={dispatchUser}
                companies={companies}
                onAssign={assignCompany}
                onUnassign={unassignCompany}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CompanyCalendar({
  companyName,
  jobs,
  daySettings,
  viewDate,
  selectedJobId,
  onPrevMonth,
  onNextMonth,
  onSaveDaySetting,
}: {
  companyName: string;
  jobs: LeadJob[];
  daySettings: Record<string, DispatchCalendarDaySetting>;
  viewDate: Date;
  selectedJobId: string;
  onPrevMonth: () => void;
  onNextMonth: () => void;
  onSaveDaySetting: (dayDate: string, isFull: boolean, note: string) => Promise<void>;
}) {
  const [selectedJobTabByDay, setSelectedJobTabByDay] = useState<Record<number, number>>({});
  const [savingDayByDay, setSavingDayByDay] = useState<Record<number, boolean>>({});
  const [dayErrorByDay, setDayErrorByDay] = useState<Record<number, string>>({});
  const [noteModalDay, setNoteModalDay] = useState<number | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [noteModalError, setNoteModalError] = useState("");
  const [noteModalSaving, setNoteModalSaving] = useState(false);
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const monthLabel = viewDate.toLocaleString(undefined, { month: "long", year: "numeric" });

  const jobsByDay = new Map<number, LeadJob[]>();
  for (const job of jobs) {
    const parsed = parseCalendarDate(job.move_date);
    if (!parsed) continue;
    if (parsed.getFullYear() !== year || parsed.getMonth() !== month) continue;
    const day = parsed.getDate();
    const bucket = jobsByDay.get(day) || [];
    bucket.push(job);
    jobsByDay.set(day, bucket);
  }

  useEffect(() => {
    if (!selectedJobId) return;
    const selectedJob = jobs.find((job) => job.id === selectedJobId);
    if (!selectedJob) return;
    const parsed = parseCalendarDate(selectedJob.move_date);
    if (!parsed || parsed.getFullYear() !== year || parsed.getMonth() !== month) return;
    const day = parsed.getDate();
    const dayJobs = jobsByDay.get(day) || [];
    const selectedIndex = dayJobs.findIndex((job) => job.id === selectedJobId);
    if (selectedIndex >= 0) {
      setSelectedJobTabByDay((prev) => (prev[day] === selectedIndex ? prev : { ...prev, [day]: selectedIndex }));
    }
  }, [jobs, selectedJobId, year, month]);

  function dayDateKey(day: number): string {
    return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }

  function openNoteModal(day: number) {
    const key = dayDateKey(day);
    const setting = daySettings[key];
    setNoteDraft(setting?.note || "");
    setNoteModalError("");
    setNoteModalDay(day);
  }

  async function toggleFullDay(day: number) {
    const key = dayDateKey(day);
    const currentSetting = daySettings[key];
    const nextIsFull = !Boolean(currentSetting?.is_full);
    const note = currentSetting?.note || "";
    setSavingDayByDay((prev) => ({ ...prev, [day]: true }));
    setDayErrorByDay((prev) => ({ ...prev, [day]: "" }));
    try {
      await onSaveDaySetting(key, nextIsFull, note);
    } catch (err: unknown) {
      setDayErrorByDay((prev) => ({ ...prev, [day]: err instanceof Error ? err.message : "Failed to save day" }));
    } finally {
      setSavingDayByDay((prev) => ({ ...prev, [day]: false }));
    }
  }

  async function saveNoteModal() {
    if (noteModalDay == null) return;
    const key = dayDateKey(noteModalDay);
    const currentSetting = daySettings[key];
    const isFull = Boolean(currentSetting?.is_full);
    setNoteModalSaving(true);
    setNoteModalError("");
    try {
      await onSaveDaySetting(key, isFull, noteDraft);
      setNoteModalDay(null);
    } catch (err: unknown) {
      setNoteModalError(err instanceof Error ? err.message : "Failed to save note");
    } finally {
      setNoteModalSaving(false);
    }
  }

  return (
    <section style={{ border: "1px solid #dddbda", borderRadius: 4, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)", marginBottom: 14 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid #dddbda", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 15, color: "#032d60" }}>{companyName}</h2>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "#64748b" }}>Filtered by selected month</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button type="button" onClick={onPrevMonth} style={calendarNavBtn}>◀</button>
          <strong style={{ minWidth: 150, textAlign: "center", fontSize: 13, color: "#0f172a" }}>{monthLabel}</strong>
          <button type="button" onClick={onNextMonth} style={calendarNavBtn}>▶</button>
        </div>
      </div>

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
            const dayKey = dayDateKey(day);
            const daySetting = daySettings[dayKey];
            const isFullDay = Boolean(daySetting?.is_full);
            const dayNote = daySetting?.note || "";
            const isSelectedDay = selectedJobId ? dayJobs.some((job) => job.id === selectedJobId) : false;
            const isSavingDay = Boolean(savingDayByDay[day]);
            const dayError = dayErrorByDay[day] || "";
            const selectedTab = selectedJobTabByDay[day] ?? 0;
            const normalizedTab = Math.min(selectedTab, Math.max(dayJobs.length - 1, 0));
            const activeJob = dayJobs[normalizedTab] || null;
            return (
              <div
                key={day}
                style={{
                  ...calendarDayCell,
                  border: isSelectedDay ? "1px solid #2563eb" : calendarDayCell.border,
                  boxShadow: isSelectedDay ? "0 0 0 2px rgba(37, 99, 235, 0.15)" : undefined,
                  background: isSelectedDay ? "#eff6ff" : (isFullDay ? "#fff7ed" : calendarDayCell.background),
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "#1e293b" }}>{day}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <button
                      type="button"
                      onClick={() => openNoteModal(day)}
                      style={{
                        ...calendarActionIconBtn,
                        borderColor: dayNote ? "#0176d3" : "#cbd5e1",
                        background: dayNote ? "#eaf5fe" : "#fff",
                      }}
                      title={dayNote ? "View or edit day note" : "Add day note"}
                      aria-label={dayNote ? "View or edit day note" : "Add day note"}
                    >
                      <NoteIcon active={Boolean(dayNote)} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void toggleFullDay(day)}
                      disabled={isSavingDay}
                      style={{
                        ...calendarActionIconBtn,
                        borderColor: isFullDay ? "#0176d3" : "#cbd5e1",
                        background: isFullDay ? "#0176d3" : "#fff",
                        color: isFullDay ? "#fff" : "#334155",
                        opacity: isSavingDay ? 0.6 : 1,
                      }}
                      title={isFullDay ? "Day is full (click to turn off)" : "Mark day as full"}
                      aria-label={isFullDay ? "Day is full (click to turn off)" : "Mark day as full"}
                    >
                      <FullDayIcon active={isFullDay} />
                    </button>
                    {isFullDay ? (
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#9a3412", background: "#ffedd5", borderRadius: 999, padding: "2px 6px" }}>
                        Full
                      </span>
                    ) : null}
                    {isSelectedDay ? (
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#1d4ed8", background: "#dbeafe", borderRadius: 999, padding: "2px 6px" }}>
                        Selected
                      </span>
                    ) : null}
                  </div>
                </div>
                {dayNote ? (
                  <div style={{ marginBottom: 6, fontSize: 10, color: "#334155", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 4, padding: "4px 5px" }} title={dayNote}>
                    {dayNote.length > 60 ? `${dayNote.slice(0, 60)}...` : dayNote}
                  </div>
                ) : null}
                {dayError ? <div style={{ marginBottom: 6, fontSize: 10, color: "#ba0517" }}>{dayError}</div> : null}
                {dayJobs.length > 0 ? (
                  <div style={{ display: "grid", gap: 6 }}>
                    <div style={{ display: "flex", gap: 4, overflowX: "auto", paddingBottom: 2 }}>
                      {dayJobs.map((job, idx) => {
                        const isActive = idx === normalizedTab;
                        return (
                          <button
                            key={job.id}
                            type="button"
                            onClick={() => setSelectedJobTabByDay((prev) => ({ ...prev, [day]: idx }))}
                            style={{
                              border: isActive ? "1px solid #0176d3" : "1px solid #cbd5e1",
                              borderBottom: isActive ? "2px solid #0176d3" : "1px solid #cbd5e1",
                              background: isActive ? "#eaf5fe" : "#fff",
                              color: isActive ? "#014486" : "#334155",
                              borderRadius: 4,
                              padding: "3px 8px",
                              fontSize: 11,
                              fontWeight: 600,
                              whiteSpace: "nowrap",
                              cursor: "pointer",
                            }}
                          >
                            {`Job ${idx + 1}`}
                          </button>
                        );
                      })}
                    </div>
                    {activeJob ? (
                      <Link
                        to={`/leads/${activeJob.lead_id || activeJob.id}`}
                        style={{
                          display: "block",
                          fontSize: 11,
                          color: activeJob.id === selectedJobId ? "#0f172a" : "#0b5cab",
                          textDecoration: "none",
                          background: activeJob.id === selectedJobId ? "#bfdbfe" : "#eaf5fe",
                          border: activeJob.id === selectedJobId ? "1px solid #2563eb" : "1px solid #c9e6ff",
                          borderRadius: 4,
                          padding: "4px 5px",
                          overflow: "hidden",
                          boxShadow: activeJob.id === selectedJobId ? "0 0 0 1px rgba(37, 99, 235, 0.2)" : undefined,
                        }}
                        title={`${activeJob.full_name} • ${activeJob.pickup_zip || "?"} -> ${activeJob.delivery_zip || "?"} • ${activeJob.status}`}
                      >
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 600 }}>{activeJob.full_name}</div>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#475569" }}>{activeJob.pickup_zip || "?"}{" -> "}{activeJob.delivery_zip || "?"}</div>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: activeJob.id === selectedJobId ? "#1d4ed8" : "#0369a1" }}>{activeJob.status || "booked"}</div>
                        {activeJob.price != null ? <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#0f766e" }}>${activeJob.price.toFixed(2)}</div> : null}
                      </Link>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      {noteModalDay != null ? (
        <div
          role="presentation"
          onClick={() => {
            if (!noteModalSaving) {
              setNoteModalDay(null);
              setNoteModalError("");
            }
          }}
          style={{ position: "fixed", inset: 0, background: "rgba(15, 23, 42, 0.55)", zIndex: 90, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
        >
          <div
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
            style={{ width: "min(540px, 100%)", background: "#fff", borderRadius: 8, border: "1px solid #cbd5e1", boxShadow: "0 20px 36px rgba(15,23,42,0.2)" }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "12px 14px", borderBottom: "1px solid #e2e8f0" }}>
              <strong style={{ fontSize: 14, color: "#0f172a" }}>Day Note • {dayDateKey(noteModalDay)}</strong>
              <button
                type="button"
                onClick={() => {
                  if (!noteModalSaving) {
                    setNoteModalDay(null);
                    setNoteModalError("");
                  }
                }}
                disabled={noteModalSaving}
                style={{ border: "1px solid #cbd5e1", background: "#fff", color: "#334155", borderRadius: 4, padding: "4px 8px", fontSize: 12 }}
              >
                Close
              </button>
            </div>
            <div style={{ padding: 14 }}>
              <label style={{ display: "grid", gap: 6, fontSize: 12, color: "#334155", fontWeight: 600 }}>
                Note
                <textarea
                  value={noteDraft}
                  onChange={(e) => setNoteDraft(e.target.value)}
                  placeholder="Add context for dispatchers (parking, access, constraints, etc.)"
                  rows={6}
                  style={{ width: "100%", boxSizing: "border-box", border: "1px solid #cbd5e1", borderRadius: 6, padding: "8px 10px", fontSize: 13, resize: "vertical" }}
                />
              </label>
              {noteModalError ? <div style={{ marginTop: 8, fontSize: 12, color: "#ba0517" }}>{noteModalError}</div> : null}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
                <button
                  type="button"
                  onClick={() => {
                    setNoteModalDay(null);
                    setNoteModalError("");
                  }}
                  disabled={noteModalSaving}
                  style={{ border: "1px solid #cbd5e1", background: "#fff", color: "#334155", borderRadius: 4, padding: "7px 12px", fontSize: 12, fontWeight: 600 }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void saveNoteModal()}
                  disabled={noteModalSaving}
                  style={{ border: "1px solid #0176d3", background: "#0176d3", color: "#fff", borderRadius: 4, padding: "7px 12px", fontSize: 12, fontWeight: 600 }}
                >
                  {noteModalSaving ? "Saving..." : "Save Note"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function NoteIcon({ active }: { active: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
      <path
        d="M6 3h9l3 3v15H6z"
        fill={active ? "#0176d3" : "none"}
        stroke={active ? "#0176d3" : "currentColor"}
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M15 3v4h4" fill="none" stroke={active ? "#fff" : "currentColor"} strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M9 11h6M9 14h6" fill="none" stroke={active ? "#fff" : "currentColor"} strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function FullDayIcon({ active }: { active: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
      <rect
        x="3.5"
        y="5"
        width="17"
        height="15"
        rx="2.5"
        fill={active ? "#fff" : "none"}
        stroke={active ? "#fff" : "currentColor"}
        strokeWidth="1.6"
      />
      <path d="M8 3.5v3M16 3.5v3M3.5 9h17" fill="none" stroke={active ? "#fff" : "currentColor"} strokeWidth="1.6" strokeLinecap="round" />
      <path d="M9 14l2 2 4-4" fill="none" stroke={active ? "#0176d3" : "currentColor"} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DispatchRow({
  dispatchUser,
  companies,
  onAssign,
  onUnassign,
}: {
  dispatchUser: AppUser;
  companies: Company[];
  onAssign: (userId: string, companyId: string) => Promise<void>;
  onUnassign: (userId: string, companyId: string) => Promise<void>;
}) {
  const [selectedCompanyId, setSelectedCompanyId] = useState("");
  const assigned = dispatchUser.companies || [];
  const assignedIds = new Set(assigned.map((c) => c.id));
  const availableCompanies = companies.filter((c) => !assignedIds.has(c.id));

  return (
    <tr style={{ borderTop: "1px solid #e5e7eb" }}>
      <td style={td}>{dispatchUser.name}</td>
      <td style={td}>{dispatchUser.email}</td>
      <td style={td}>{dispatchUser.phone || ""}</td>
      <td style={td}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {assigned.length === 0 ? <span style={{ color: "#706e6b", fontSize: 12 }}>No companies</span> : null}
          {assigned.map((c) => (
            <span key={c.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, border: "1px solid #c9c7c5", borderRadius: 16, padding: "3px 8px", fontSize: 12, color: "#3e3e3c", background: "#f8f9fa" }}>
              {c.name}
              <button
                type="button"
                onClick={() => void onUnassign(dispatchUser.id, c.id)}
                style={{ border: "none", background: "transparent", color: "#ba0517", fontSize: 12, padding: 0, cursor: "pointer" }}
                title="Remove"
              >
                x
              </button>
            </span>
          ))}
        </div>
      </td>
      <td style={td}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={selectedCompanyId} onChange={(e) => setSelectedCompanyId(e.target.value)} style={{ ...inputStyle, minWidth: 220 }}>
            <option value="">Select company...</option>
            {availableCompanies.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void onAssign(dispatchUser.id, selectedCompanyId)}
            disabled={!selectedCompanyId}
            style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "6px 10px", fontSize: 12, fontWeight: 600 }}
          >
            Assign
          </button>
        </div>
      </td>
    </tr>
  );
}

const sectionHeader: React.CSSProperties = {
  margin: "0 0 10px",
  fontSize: 13,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "#3e3e3c",
};

const fieldLabel: React.CSSProperties = {
  display: "grid",
  gap: 5,
  fontSize: 13,
  fontWeight: 600,
  color: "#3e3e3c",
};

const inputStyle: React.CSSProperties = {
  border: "1px solid #dddbda",
  borderRadius: 4,
  padding: "8px 10px",
  background: "#fff",
  fontSize: 13,
};

const th: React.CSSProperties = {
  padding: "9px 12px",
  textAlign: "left",
  fontSize: 11,
  fontWeight: 700,
  color: "#3e3e3c",
  borderBottom: "2px solid #dddbda",
  whiteSpace: "nowrap",
  background: "#f3f2f2",
  textTransform: "uppercase",
  letterSpacing: "0.04em",
};

const td: React.CSSProperties = {
  padding: "10px 12px",
  fontSize: 13,
  color: "#111827",
  verticalAlign: "top",
};

const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

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

const calendarActionIconBtn: React.CSSProperties = {
  border: "1px solid #cbd5e1",
  background: "#fff",
  color: "#334155",
  borderRadius: 6,
  width: 24,
  height: 24,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 0,
  cursor: "pointer",
};
