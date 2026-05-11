import { useEffect, useState, useRef, useCallback } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Lead, formatLabel, formatValue } from "./leadUtils";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";

interface Tooltip {
  text: string;
  x: number;
  y: number;
}

// Fields hidden from the main table (shown only on detail page)
const HIDDEN_FROM_TABLE = new Set([
  "entry_id",
  "page_id",
  "form_id",
  "adgroup_id",
  "ad_id",
  "inbox_url",
]);

const TABLE_FIELDS = [
  "leadgen_id",
  "full_name",
  "pickup_zip",
  "delivery_zip",
  "when_is_the_move?",
  "move_size",
  "phone_number",
  "email",
  "are_you_moving_within_the_state_or_out_of_state?",
  "created_time",
];

const COL_WIDTHS: Record<string, number> = {
  leadgen_id: 120,
  full_name: 250,
  pickup_zip: 120,
  delivery_zip: 130,
  "when_is_the_move?": 180,
  move_size: 140,
  phone_number: 150,
  email: 220,
  "are_you_moving_within_the_state_or_out_of_state?": 120,
  created_time: 200,
};

const DEFAULT_MAX = 180;

function cellStyle(key: string): React.CSSProperties {
  return {
    maxWidth: COL_WIDTHS[key] ?? DEFAULT_MAX,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    padding: "8px 12px",
  };
}

export default function LeadsList() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { token } = useAuth();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sortBy, setSortBy] = useState("created_time");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const observerRef = useRef<IntersectionObserver | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const companyIdFilter = searchParams.get("company_id") || "";
  const companyNameFilter = searchParams.get("company_name") || "";

  const STATUS_OPTIONS = ["new", "contacted", "quoted", "booked", "scheduled", "completed", "lost", "cancelled"];
  const SORTABLE_COLS = new Set(["created_time", "full_name", "status", "move_size", "pickup_zip", "delivery_zip"]);

  const handleSort = (col: string) => {
    if (!SORTABLE_COLS.has(col)) return;
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("asc");
    }
  };

  const fetchLeads = useCallback(async (offset: number = 0, query: string = "") => {
    const isFirst = offset === 0;
    if (!isFirst) setLoadingMore(true);
    try {
      const params = new URLSearchParams({ limit: "50", offset: String(offset) });
      if (query) params.set("search", query);
      if (companyIdFilter) params.set("company_id", companyIdFilter);
      if (statusFilter) params.set("status", statusFilter);
      params.set("sort_by", sortBy);
      params.set("sort_dir", sortDir);
      const res = await fetch(`${API_BASE}/api/leads?${params}`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setLeads((prev) => (isFirst ? data.items : [...prev, ...data.items]));
      setHasMore(data.has_more);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [token, companyIdFilter, statusFilter, sortBy, sortDir]);

  useEffect(() => {
    fetchLeads(0, search);
  }, [fetchLeads, search, companyIdFilter, statusFilter, sortBy, sortDir]);

  const handleSearchChange = (value: string) => {
    setSearchInput(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setSearch(value), 300);
  };

  const sentinelRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (observerRef.current) observerRef.current.disconnect();
      if (!node || !hasMore) return;
      observerRef.current = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore) {
          fetchLeads(leads.length, search);
        }
      });
      observerRef.current.observe(node);
    },
    [hasMore, loadingMore, fetchLeads, leads.length, search]
  );

  const getColumns = (data: Lead[]): string[] => {
    if (!data.length) return [];
    const allKeys = Object.keys(data[0]).filter(
      (k) => !HIDDEN_FROM_TABLE.has(k)
    );
    const ordered: string[] = [];
    for (const f of TABLE_FIELDS) {
      if (allKeys.includes(f)) ordered.push(f);
    }
    const remaining = allKeys.filter((k) => !ordered.includes(k));
    ordered.push(...remaining);
    return ordered;
  };

  if (loading) return <p>Loading…</p>;
  if (error) return <p style={{ color: "red" }}>Error: {error}</p>;

  const columns = getColumns(leads);

  return (
    <div style={{ padding: "20px 24px", fontFamily: "inherit", display: "flex", flexDirection: "column", height: "calc(100vh - 52px)", boxSizing: "border-box", overflow: "hidden" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700 }}>Leads</h1>
      </div>
      {companyIdFilter ? (
        <div style={{ marginBottom: 12, fontSize: 13, color: "#334155", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span>
            Showing company: <strong>{companyNameFilter || companyIdFilter}</strong>
          </span>
          <button
            type="button"
            onClick={() => setSearchParams((prev) => {
              const next = new URLSearchParams(prev);
              next.delete("company_id");
              next.delete("company_name");
              return next;
            })}
            style={{ border: "1px solid #cbd5e1", borderRadius: 6, background: "#fff", padding: "4px 10px", cursor: "pointer" }}
          >
            Show All Companies
          </button>
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="text"
          placeholder="Search by name, ID, phone, or email…"
          value={searchInput}
          onChange={(e) => handleSearchChange(e.target.value)}
          style={{
            width: 320,
            padding: "8px 12px",
            border: "1px solid #dddbda",
            borderRadius: 4,
            fontSize: 14,
            outline: "none",
            background: "#fff",
          }}
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ padding: "8px 12px", border: "1px solid #dddbda", borderRadius: 4, fontSize: 14, background: "#fff", cursor: "pointer" }}
        >
          <option value="">All Statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>
      </div>
      {leads.length === 0 ? (
        <p>No leads found.</p>
      ) : (
        <div style={{ flex: 1, overflow: "auto", background: "#fff", border: "1px solid #dddbda", borderRadius: 4, boxShadow: "0 1px 2px rgba(0,0,0,.08)" }}>
        <table style={{ width: "max-content", minWidth: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {columns.map((col) => {
                const isSortable = SORTABLE_COLS.has(col);
                const isActive = sortBy === col;
                return (
                <th
                  key={col}
                  onClick={() => handleSort(col)}
                  style={{
                    ...cellStyle(col),
                    textAlign: "left",
                    borderBottom: "2px solid #dddbda",
                    position: "sticky",
                    top: 0,
                    background: "#f3f2f2",
                    zIndex: 1,
                    fontSize: 12,
                    fontWeight: 700,
                    color: isActive ? "#032d60" : "#3e3e3c",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    cursor: isSortable ? "pointer" : "default",
                    userSelect: "none",
                    whiteSpace: "nowrap",
                  }}
                >
                  {formatLabel(col)}{isActive ? (sortDir === "asc" ? " ▲" : " ▼") : isSortable ? " ⇅" : ""}
                </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {leads.map((lead, i) => (
              <tr
                key={lead.leadgen_id ?? i}
                onClick={() => navigate(`/leads/${lead.id}`)}
                style={{ cursor: "pointer" }}
                onMouseOver={(e) =>
                  (e.currentTarget.style.background = "#f0f9ff")
                }
                onMouseOut={(e) =>
                  (e.currentTarget.style.background = "transparent")
                }
              >
                {columns.map((col) => {
                  const text = formatValue(col, lead[col]);
                  const isCompanyCell = col === "company_name" && lead.company_id;
                  return (
                    <td
                      key={col}
                      style={{
                        ...cellStyle(col),
                        borderBottom: "1px solid #eee",
                      }}
                      onMouseEnter={(e) => {
                        const td = e.currentTarget;
                        if (td.scrollWidth > td.clientWidth) {
                          const rect = td.getBoundingClientRect();
                          setTooltip({ text, x: rect.left, y: rect.top });
                        }
                      }}
                      onMouseLeave={(e) => {
                        const related = e.relatedTarget as Node | null;
                        if (tooltipRef.current?.contains(related)) return;
                        setTooltip(null);
                      }}
                    >
                      {isCompanyCell ? (
                        <Link
                          to={`/?company_id=${encodeURIComponent(String(lead.company_id))}&company_name=${encodeURIComponent(String(lead.company_name || ""))}`}
                          onClick={(e) => e.stopPropagation()}
                          style={{ color: "#2563eb", textDecoration: "underline" }}
                        >
                          {text}
                        </Link>
                      ) : (
                        text
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <div ref={sentinelRef} style={{ height: 1 }} />
        {loadingMore && <p style={{ padding: "8px 12px", margin: 0 }}>Loading more…</p>}
        </div>
      )}

      {tooltip && (
        <div
          ref={tooltipRef}
          onMouseLeave={() => setTooltip(null)}
          style={{
            position: "fixed",
            left: tooltip.x,
            top: tooltip.y,
            maxWidth: 400,
            padding: "8px 12px",
            background: "#1a1a1a",
            color: "#fff",
            borderRadius: 6,
            fontSize: 13,
            lineHeight: 1.4,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            boxShadow: "0 4px 12px rgba(0,0,0,.25)",
            zIndex: 1000,
            userSelect: "text",
            cursor: "text",
          }}
        >
          {tooltip.text}
        </div>
      )}

    </div>
  );
}
