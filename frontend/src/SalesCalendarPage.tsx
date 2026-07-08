import { Link, useLocation } from "react-router-dom";
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
  estimatedTotal?: EstimatedTotal | null;
  payments?: LeadPayment[];
  status: string;
  assigned_to: string;
  assigned_to_name: string;
  assigned_to_role: string;
};

type EstimatedTotal = {
  subtotal: number;
  taxableAmount: number;
  tax: number;
  finalTotal: number;
};

type LeadPayment = {
  amount: number;
  takenByUser: string;
  repPaid?: boolean;
  repPaidAt?: string;
};

type AssigneeOption = {
  key: string;
  id: string;
  name: string;
  role: string;
};

type CompanyTone = {
  tint: string;
  border: string;
  text: string;
};

const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const UNASSIGNED_KEY = "__unassigned__";
const DEFAULT_COMPANY_TONE: CompanyTone = Object.freeze({ tint: "#e0f2fe", border: "#7dd3fc", text: "#0c4a6e" });

function toneForCompanyColor(companyColor?: string, companyName?: string): CompanyTone {
  const normalizedColor = normalizeHexColor(companyColor) || generateCompanyColorFromName(companyName);
  if (!normalizedColor) return DEFAULT_COMPANY_TONE;

  return {
    tint: mixHexColors(normalizedColor, "#ffffff", 0.82),
    border: mixHexColors(normalizedColor, "#ffffff", 0.48),
    text: mixHexColors(normalizedColor, "#111827", 0.35),
  };
}

function toneForRepName(repName?: string): CompanyTone {
  return toneForCompanyColor(undefined, repName || "unassigned");
}

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

function assigneeKey(job: SalesCalendarJob): string {
  return String(job.assigned_to || "").trim() || UNASSIGNED_KEY;
}

function roleLabel(role: string): string {
  if (role === "admin") return "Admin";
  if (role === "sales_rep") return "Rep";
  return "";
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value || 0);
}

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

function parseEstimatedTotal(raw: unknown): EstimatedTotal | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  return {
    subtotal: Number(value.subtotal || 0),
    taxableAmount: Number(value.taxableAmount || 0),
    tax: Number(value.tax || 0),
    finalTotal: Number(value.finalTotal || 0),
  };
}

function parsePayments(raw: unknown): LeadPayment[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const value = (item && typeof item === "object") ? item as Record<string, unknown> : {};
    return {
      amount: Number(value.amount || 0),
      takenByUser: String(value.takenByUser || ""),
      repPaid: Boolean(value.repPaid || false),
      repPaidAt: String(value.repPaidAt || ""),
    };
  });
}

export default function SalesCalendarPage() {
  const location = useLocation();
  const { token, user } = useAuth();

  const [viewMonth, setViewMonth] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [jobs, setJobs] = useState<SalesCalendarJob[]>([]);
  const [selectedAssigneeKeys, setSelectedAssigneeKeys] = useState<string[]>([]);
  const [totalsExpanded, setTotalsExpanded] = useState(false);

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
          estimatedTotal: parseEstimatedTotal(item.estimatedTotal),
          payments: parsePayments(item.payments),
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

  const totalLeadCount = useMemo(() => {
    return new Set(jobs.map((job) => String(job.lead_id || "")).filter(Boolean)).size;
  }, [jobs]);

  const filteredLeadCount = useMemo(() => {
    return new Set(filteredJobs.map((job) => String(job.lead_id || "")).filter(Boolean)).size;
  }, [filteredJobs]);

  const salesMoneySummary = useMemo(() => {
    const uniqueLeads = new Map<string, SalesCalendarJob>();
    const companyBuckets = new Map<string, {
      companyId: string;
      companyName: string;
      companyColor?: string;
      leads: Map<string, SalesCalendarJob>;
    }>();

    for (const job of filteredJobs) {
      if (!job.lead_id) continue;
      if (!uniqueLeads.has(job.lead_id)) {
        uniqueLeads.set(job.lead_id, job);
      }

      const companyId = String(job.company_id || "");
      if (!companyId) continue;
      let bucket = companyBuckets.get(companyId);
      if (!bucket) {
        bucket = {
          companyId,
          companyName: String(job.company_name || "Unknown company"),
          companyColor: job.company_color,
          leads: new Map<string, SalesCalendarJob>(),
        };
        companyBuckets.set(companyId, bucket);
      }
      if (!bucket.leads.has(job.lead_id)) {
        bucket.leads.set(job.lead_id, job);
      }
    }

    function summarizeJobs(items: Iterable<SalesCalendarJob>) {
      let estimatedTotal = 0;
      let paymentsTotal = 0;
      let repCommissionPaid = 0;
      let leadCount = 0;
      for (const job of items) {
        leadCount += 1;
        estimatedTotal += Number(job.estimatedTotal?.finalTotal || 0);
        for (const payment of job.payments || []) {
          const paymentAmount = Number(payment.amount || 0);
          paymentsTotal += paymentAmount;
          if (payment.repPaid) {
            repCommissionPaid += paymentAmount * 0.3;
          }
        }
      }
      const remainingTotal = estimatedTotal - paymentsTotal;
      const paymentsPercent = estimatedTotal > 0 ? (paymentsTotal / estimatedTotal) * 100 : 0;
      const remainingPercent = estimatedTotal > 0 ? (remainingTotal / estimatedTotal) * 100 : 0;
      const repCommissionTotal = paymentsTotal * 0.3;
      const repCommissionRemaining = Math.max(0, repCommissionTotal - repCommissionPaid);
      return {
        estimatedTotal,
        paymentsTotal,
        remainingTotal,
        paymentsPercent,
        remainingPercent,
        repCommissionTotal,
        repCommissionPaid,
        repCommissionRemaining,
        leadCount,
      };
    }

    const companies = Array.from(companyBuckets.values())
      .map((bucket) => ({
        companyId: bucket.companyId,
        companyName: bucket.companyName,
        companyColor: bucket.companyColor,
        ...summarizeJobs(bucket.leads.values()),
      }))
      .sort((left, right) => left.companyName.localeCompare(right.companyName));

    return {
      ...summarizeJobs(uniqueLeads.values()),
      companies,
    };
  }, [filteredJobs]);

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
              Total leads this month: {totalLeadCount} ({jobs.length} jobs)
              {selectedAssigneeKeys.length > 0 && selectedAssigneeKeys.length !== assigneeOptions.length
                ? ` • Showing ${filteredLeadCount} leads (${filteredJobs.length} jobs)`
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
              const repTone = toneForRepName(assignee.name);
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
                    border: checked ? `1px solid ${repTone.border}` : "1px solid #cbd5e1",
                    background: checked ? repTone.tint : "#fff",
                    color: checked ? repTone.text : "#334155",
                    borderRadius: 999,
                    padding: "5px 10px",
                    fontSize: 12,
                    fontWeight: checked ? 700 : 600,
                    cursor: "pointer",
                  }}
                >
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: checked ? repTone.border : "#94a3b8", display: "inline-block" }} />
                  <span style={{ color: repTone.text, fontWeight: 700 }}>{assignee.name}</span>{role ? ` (${role})` : ""} ({count})
                </button>
              );
            })}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginTop: 4 }}>
            <div style={{ border: "1px solid #cbd5e1", borderRadius: 14, padding: "12px 14px", background: "linear-gradient(135deg, #eff6ff 0%, #ffffff 100%)" }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#1d4ed8", textTransform: "uppercase", letterSpacing: "0.05em" }}>Estimated Total</div>
              <div style={{ marginTop: 6, fontSize: 24, fontWeight: 800, color: "#0f172a" }}>{formatMoney(salesMoneySummary.estimatedTotal)}</div>
              <div style={{ marginTop: 4, fontSize: 12, color: "#475569" }}>{salesMoneySummary.leadCount} lead{salesMoneySummary.leadCount === 1 ? "" : "s"}</div>
            </div>
            <div style={{ border: "1px solid #bbf7d0", borderRadius: 14, padding: "12px 14px", background: "linear-gradient(135deg, #f0fdf4 0%, #ffffff 100%)" }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#15803d", textTransform: "uppercase", letterSpacing: "0.05em" }}>Payments</div>
              <div style={{ marginTop: 6, fontSize: 24, fontWeight: 800, color: "#0f172a" }}>{formatMoney(salesMoneySummary.paymentsTotal)}</div>
              <div style={{ marginTop: 4, fontSize: 12, color: "#166534" }}>{formatPercent(salesMoneySummary.paymentsPercent)}</div>
            </div>
            <div style={{ border: "1px solid #fde68a", borderRadius: 14, padding: "12px 14px", background: "linear-gradient(135deg, #fffbeb 0%, #ffffff 100%)" }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#b45309", textTransform: "uppercase", letterSpacing: "0.05em" }}>Remaining</div>
              <div style={{ marginTop: 6, fontSize: 24, fontWeight: 800, color: "#0f172a" }}>{formatMoney(salesMoneySummary.remainingTotal)}</div>
              <div style={{ marginTop: 4, fontSize: 12, color: "#92400e" }}>{formatPercent(salesMoneySummary.remainingPercent)}</div>
            </div>
            <div style={{ border: "1px solid #c7d2fe", borderRadius: 14, padding: "12px 14px", background: "linear-gradient(135deg, #eef2ff 0%, #ffffff 100%)" }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#4338ca", textTransform: "uppercase", letterSpacing: "0.05em" }}>Rep Paid (30%)</div>
              <div style={{ marginTop: 6, fontSize: 24, fontWeight: 800, color: "#0f172a" }}>{formatMoney(salesMoneySummary.repCommissionPaid)}</div>
              <div style={{ marginTop: 4, fontSize: 12, color: "#4f46e5" }}>of {formatMoney(salesMoneySummary.repCommissionTotal)}</div>
            </div>
            <div style={{ border: "1px solid #fecaca", borderRadius: 14, padding: "12px 14px", background: "linear-gradient(135deg, #fff1f2 0%, #ffffff 100%)" }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#be123c", textTransform: "uppercase", letterSpacing: "0.05em" }}>Rep Remaining (30%)</div>
              <div style={{ marginTop: 6, fontSize: 24, fontWeight: 800, color: "#0f172a" }}>{formatMoney(salesMoneySummary.repCommissionRemaining)}</div>
              <div style={{ marginTop: 4, fontSize: 12, color: "#be123c" }}>unpaid commission</div>
            </div>
          </div>

          <div style={{ border: "1px solid #dbe4ef", borderRadius: 14, background: "#fff", overflow: "hidden" }}>
            <button
              type="button"
              onClick={() => setTotalsExpanded((prev) => !prev)}
              style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, border: "none", background: "#f8fafc", padding: "12px 14px", cursor: "pointer", textAlign: "left" }}
            >
              <div>
                <div style={{ fontSize: 12, fontWeight: 800, color: "#0f172a" }}>Company Breakdown</div>
                <div style={{ fontSize: 11, color: "#64748b" }}>Totals for currently selected assignees</div>
              </div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#334155" }}>{totalsExpanded ? "Hide" : "Show"}</div>
            </button>
            {totalsExpanded ? (
              <div style={{ padding: 12, display: "grid", gap: 8 }}>
                {salesMoneySummary.companies.length === 0 ? (
                  <div style={{ fontSize: 12, color: "#64748b" }}>No companies selected.</div>
                ) : salesMoneySummary.companies.map((company) => {
                  const tone = toneForCompanyColor(company.companyColor, company.companyName);
                  return (
                    <div key={company.companyId} style={{ border: `1px solid ${tone.border}`, background: tone.tint, borderRadius: 12, padding: 12, display: "grid", gap: 6 }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                        <div style={{ fontSize: 13, fontWeight: 800, color: tone.text }}>{company.companyName}</div>
                        <div style={{ fontSize: 11, color: tone.text }}>{company.leadCount} lead{company.leadCount === 1 ? "" : "s"}</div>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8 }}>
                        <div style={{ fontSize: 12, color: "#334155" }}>Estimated: <strong>{formatMoney(company.estimatedTotal)}</strong></div>
                        <div style={{ fontSize: 12, color: "#166534" }}>Payments: <strong>{formatMoney(company.paymentsTotal)}</strong> ({formatPercent(company.paymentsPercent)})</div>
                        <div style={{ fontSize: 12, color: "#92400e" }}>Remaining: <strong>{formatMoney(company.remainingTotal)}</strong> ({formatPercent(company.remainingPercent)})</div>
                        <div style={{ fontSize: 12, color: "#4338ca" }}>Rep Paid (30%): <strong>{formatMoney(company.repCommissionPaid)}</strong> of {formatMoney(company.repCommissionTotal)}</div>
                        <div style={{ fontSize: 12, color: "#be123c" }}>Rep Remaining (30%): <strong>{formatMoney(company.repCommissionRemaining)}</strong></div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
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
                      {visibleJobs.map((job, idx) => {
                        const companyTone = toneForCompanyColor(job.company_color, job.company_name);
                        const repTone = toneForRepName(job.assigned_to_name || "Unassigned");
                        return (
                          <Link
                            key={job.id}
                            to={`/leads/${job.lead_id || job.id}?job_id=${encodeURIComponent(job.id)}`}
                            state={backState}
                            style={{
                              display: "block",
                              fontSize: 11,
                              color: companyTone.text,
                              textDecoration: "none",
                              background: companyTone.tint,
                              border: `1px solid ${companyTone.border}`,
                              borderRadius: 4,
                              padding: "4px 5px",
                              overflow: "hidden",
                            }}
                            title={`${job.full_name} • ${job.pickup_zip || "?"} -> ${job.delivery_zip || "?"} • ${job.status}`}
                          >
                            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 600 }}>{job.full_name}</div>
                            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: repTone.text, fontWeight: 700 }}>{job.assigned_to_name || "Unassigned"}</div>
                            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#475569" }}>{job.pickup_zip || "?"} {" -> "} {job.delivery_zip || "?"}</div>
                            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#475569", fontSize: 11 }}>{`Job ${job.job_order || idx + 1}`}</div>
                          </Link>
                        );
                      })}
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
