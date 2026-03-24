import { useEffect, useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
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
  const { token } = useAuth();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const observerRef = useRef<IntersectionObserver | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchLeads = useCallback(async (offset: number = 0, query: string = "") => {
    const isFirst = offset === 0;
    if (!isFirst) setLoadingMore(true);
    try {
      const params = new URLSearchParams({ limit: "50", offset: String(offset) });
      if (query) params.set("search", query);
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
  }, [token]);

  useEffect(() => {
    fetchLeads(0, search);
  }, [fetchLeads, search]);

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
    <div style={{ padding: 24, fontFamily: "sans-serif" }}>
      <h1>Leads</h1>
      <input
        type="text"
        placeholder="Search by name, ID, phone, or email…"
        value={searchInput}
        onChange={(e) => handleSearchChange(e.target.value)}
        style={{
          width: "100%",
          maxWidth: 400,
          padding: "10px 14px",
          marginBottom: 16,
          border: "1px solid #ccc",
          borderRadius: 6,
          fontSize: 14,
          outline: "none",
        }}
      />
      {leads.length === 0 ? (
        <p>No leads found.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  style={{
                    ...cellStyle(col),
                    textAlign: "left",
                    borderBottom: "2px solid #ccc",
                  }}
                >
                  {formatLabel(col)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {leads.map((lead, i) => (
              <tr
                key={lead.leadgen_id ?? i}
                onClick={() => navigate(`/leads/${lead.leadgen_id}`)}
                style={{ cursor: "pointer" }}
                onMouseOver={(e) =>
                  (e.currentTarget.style.background = "#f5f5f5")
                }
                onMouseOut={(e) =>
                  (e.currentTarget.style.background = "transparent")
                }
              >
                {columns.map((col) => {
                  const text = formatValue(col, lead[col]);
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
                      {text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
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

      <div ref={sentinelRef} style={{ height: 1 }} />
      {loadingMore && <p>Loading more…</p>}
    </div>
  );
}
