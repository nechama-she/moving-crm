import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type DispatchPageMode = "calendar" | "manage";

type Company = {
  id: string;
  name: string;
  color?: string;
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
  company_id?: string;
  company_name?: string;
  company_color?: string;
  job_order?: number;
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

type CompanyTone = {
  tint: string;
  border: string;
  text: string;
};

const DEFAULT_COMPANY_TONE: CompanyTone = Object.freeze({ tint: "#e0f2fe", border: "#7dd3fc", text: "#0c4a6e" });

function companyKeyForJob(job: LeadJob): string {
  return job.company_name || job.company_id || "unknown";
}

function toneForCompanyColor(companyColor?: string, companyName?: string): CompanyTone {
  const normalizedColor = normalizeHexColor(companyColor) || generateCompanyColorFromName(companyName);
  if (!normalizedColor) return DEFAULT_COMPANY_TONE;

  return {
    tint: mixHexColors(normalizedColor, "#ffffff", 0.82),
    border: mixHexColors(normalizedColor, "#ffffff", 0.48),
    text: mixHexColors(normalizedColor, "#111827", 0.35),
  };
}

function monthKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function parseMonthFromSearch(search: string): Date | null {
  const params = new URLSearchParams(search);
  const raw = (params.get("move_month") || "").trim();
  const match = raw.match(/^(\d{4})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (!Number.isFinite(year) || !Number.isFinite(month) || month < 1 || month > 12) return null;
  return new Date(year, month - 1, 1);
}

function parseDispatchCompanySelectionFromSearch(search: string): { ids: string[]; hasParam: boolean } {
  const params = new URLSearchParams(search);
  if (!params.has("dispatch_company_ids")) {
    return { ids: [], hasParam: false };
  }
  const raw = (params.get("dispatch_company_ids") || "").trim();
  if (!raw || raw === "__none__") {
    return { ids: [], hasParam: true };
  }

  const seen = new Set<string>();
  const ids = raw
    .split(",")
    .map((part) => part.trim())
    .filter((part) => {
      if (!part || seen.has(part)) return false;
      seen.add(part);
      return true;
    });

  return { ids, hasParam: true };
}

function parseCalendarDate(raw: string): Date | null {
  const value = (raw || "").trim();
  if (!value) return null;
  const ymd = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (ymd) {
    const year = Number(ymd[1]);
    const month = Number(ymd[2]);
    const day = Number(ymd[3]);
    const localDate = new Date(year, month - 1, day);
    if (Number.isNaN(localDate.getTime())) return null;
    return localDate;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function normalizeHexColor(value?: string): string | null {
  const raw = (value || "").trim();
  if (!/^#[0-9a-fA-F]{6}$/.test(raw)) return null;
  return raw.toLowerCase();
}

function mixHexColors(baseHex: string, mixHex: string, mixRatio: number): string {
  const baseRgb = hexToRgb(baseHex);
  const mixRgb = hexToRgb(mixHex);
  if (!baseRgb || !mixRgb) return baseHex;

  const ratio = Math.max(0, Math.min(1, mixRatio));
  return rgbToHex({
    red: Math.round(baseRgb.red * (1 - ratio) + mixRgb.red * ratio),
    green: Math.round(baseRgb.green * (1 - ratio) + mixRgb.green * ratio),
    blue: Math.round(baseRgb.blue * (1 - ratio) + mixRgb.blue * ratio),
  });
}

function hexToRgb(hex: string): { red: number; green: number; blue: number } | null {
  const normalized = normalizeHexColor(hex);
  if (!normalized) return null;
  return {
    red: Number.parseInt(normalized.slice(1, 3), 16),
    green: Number.parseInt(normalized.slice(3, 5), 16),
    blue: Number.parseInt(normalized.slice(5, 7), 16),
  };
}

function rgbToHex(rgb: { red: number; green: number; blue: number }): string {
  return `#${rgb.red.toString(16).padStart(2, "0")}${rgb.green.toString(16).padStart(2, "0")}${rgb.blue.toString(16).padStart(2, "0")}`;
}

function generateCompanyColorFromName(name?: string): string | null {
  const normalizedName = (name || "").trim().toLowerCase();
  if (!normalizedName) return null;

  let hash = 2166136261;
  for (let idx = 0; idx < normalizedName.length; idx += 1) {
    hash ^= normalizedName.charCodeAt(idx);
    hash = Math.imul(hash, 16777619);
  }

  const byte0 = (hash >>> 24) & 0xff;
  const byte1 = (hash >>> 16) & 0xff;
  const byte2 = (hash >>> 8) & 0xff;
  const byte3 = hash & 0xff;

  const hue = ((byte0 << 8) | byte1) % 360;
  const saturation = 58 + (byte2 % 15);
  const lightness = 42 + (byte3 % 12);

  return hslToHex(hue, saturation / 100, lightness / 100);
}

function hslToHex(hue: number, saturation: number, lightness: number): string {
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const hueSection = hue / 60;
  const xVal = chroma * (1 - Math.abs((hueSection % 2) - 1));

  let red1 = 0;
  let green1 = 0;
  let blue1 = 0;

  if (hueSection >= 0 && hueSection < 1) {
    red1 = chroma;
    green1 = xVal;
  } else if (hueSection < 2) {
    red1 = xVal;
    green1 = chroma;
  } else if (hueSection < 3) {
    green1 = chroma;
    blue1 = xVal;
  } else if (hueSection < 4) {
    green1 = xVal;
    blue1 = chroma;
  } else if (hueSection < 5) {
    red1 = xVal;
    blue1 = chroma;
  } else {
    red1 = chroma;
    blue1 = xVal;
  }

  const match = lightness - chroma / 2;
  return rgbToHex({
    red: Math.round((red1 + match) * 255),
    green: Math.round((green1 + match) * 255),
    blue: Math.round((blue1 + match) * 255),
  });
}

export default function DispatchPage({ mode }: { mode?: DispatchPageMode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { token, user } = useAuth();
  const dispatchCompanySelectionFromSearch = useMemo(
    () => parseDispatchCompanySelectionFromSearch(location.search),
    [location.search]
  );
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
  const [selectedDispatchCompanyIds, setSelectedDispatchCompanyIds] = useState<string[]>(
    () => parseDispatchCompanySelectionFromSearch(location.search).ids
  );
  const [dispatchMonth, setDispatchMonth] = useState(() => {
    const fromSearch = parseMonthFromSearch(location.search);
    if (fromSearch) return fromSearch;
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
  const handledRouteJobIdRef = useRef("");
  const singleSelectedDispatchCompanyId = selectedDispatchCompanyIds.length === 1 ? selectedDispatchCompanyIds[0] : "";

  const filteredCalendarJobs = useMemo(() => {
    if (selectedDispatchCompanyIds.length === 0) return [];
    if (selectedDispatchCompanyIds.length === dispatchCompanies.length) return calendarJobs;
    const selected = new Set(selectedDispatchCompanyIds);
    return calendarJobs.filter((job) => selected.has(String((job as unknown as { company_id?: string }).company_id || "")));
  }, [calendarJobs, selectedDispatchCompanyIds, dispatchCompanies.length]);

  const monthlyJobsByCompanyId = useMemo(() => {
    const counts = new Map<string, number>();
    for (const job of calendarJobs) {
      const companyId = String((job as unknown as { company_id?: string }).company_id || "");
      if (!companyId) continue;
      counts.set(companyId, (counts.get(companyId) || 0) + 1);
    }
    return counts;
  }, [calendarJobs]);

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
    if (!showCalendar) return;
    void loadDispatchCalendarJobs(dispatchMonth);
  }, [token, showCalendar, dispatchMonth]);

  useEffect(() => {
    if (!showCalendar) return;
    const params = new URLSearchParams(location.search);
    const targetMonth = monthKey(dispatchMonth);
    let didChange = false;

    if (params.get("move_month") !== targetMonth) {
      params.set("move_month", targetMonth);
      didChange = true;
    }

    if (dispatchCompanies.length > 0) {
      const currentRaw = (params.get("dispatch_company_ids") || "").trim();
      if (selectedDispatchCompanyIds.length === dispatchCompanies.length) {
        if (params.has("dispatch_company_ids")) {
          params.delete("dispatch_company_ids");
          didChange = true;
        }
      } else if (selectedDispatchCompanyIds.length === 0) {
        if (currentRaw !== "__none__") {
          params.set("dispatch_company_ids", "__none__");
          didChange = true;
        }
      } else {
        const nextRaw = selectedDispatchCompanyIds.join(",");
        if (currentRaw !== nextRaw) {
          params.set("dispatch_company_ids", nextRaw);
          didChange = true;
        }
      }
    }

    if (!didChange) return;
    navigate({ pathname: location.pathname, search: `?${params.toString()}` }, { replace: true });
  }, [
    showCalendar,
    dispatchMonth,
    selectedDispatchCompanyIds,
    dispatchCompanies.length,
    location.pathname,
    location.search,
    navigate,
  ]);

  useEffect(() => {
    if (!showCalendar || !singleSelectedDispatchCompanyId) {
      setDaySettings({});
      setDaySettingsError("");
      return;
    }
    void loadDispatchCalendarDaySettings(singleSelectedDispatchCompanyId, dispatchMonth);
  }, [token, showCalendar, singleSelectedDispatchCompanyId, dispatchMonth]);

  useEffect(() => {
    if (!showCalendar || dispatchCompanies.length === 0) return;
    const params = new URLSearchParams(location.search);
    const routeJobId = (params.get("job_id") || "").trim();
    if (!routeJobId) return;
    if (handledRouteJobIdRef.current === routeJobId) return;
    void focusDispatchJobById(routeJobId);
  }, [showCalendar, dispatchCompanies, location.search]);

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
              job_order: Number(item.job_order || 0),
              full_name: String(item.full_name || "Unnamed"),
              move_date: String(item.move_date || ""),
              booked_move_date: String(item.booked_move_date || ""),
              pickup_zip: String(item.pickup_zip || ""),
              delivery_zip: String(item.delivery_zip || ""),
              status: String(item.status || ""),
              price: item.price == null ? null : Number(item.price),
              company_id: String(item.company_id || ""),
              company_name: String(item.company_name || ""),
              company_color: String(item.company_color || ""),
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
        setSelectedDispatchCompanyIds((prev) => {
          if (dispatchCompanySelectionFromSearch.hasParam) {
            return dispatchCompanySelectionFromSearch.ids.filter((id) => assignedCompanies.some((c) => c.id === id));
          }
          if (prev.length === 0) return assignedCompanies.map((c) => c.id);
          const valid = prev.filter((id) => assignedCompanies.some((c) => c.id === id));
          return valid.length > 0 ? valid : assignedCompanies.map((c) => c.id);
        });
      } else {
        setSelectedDispatchCompanyIds([]);
        setCalendarJobs([]);
      }
    } catch (err: unknown) {
      setCalendarError(err instanceof Error ? err.message : "Failed to load companies");
    }
  }

  async function loadDispatchCalendarJobs(month: Date) {
    setCalendarLoading(true);
    setCalendarError("");
    try {
      const params = new URLSearchParams({
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
          company_id: String(item.company_id || ""),
          company_name: String(item.company_name || ""),
          company_color: String(item.company_color || ""),
          job_order: Number(item.job_order || 0),
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

  async function loadDispatchCalendarDaySettingForCompany(companyId: string, dayDate: string, month: Date): Promise<DispatchCalendarDaySetting | null> {
    const params = new URLSearchParams({
      company_id: companyId,
      move_month: monthKey(month),
    });
    const res = await fetch(`${API_BASE}/api/dispatch-calendar-days?${params.toString()}`, { headers: authHeaders(token) });
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
    const data = (await res.json()) as { items?: Array<Record<string, unknown>> };
    const items = Array.isArray(data.items) ? data.items : [];
    const match = items.find((item) => String(item.day_date || "") === dayDate);
    if (!match) return null;
    return {
      day_date: String(match.day_date || dayDate),
      is_full: Boolean(match.is_full),
      note: String(match.note || ""),
    };
  }

  async function saveDispatchCalendarDaySettingForCompany(
    companyId: string,
    dayDate: string,
    isFull: boolean,
    note: string
  ): Promise<DispatchCalendarDaySetting | null> {
    setDaySettingsError("");
    const cleanNote = note.trim();
    const res = await fetch(`${API_BASE}/api/dispatch-calendar-days`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({
        company_id: companyId,
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
    const nextSetting = item
      ? {
          day_date: String(item.day_date || dayDate),
          is_full: Boolean(item.is_full),
          note: String(item.note || ""),
        }
      : null;

    if (companyId === singleSelectedDispatchCompanyId) {
      setDaySettings((prev) => {
        const next = { ...prev };
        if (!nextSetting) {
          delete next[dayDate];
          return next;
        }
        next[nextSetting.day_date] = nextSetting;
        return next;
      });
    }

    return nextSetting;
  }

  function selectDispatchJob(job: DispatchJobSearchResult) {
    const parsed = parseCalendarDate(job.move_date);
    if (!parsed) return;
    setSelectedJobId(job.id);
    setSelectedDispatchCompanyIds([job.company_id]);
    setDispatchMonth(new Date(parsed.getFullYear(), parsed.getMonth(), 1));
    setJobSearch(job.full_name);
    setJobSearchResults([]);
    setJobSearchOpen(false);
  }

  async function focusDispatchJobById(jobId: string) {
    try {
      const params = new URLSearchParams({ query: jobId, limit: "25" });
      const res = await fetch(`${API_BASE}/api/dispatch-job-search?${params.toString()}`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`Dispatch job search HTTP ${res.status}`);
      const data = (await res.json()) as { items?: Array<Record<string, unknown>> };
      const items = Array.isArray(data.items) ? data.items : [];
      const mapped = items.map((item) => ({
        id: String(item.id || ""),
        lead_id: String(item.lead_id || ""),
        job_order: Number(item.job_order || 0),
        full_name: String(item.full_name || "Unnamed"),
        move_date: String(item.move_date || ""),
        booked_move_date: String(item.booked_move_date || ""),
        pickup_zip: String(item.pickup_zip || ""),
        delivery_zip: String(item.delivery_zip || ""),
        status: String(item.status || ""),
        price: item.price == null ? null : Number(item.price),
        company_id: String(item.company_id || ""),
        company_name: String(item.company_name || ""),
        company_color: String(item.company_color || ""),
        leadgen_id: String(item.leadgen_id || ""),
      }));
      const match = mapped.find((item) => item.id === jobId);
      if (!match) return;
      const parsed = parseCalendarDate(match.move_date);
      if (parsed) {
        setDispatchMonth(new Date(parsed.getFullYear(), parsed.getMonth(), 1));
      }
      setSelectedDispatchCompanyIds([match.company_id]);
      setSelectedJobId(match.id);
      setJobSearch(match.full_name);
      setJobSearchResults([]);
      setJobSearchOpen(false);
      handledRouteJobIdRef.current = jobId;
    } catch {
      // Keep current calendar view if deep-link job lookup fails.
    }
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
        <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Dispatcher Calender</h1>
        <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
          Jobs grouped by booked move date for all checked companies in the selected month.
        </p>

        {calendarError ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{calendarError}</p> : null}
        {daySettingsError ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{daySettingsError}</p> : null}

        {!calendarLoading && dispatchCompanies.length > 0 ? (
          <div style={{ marginBottom: 12, maxWidth: 900, display: "grid", gap: 8 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <div style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>Companies</div>
              <div style={{ fontSize: 12, color: "#334155", fontWeight: 600 }}>
                Total jobs this month: {calendarJobs.length}
                {selectedDispatchCompanyIds.length > 0 && selectedDispatchCompanyIds.length !== dispatchCompanies.length
                  ? ` • Showing ${filteredCalendarJobs.length}`
                  : ""}
              </div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              <button
                type="button"
                onClick={() => {
                  const allIds = dispatchCompanies.map((c) => c.id);
                  const isAllSelected = selectedDispatchCompanyIds.length > 0 && selectedDispatchCompanyIds.length === dispatchCompanies.length;
                  setSelectedDispatchCompanyIds(isAllSelected ? [] : allIds);
                }}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  border: selectedDispatchCompanyIds.length > 0 && selectedDispatchCompanyIds.length === dispatchCompanies.length
                    ? "1px solid #0f766e"
                    : "1px solid #cbd5e1",
                  background: selectedDispatchCompanyIds.length > 0 && selectedDispatchCompanyIds.length === dispatchCompanies.length
                    ? "#ccfbf1"
                    : "#fff",
                  color: selectedDispatchCompanyIds.length > 0 && selectedDispatchCompanyIds.length === dispatchCompanies.length
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
                All ({calendarJobs.length})
              </button>
              {dispatchCompanies.map((company) => {
                const checked = selectedDispatchCompanyIds.includes(company.id);
                const monthlyCount = monthlyJobsByCompanyId.get(company.id) || 0;
                const tone = toneForCompanyColor(company.color, company.name);
                return (
                  <button
                    type="button"
                    key={company.id}
                    onClick={() => {
                      setSelectedDispatchCompanyIds((prev) =>
                        checked ? prev.filter((id) => id !== company.id) : [...prev, company.id]
                      );
                    }}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      border: checked ? `1px solid ${tone.border}` : "1px solid #cbd5e1",
                      background: checked ? tone.tint : "#fff",
                      color: checked ? tone.text : "#334155",
                      borderRadius: 999,
                      padding: "5px 10px",
                      fontSize: 12,
                      fontWeight: checked ? 700 : 600,
                      cursor: "pointer",
                    }}
                    aria-pressed={checked}
                    title={company.name}
                  >
                    <span style={{ width: 8, height: 8, borderRadius: 999, background: tone.border, display: "inline-block" }} />
                    {company.name} ({monthlyCount})
                  </button>
                );
              })}
            </div>
            {selectedDispatchCompanyIds.length !== 1 ? (
              <div style={{ fontSize: 11, color: "#64748b" }}>
                Day note/full controls are available when exactly one company is checked.
              </div>
            ) : null}
          </div>
        ) : null}

        {calendarLoading ? <p style={{ color: "#3e3e3c", fontSize: 13 }}>Loading calender...</p> : null}

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

        {!calendarLoading && selectedDispatchCompanyIds.length > 0 ? (
          <CompanyCalendar
            companyName={selectedDispatchCompanyIds.length === dispatchCompanies.length
              ? "All Companies"
              : selectedDispatchCompanyIds.length === 1
                ? (dispatchCompanies.find((c) => c.id === selectedDispatchCompanyIds[0])?.name || "Company")
                : `${selectedDispatchCompanyIds.length} Companies`}
            daySettingCompanies={dispatchCompanies.filter((c) => selectedDispatchCompanyIds.includes(c.id))}
            jobs={filteredCalendarJobs}
            daySettings={daySettings}
            viewDate={dispatchMonth}
            selectedJobId={selectedJobId}
            onPrevMonth={() => setDispatchMonth((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1))}
            onNextMonth={() => setDispatchMonth((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1))}
            onLoadDaySetting={loadDispatchCalendarDaySettingForCompany}
            onSaveDaySetting={saveDispatchCalendarDaySettingForCompany}
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
  daySettingCompanies,
  jobs,
  daySettings,
  viewDate,
  selectedJobId,
  onPrevMonth,
  onNextMonth,
  onLoadDaySetting,
  onSaveDaySetting,
}: {
  companyName: string;
  daySettingCompanies: Company[];
  jobs: LeadJob[];
  daySettings: Record<string, DispatchCalendarDaySetting>;
  viewDate: Date;
  selectedJobId: string;
  onPrevMonth: () => void;
  onNextMonth: () => void;
  onLoadDaySetting: (companyId: string, dayDate: string, month: Date) => Promise<DispatchCalendarDaySetting | null>;
  onSaveDaySetting: (companyId: string, dayDate: string, isFull: boolean, note: string) => Promise<DispatchCalendarDaySetting | null>;
}) {
  const location = useLocation();
  const [jobPanelDay, setJobPanelDay] = useState<number | null>(null);
  const [panelCompanyId, setPanelCompanyId] = useState("");
  const [panelNote, setPanelNote] = useState("");
  const [panelIsFull, setPanelIsFull] = useState(false);
  const [panelLoading, setPanelLoading] = useState(false);
  const [panelSaving, setPanelSaving] = useState(false);
  const [panelError, setPanelError] = useState("");
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const monthLabel = viewDate.toLocaleString(undefined, { month: "long", year: "numeric" });
  const dispatchBackState = useMemo(
    () => ({
      backTo: `${location.pathname}${location.search}`,
      backLabel: "← Back to Calendar",
      backOrigin: "dispatch-calendar",
    }),
    [location.pathname, location.search]
  );

  const companyStyles = useMemo(() => {
    const uniqueCompanies = new Map<string, { name: string; tone: CompanyTone }>();
    const sortedJobs = [...jobs].sort((left, right) => {
      const leftName = (left.company_name || "").toLowerCase();
      const rightName = (right.company_name || "").toLowerCase();
      if (leftName !== rightName) return leftName.localeCompare(rightName);
      return companyKeyForJob(left).localeCompare(companyKeyForJob(right));
    });

    for (const job of sortedJobs) {
      const key = companyKeyForJob(job);
      if (uniqueCompanies.has(key)) continue;
      const tone = toneForCompanyColor(job.company_color, job.company_name);
      uniqueCompanies.set(key, { name: job.company_name || "Company", tone });
    }

    return uniqueCompanies;
  }, [jobs]);

  function getCompanyTone(job: LeadJob): CompanyTone {
    const key = companyKeyForJob(job);
    return companyStyles.get(key)?.tone || toneForCompanyColor(job.company_color, job.company_name);
  }

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
  const panelDayJobs = jobPanelDay == null ? [] : (jobsByDay.get(jobPanelDay) || []);

  useEffect(() => {
    if (!selectedJobId) return;
    const selectedJob = jobs.find((job) => job.id === selectedJobId);
    if (!selectedJob) return;
    const parsed = parseCalendarDate(selectedJob.move_date);
    if (!parsed || parsed.getFullYear() !== year || parsed.getMonth() !== month) return;
    const day = parsed.getDate();
    const dayJobs = jobsByDay.get(day) || [];
    if (dayJobs.some((job) => job.id === selectedJobId)) {
      return;
    }
  }, [jobs, selectedJobId, year, month]);

  function dayDateKey(day: number): string {
    return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }

  function openDayPanel(day: number, preferredCompanyId = "") {
    const dayJobs = jobsByDay.get(day) || [];
    const preferred = preferredCompanyId && daySettingCompanies.some((company) => company.id === preferredCompanyId)
      ? preferredCompanyId
      : "";
    const dayMatchedCompanyId = daySettingCompanies.find((company) =>
      dayJobs.some((job) => String(job.company_id || "") === company.id)
    )?.id || "";
    const fallbackCompanyId = daySettingCompanies[0]?.id || "";
    setPanelCompanyId(preferred || dayMatchedCompanyId || fallbackCompanyId);
    setPanelError("");
    setJobPanelDay(day);
  }

  function closeDayPanel() {
    if (panelSaving) return;
    setJobPanelDay(null);
    setPanelError("");
  }

  async function saveDayPanelSetting() {
    if (jobPanelDay == null) return;
    if (!panelCompanyId) {
      setPanelError("Select a company first.");
      return;
    }
    setPanelSaving(true);
    setPanelError("");
    try {
      const saved = await onSaveDaySetting(panelCompanyId, dayDateKey(jobPanelDay), panelIsFull, panelNote);
      setPanelIsFull(Boolean(saved?.is_full));
      setPanelNote(saved?.note || "");
    } catch (err: unknown) {
      setPanelError(err instanceof Error ? err.message : "Failed to save day setting");
    } finally {
      setPanelSaving(false);
    }
  }

  useEffect(() => {
    if (jobPanelDay == null) return;
    if (!panelCompanyId) {
      setPanelIsFull(false);
      setPanelNote("");
      return;
    }
    let cancelled = false;
    setPanelLoading(true);
    setPanelError("");
    void (async () => {
      try {
        const setting = await onLoadDaySetting(panelCompanyId, dayDateKey(jobPanelDay), viewDate);
        if (cancelled) return;
        setPanelIsFull(Boolean(setting?.is_full));
        setPanelNote(setting?.note || "");
      } catch (err: unknown) {
        if (cancelled) return;
        setPanelError(err instanceof Error ? err.message : "Failed to load day setting");
        setPanelIsFull(false);
        setPanelNote("");
      } finally {
        if (!cancelled) {
          setPanelLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jobPanelDay, panelCompanyId, viewDate, onLoadDaySetting]);

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
            const visibleJobs = dayJobs.slice(0, 3);
            const overflowCount = Math.max(dayJobs.length - visibleJobs.length, 0);
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
                      onClick={() => openDayPanel(day)}
                      style={{
                        ...calendarActionIconBtn,
                        borderColor: dayNote ? "#0176d3" : "#cbd5e1",
                        background: dayNote ? "#eaf5fe" : "#fff",
                      }}
                      title="Open day panel"
                      aria-label="Open day panel"
                    >
                      <NoteIcon active={Boolean(dayNote)} />
                    </button>
                    <button
                      type="button"
                      onClick={() => openDayPanel(day)}
                      style={{
                        ...calendarActionIconBtn,
                        borderColor: isFullDay ? "#0176d3" : "#cbd5e1",
                        background: isFullDay ? "#0176d3" : "#fff",
                        color: isFullDay ? "#fff" : "#334155",
                      }}
                      title="Open day panel"
                      aria-label="Open day panel"
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
                  <button
                    type="button"
                    onClick={() => openDayPanel(day)}
                    style={{ marginBottom: 6, width: "100%", textAlign: "left", fontSize: 10, color: "#334155", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 4, padding: "4px 5px", cursor: "pointer" }}
                    title={dayNote}
                    aria-label="Open day panel note"
                  >
                    {dayNote.length > 60 ? `${dayNote.slice(0, 60)}...` : dayNote}
                  </button>
                ) : null}
                {dayJobs.length > 0 ? (
                  <div style={{ display: "grid", gap: 6 }}>
                    {visibleJobs.map((job, idx) => (
                      <Link
                        key={job.id}
                        to={`/leads/${job.lead_id || job.id}?job_id=${encodeURIComponent(job.id)}`}
                        state={dispatchBackState}
                        data-company-key={companyKeyForJob(job)}
                        style={{
                          display: "block",
                          fontSize: 11,
                          color: getCompanyTone(job).text,
                          textDecoration: "none",
                          background: job.id === selectedJobId ? "#f8fafc" : getCompanyTone(job).tint,
                          border: `1px solid ${job.id === selectedJobId ? "#2563eb" : getCompanyTone(job).border}`,
                          borderRadius: 4,
                          padding: "4px 5px",
                          overflow: "hidden",
                          boxShadow: job.id === selectedJobId ? "0 0 0 1px rgba(37, 99, 235, 0.2)" : undefined,
                        }}
                        title={`${job.full_name} • ${job.pickup_zip || "?"} -> ${job.delivery_zip || "?"} • ${job.status}`}
                      >
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 600 }}>{job.full_name}</div>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: getCompanyTone(job).text, fontWeight: 700 }}>{job.company_name || "Unknown company"}</div>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#475569" }}>{job.pickup_zip || "?"}{" -> "}{job.delivery_zip || "?"}</div>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: job.id === selectedJobId ? "#1d4ed8" : getCompanyTone(job).text }}>{job.status || "booked"}</div>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#475569", fontSize: 11 }}>{`Job ${job.job_order || idx + 1}`}</div>
                        {job.price != null ? <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#0f766e" }}>${job.price.toFixed(2)}</div> : null}
                      </Link>
                    ))}
                    {overflowCount > 0 ? (
                      <button
                        type="button"
                        onClick={() => openDayPanel(day)}
                        style={{
                          border: "1px solid #cbd5e1",
                          background: "#f8fafc",
                          borderRadius: 4,
                          color: "#0f172a",
                          fontSize: 11,
                          fontWeight: 700,
                          padding: "4px 6px",
                          cursor: "pointer",
                          textAlign: "left",
                        }}
                      >
                        More +{overflowCount}
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      {jobPanelDay != null ? (
        <div
          role="presentation"
          onClick={closeDayPanel}
          style={{ position: "fixed", inset: 0, background: "rgba(15, 23, 42, 0.35)", zIndex: 95 }}
        >
          <div
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
            style={{
              position: "fixed",
              top: 0,
              right: 0,
              width: "min(420px, 100%)",
              height: "100vh",
              background: "#fff",
              borderLeft: "1px solid #cbd5e1",
              boxShadow: "-16px 0 32px rgba(15, 23, 42, 0.18)",
              display: "flex",
              flexDirection: "column",
              zIndex: 96,
            }}
          >
            <div style={{ padding: 14, borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>Day Panel • {dayDateKey(jobPanelDay)}</div>
                <div style={{ fontSize: 12, color: "#64748b" }}>{panelDayJobs.length} job{panelDayJobs.length === 1 ? "" : "s"}</div>
              </div>
              <button type="button" onClick={closeDayPanel} style={calendarNavBtn} aria-label="Close day panel">
                ✕
              </button>
            </div>
            <div style={{ padding: 12, overflowY: "auto", display: "grid", gap: 12 }}>
              <div style={{ border: "1px solid #e2e8f0", borderRadius: 8, padding: 10, background: "#f8fafc", display: "grid", gap: 8 }}>
                <div style={{ fontSize: 12, color: "#334155", fontWeight: 700 }}>Day Settings</div>
                <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#334155", fontWeight: 600 }}>
                  Company
                  <select
                    value={panelCompanyId}
                    onChange={(e) => setPanelCompanyId(e.target.value)}
                    style={{ ...inputStyle, height: 34 }}
                    disabled={daySettingCompanies.length === 0 || panelSaving}
                  >
                    {daySettingCompanies.length === 0 ? <option value="">No selected companies</option> : null}
                    {daySettingCompanies.map((company) => (
                      <option key={company.id} value={company.id}>{company.name}</option>
                    ))}
                  </select>
                </label>
                <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#334155", fontWeight: 600 }}>
                  <input
                    type="checkbox"
                    checked={panelIsFull}
                    onChange={(e) => setPanelIsFull(e.target.checked)}
                    disabled={!panelCompanyId || panelLoading || panelSaving}
                  />
                  Mark day as full
                </label>
                <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#334155", fontWeight: 600 }}>
                  Note
                  <textarea
                    value={panelNote}
                    onChange={(e) => setPanelNote(e.target.value)}
                    placeholder="Add context for dispatchers (parking, access, constraints, etc.)"
                    rows={4}
                    disabled={!panelCompanyId || panelLoading || panelSaving}
                    style={{ width: "100%", boxSizing: "border-box", border: "1px solid #cbd5e1", borderRadius: 6, padding: "8px 10px", fontSize: 13, resize: "vertical", background: "#fff" }}
                  />
                </label>
                {panelLoading ? <div style={{ fontSize: 12, color: "#475569" }}>Loading day setting...</div> : null}
                {panelError ? <div style={{ fontSize: 12, color: "#ba0517" }}>{panelError}</div> : null}
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button
                    type="button"
                    onClick={() => void saveDayPanelSetting()}
                    disabled={!panelCompanyId || panelLoading || panelSaving}
                    style={{ border: "1px solid #0176d3", background: "#0176d3", color: "#fff", borderRadius: 4, padding: "7px 12px", fontSize: 12, fontWeight: 600 }}
                  >
                    {panelSaving ? "Saving..." : "Save Day Setting"}
                  </button>
                </div>
              </div>

              <div style={{ fontSize: 12, color: "#334155", fontWeight: 700 }}>Jobs</div>
              {panelDayJobs.map((job, idx) => (
                <Link
                  key={job.id}
                  to={`/leads/${job.lead_id || job.id}?job_id=${encodeURIComponent(job.id)}`}
                  state={dispatchBackState}
                  onClick={closeDayPanel}
                  style={{
                    display: "grid",
                    gap: 3,
                    textDecoration: "none",
                    color: getCompanyTone(job).text,
                    border: job.id === selectedJobId ? "1px solid #2563eb" : `1px solid ${getCompanyTone(job).border}`,
                    background: job.id === selectedJobId ? "#eff6ff" : getCompanyTone(job).tint,
                    borderRadius: 8,
                    padding: 10,
                    boxShadow: job.id === selectedJobId ? "0 0 0 1px rgba(37, 99, 235, 0.12)" : "none",
                  }}
                  title={`${job.full_name} • ${job.pickup_zip || "?"} -> ${job.delivery_zip || "?"} • ${job.status}`}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <strong style={{ fontSize: 13, color: "#0f172a" }}>{job.full_name}</strong>
                    <span style={{ fontSize: 11, color: getCompanyTone(job).text, fontWeight: 700 }}>{`Job ${job.job_order || idx + 1}`}</span>
                  </div>
                  <div style={{ fontSize: 12, color: getCompanyTone(job).text, fontWeight: 700 }}>{job.company_name || "Unknown company"}</div>
                  <div style={{ fontSize: 12, color: "#334155" }}>{job.pickup_zip || "?"} {" -> "} {job.delivery_zip || "?"}</div>
                  <div style={{ fontSize: 11, color: getCompanyTone(job).text, fontWeight: 600 }}>{job.status || "booked"}</div>
                  {job.price != null ? <div style={{ fontSize: 11, color: "#0f766e", fontWeight: 700 }}>${job.price.toFixed(2)}</div> : null}
                </Link>
              ))}
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
