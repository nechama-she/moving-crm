import { Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth, authHeaders } from "./AuthContext";
import { API_BASE } from "./apiConfig";
import "./AccessHistoryPage.css";

type AccessItem = {
  id: string;
  created_at: string;
  user_id: string | null;
  user_name: string;
  user_email: string | null;
  user_role: string;
  ip_address: string;
  method: string;
  path: string;
  query_params: string;
  status_code: number;
  duration_ms: number;
  user_agent: string;
  referer: string;
};

type GroupedUserRow = {
  user_id: string | null;
  user_name: string;
  user_email: string | null;
  user_role: string;
  total_requests: number;
  distinct_ips: number;
  total_errors: number;
  last_active: string | null;
  avg_duration_ms: number;
};

type GroupedIpRow = {
  ip_address: string;
  total_requests: number;
  distinct_users: number;
  total_errors: number;
  last_active: string | null;
  sample_user_agent: string;
};

type GroupedPathRow = {
  method: string;
  path: string;
  total_requests: number;
  total_errors: number;
  avg_duration_ms: number;
  last_active: string | null;
};

type GroupedStatusRow = {
  status_code: number;
  total_requests: number;
  distinct_users: number;
  distinct_ips: number;
  avg_duration_ms: number;
  last_active: string | null;
};

interface DrilldownPanelProps {
  initialFilter: Record<string, string>;
  title: string;
  onClose: () => void;
  token: string | null;
}

function DrilldownPanel({ initialFilter, title, onClose, token }: DrilldownPanelProps) {
  const [filters, setFilters] = useState<Record<string, string>>(initialFilter);

  // Pick sensible initial subGroup
  const getDefaultSubGroup = (f: Record<string, string>) => {
    if (!f.status_filter) return "status";
    if (!f.path) return "path";
    if (!f.user_id) return "user";
    if (!f.ip_address) return "ip";
    return "requests";
  };

  const [subGroup, setSubGroup] = useState<"status" | "path" | "user" | "ip" | "requests">(() => getDefaultSubGroup(initialFilter));
  const [subLoading, setSubLoading] = useState(false);
  const [subError, setSubError] = useState("");

  const [subStatuses, setSubStatuses] = useState<GroupedStatusRow[]>([]);
  const [subPaths, setSubPaths] = useState<GroupedPathRow[]>([]);
  const [subUsers, setSubUsers] = useState<GroupedUserRow[]>([]);
  const [subIps, setSubIps] = useState<GroupedIpRow[]>([]);
  const [subRequests, setSubRequests] = useState<AccessItem[]>([]);

  const fetchSubData = useCallback(async () => {
    setSubLoading(true);
    setSubError("");
    try {
      const q = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => {
        if (v && v.trim()) q.set(k, v.trim());
      });

      if (subGroup === "requests") {
        q.set("limit", "50");
        const res = await fetch(`${API_BASE}/api/system/access-logs?${q.toString()}`, {
          headers: authHeaders(token),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setSubRequests(data.items || []);
      } else {
        q.set("group_by", subGroup);
        const res = await fetch(`${API_BASE}/api/system/access-logs/grouped?${q.toString()}`, {
          headers: authHeaders(token),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        if (subGroup === "status") setSubStatuses(data.results || []);
        else if (subGroup === "path") setSubPaths(data.results || []);
        else if (subGroup === "user") setSubUsers(data.results || []);
        else if (subGroup === "ip") setSubIps(data.results || []);
      }
    } catch (err) {
      setSubError(err instanceof Error ? err.message : "Failed to load grouped details");
    } finally {
      setSubLoading(false);
    }
  }, [filters, subGroup, token]);

  useEffect(() => {
    void fetchSubData();
  }, [fetchSubData]);

  const addFilter = (patch: Record<string, string>, nextSubGroup?: "status" | "path" | "user" | "ip" | "requests") => {
    const updated = { ...filters, ...patch };
    setFilters(updated);
    if (nextSubGroup) {
      setSubGroup(nextSubGroup);
    } else {
      setSubGroup(getDefaultSubGroup(updated));
    }
  };

  const removeFilterKey = (key: string) => {
    const next = { ...filters };
    delete next[key];
    if (key === "path") delete next.method;
    // Don't allow clearing the root filter key if it was the initial basis, but allow resetting sub-filters
    setFilters(next);
  };

  const resetToInitial = () => {
    setFilters(initialFilter);
    setSubGroup(getDefaultSubGroup(initialFilter));
  };

  // Available sub-tabs based on what is NOT currently filtered
  const showStatusTab = !filters.status_filter;
  const showPathTab = !filters.path;
  const showUserTab = !filters.user_id;
  const showIpTab = !filters.ip_address;

  return (
    <div className="nested-requests-panel">
      <div className="nested-header">
        <div className="drilldown-header-left">
          <strong>{title}</strong>
          <div className="drilldown-breadcrumbs">
            {Object.entries(filters).map(([k, v]) => {
              if (!v) return null;
              let label = `${k}: ${v}`;
              if (k === "ip_address") label = `IP: ${v}`;
              else if (k === "status_filter") label = `Status: ${v}`;
              else if (k === "path") label = `${filters.method ? filters.method + " " : ""}${v}`;
              else if (k === "user_id") label = `User: ${v}`;
              else if (k === "method") return null; // shown with path

              const isInitial = Object.prototype.hasOwnProperty.call(initialFilter, k);

              return (
                <span key={k} className="drilldown-crumb-badge">
                  {label}
                  {!isInitial && (
                    <button
                      type="button"
                      aria-label={`Remove filter ${k}`}
                      onClick={() => removeFilterKey(k)}
                    >
                      ✕
                    </button>
                  )}
                </span>
              );
            })}
            {Object.keys(filters).length > Object.keys(initialFilter).length && (
              <button
                type="button"
                className="drilldown-reset-link"
                onClick={resetToInitial}
              >
                Reset drill-down
              </button>
            )}
          </div>
        </div>
        <button
          type="button"
          className="nested-close-btn"
          onClick={onClose}
        >
          ✕ Close
        </button>
      </div>

      <div className="drilldown-subtabs-bar">
        {showStatusTab && (
          <button
            type="button"
            className={`drilldown-subtab-btn ${subGroup === "status" ? "active" : ""}`}
            onClick={() => setSubGroup("status")}
          >
            By Status
          </button>
        )}
        {showPathTab && (
          <button
            type="button"
            className={`drilldown-subtab-btn ${subGroup === "path" ? "active" : ""}`}
            onClick={() => setSubGroup("path")}
          >
            By Endpoint
          </button>
        )}
        {showUserTab && (
          <button
            type="button"
            className={`drilldown-subtab-btn ${subGroup === "user" ? "active" : ""}`}
            onClick={() => setSubGroup("user")}
          >
            By User
          </button>
        )}
        {showIpTab && (
          <button
            type="button"
            className={`drilldown-subtab-btn ${subGroup === "ip" ? "active" : ""}`}
            onClick={() => setSubGroup("ip")}
          >
            By IP Address
          </button>
        )}
        <button
          type="button"
          className={`drilldown-subtab-btn ${subGroup === "requests" ? "active" : ""}`}
          onClick={() => setSubGroup("requests")}
        >
          Individual Requests ({subRequests.length})
        </button>
      </div>

      {subLoading ? (
        <div className="nested-loading">Loading grouped drill-down data...</div>
      ) : subError ? (
        <div className="nested-error">{subError}</div>
      ) : subGroup === "status" ? (
        subStatuses.length === 0 ? (
          <div className="nested-empty">No status records found.</div>
        ) : (
          <table className="nested-table">
            <thead>
              <tr>
                <th>Status Code</th>
                <th>Total Requests</th>
                <th>Distinct Users</th>
                <th>Distinct IPs</th>
                <th>Avg Latency</th>
                <th>Last Active</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {subStatuses.map((st) => (
                <tr key={st.status_code}>
                  <td>
                    <span className={`status-badge status-${String(st.status_code)[0]}xx`}>
                      {st.status_code}
                    </span>
                  </td>
                  <td><strong>{st.total_requests.toLocaleString()}</strong></td>
                  <td>{st.distinct_users} user{st.distinct_users === 1 ? "" : "s"}</td>
                  <td>{st.distinct_ips} IP{st.distinct_ips === 1 ? "" : "s"}</td>
                  <td>{st.avg_duration_ms} ms</td>
                  <td className="time-cell">
                    {st.last_active ? new Date(st.last_active).toLocaleTimeString("en-US") : "—"}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="drilldown-subaction-btn"
                      onClick={() => addFilter({ status_filter: String(st.status_code) })}
                    >
                      Filter this status ▸
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : subGroup === "path" ? (
        subPaths.length === 0 ? (
          <div className="nested-empty">No endpoint records found.</div>
        ) : (
          <table className="nested-table endpoint-drilldown-table">
            <thead>
              <tr>
                <th>Method</th>
                <th>Endpoint Path</th>
                <th>Total Hits</th>
                <th>Failed Hits</th>
                <th>Avg Latency</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {subPaths.map((p, idx) => (
                <tr key={`${p.method}-${p.path}-${idx}`}>
                  <td><span className={`method-badge ${p.method.toLowerCase()}`}>{p.method}</span></td>
                  <td className="path-cell"><code>{p.path}</code></td>
                  <td><strong>{p.total_requests.toLocaleString()}</strong></td>
                  <td>
                    {p.total_errors > 0 ? (
                      <span className="pill-badge error">{p.total_errors} errors</span>
                    ) : (
                      <span className="pill-badge success">0</span>
                    )}
                  </td>
                  <td>{p.avg_duration_ms} ms</td>
                  <td>
                    <button
                      type="button"
                      className="drilldown-subaction-btn"
                      onClick={() => addFilter({ method: p.method, path: p.path }, "requests")}
                    >
                      Filter this endpoint ▸
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : subGroup === "user" ? (
        subUsers.length === 0 ? (
          <div className="nested-empty">No user records found.</div>
        ) : (
          <table className="nested-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Total Requests</th>
                <th>Distinct IPs</th>
                <th>Errors</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {subUsers.map((u, idx) => (
                <tr key={u.user_id || `sub-user-${idx}`}>
                  <td>
                    <strong>{u.user_name}</strong>
                    {u.user_email && <small className="user-email-text">{u.user_email}</small>}
                  </td>
                  <td><span className="user-role-badge">{u.user_role}</span></td>
                  <td><strong>{u.total_requests.toLocaleString()}</strong></td>
                  <td>{u.distinct_ips} IP{u.distinct_ips === 1 ? "" : "s"}</td>
                  <td>
                    {u.total_errors > 0 ? (
                      <span className="pill-badge error">{u.total_errors}</span>
                    ) : (
                      <span className="pill-badge success">0</span>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="drilldown-subaction-btn"
                      onClick={() => addFilter({ user_id: u.user_id || "anonymous" })}
                    >
                      Filter this user ▸
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : subGroup === "ip" ? (
        subIps.length === 0 ? (
          <div className="nested-empty">No IP records found.</div>
        ) : (
          <table className="nested-table">
            <thead>
              <tr>
                <th>IP Address</th>
                <th>Total Requests</th>
                <th>Distinct Users</th>
                <th>Errors</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {subIps.map((ipRow) => (
                <tr key={ipRow.ip_address}>
                  <td className="ip-cell"><code>{ipRow.ip_address}</code></td>
                  <td><strong>{ipRow.total_requests.toLocaleString()}</strong></td>
                  <td>{ipRow.distinct_users} user{ipRow.distinct_users === 1 ? "" : "s"}</td>
                  <td>
                    {ipRow.total_errors > 0 ? (
                      <span className="pill-badge error">{ipRow.total_errors}</span>
                    ) : (
                      <span className="pill-badge success">0</span>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="drilldown-subaction-btn"
                      onClick={() => addFilter({ ip_address: ipRow.ip_address })}
                    >
                      Filter this IP ▸
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : (
        subRequests.length === 0 ? (
          <div className="nested-empty">No matching requests found.</div>
        ) : (
          <table className="nested-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>User / Role</th>
                <th>Method</th>
                <th>Path & Query</th>
                <th>Status</th>
                <th>IP Address</th>
                <th>Latency</th>
                <th>Device</th>
              </tr>
            </thead>
            <tbody>
              {subRequests.map((item) => (
                <tr key={item.id}>
                  <td className="time-cell">
                    {item.created_at ? new Date(item.created_at).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}
                  </td>
                  <td>
                    <strong>{item.user_name}</strong>
                    <small className="user-role-badge">{item.user_role}</small>
                  </td>
                  <td><span className={`method-badge ${item.method.toLowerCase()}`}>{item.method}</span></td>
                  <td className="path-cell">
                    <span className="path-text" title={item.path}>{item.path}</span>
                    {item.query_params && <small className="query-text">?{item.query_params}</small>}
                  </td>
                  <td><span className={`status-badge status-${String(item.status_code)[0]}xx`}>{item.status_code}</span></td>
                  <td><code>{item.ip_address}</code></td>
                  <td>{item.duration_ms} ms</td>
                  <td className="agent-cell" title={item.user_agent}>
                    <small>{item.user_agent.slice(0, 45)}…</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}
    </div>
  );
}

export default function AccessHistoryPage() {
  const { token, user } = useAuth();
  const isAdmin = user?.role === "admin";

  // Tab: 'stream' | 'by-user' | 'by-ip' | 'by-path' | 'by-status'
  const [tab, setTab] = useState<"stream" | "by-user" | "by-ip" | "by-path" | "by-status">("stream");

  // Stream state
  const [items, setItems] = useState<AccessItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(50);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filters for stream
  const [search, setSearch] = useState("");
  const [ipFilter, setIpFilter] = useState("");
  const [methodFilter, setMethodFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  // Grouped state
  const [groupedUsers, setGroupedUsers] = useState<GroupedUserRow[]>([]);
  const [groupedIps, setGroupedIps] = useState<GroupedIpRow[]>([]);
  const [groupedPaths, setGroupedPaths] = useState<GroupedPathRow[]>([]);
  const [groupedStatuses, setGroupedStatuses] = useState<GroupedStatusRow[]>([]);
  const [groupedLoading, setGroupedLoading] = useState(false);
  const [groupSearch, setGroupSearch] = useState("");

  // Expanded row details state: tracks which row key is open
  const [expandedRowKey, setExpandedRowKey] = useState<string | null>(null);

  const toggleExpand = (rowKey: string) => {
    setExpandedRowKey((prev) => (prev === rowKey ? null : rowKey));
  };

  const loadStream = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        limit: String(limit),
      });
      if (search.trim()) params.set("search", search.trim());
      if (ipFilter.trim()) params.set("ip_address", ipFilter.trim());
      if (methodFilter.trim()) params.set("method", methodFilter.trim());
      if (statusFilter.trim()) params.set("status_filter", statusFilter.trim());

      const res = await fetch(`${API_BASE}/api/system/access-logs?${params.toString()}`, {
        headers: authHeaders(token),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to load logs (${res.status})`);
      }
      const data = await res.json();
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load access logs");
    } finally {
      setLoading(false);
    }
  }, [token, page, limit, search, ipFilter, methodFilter, statusFilter]);

  const loadGrouped = useCallback(async () => {
    setGroupedLoading(true);
    setError("");
    try {
      const type = tab === "by-user" ? "user" : tab === "by-ip" ? "ip" : tab === "by-path" ? "path" : "status";
      const params = new URLSearchParams({ group_by: type });
      if (groupSearch.trim()) params.set("search", groupSearch.trim());

      const res = await fetch(`${API_BASE}/api/system/access-logs/grouped?${params.toString()}`, {
        headers: authHeaders(token),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to load grouped stats (${res.status})`);
      }
      const data = await res.json();
      if (type === "user") setGroupedUsers(data.results || []);
      else if (type === "ip") setGroupedIps(data.results || []);
      else if (type === "path") setGroupedPaths(data.results || []);
      else if (type === "status") setGroupedStatuses(data.results || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load grouped data");
    } finally {
      setGroupedLoading(false);
    }
  }, [token, tab, groupSearch]);

  useEffect(() => {
    if (tab === "stream") {
      void loadStream();
    } else {
      void loadGrouped();
    }
  }, [tab, loadStream, loadGrouped]);

  const totalPages = Math.ceil(total / limit) || 1;

  if (!isAdmin) {
    return (
      <div style={{ padding: 32 }}>
        <h2>Access Denied</h2>
        <p>Only administrators can review access audit history.</p>
      </div>
    );
  }

  return (
    <div className="access-history-page">
      <div className="access-history-header">
        <div>
          <span className="access-eyebrow">Security & Monitoring</span>
          <h1>Access History & Audit Logs</h1>
          <p>Full trail of all system interactions across users, API clients, IP addresses, and browsers.</p>
        </div>
        <div className="access-history-actions">
          <button
            type="button"
            className="access-btn access-btn-secondary"
            onClick={() => (tab === "stream" ? void loadStream() : void loadGrouped())}
            disabled={loading || groupedLoading}
          >
            ↻ Refresh
          </button>
          <Link to="/settings" className="access-btn access-btn-ghost">
            ← Settings
          </Link>
        </div>
      </div>

      <div className="access-tabs">
        <button
          type="button"
          className={`access-tab ${tab === "stream" ? "active" : ""}`}
          onClick={() => { setTab("stream"); setPage(1); setExpandedRowKey(null); }}
        >
          All Activity Log ({total.toLocaleString()})
        </button>
        <button
          type="button"
          className={`access-tab ${tab === "by-user" ? "active" : ""}`}
          onClick={() => { setTab("by-user"); setExpandedRowKey(null); }}
        >
          Grouped by User
        </button>
        <button
          type="button"
          className={`access-tab ${tab === "by-ip" ? "active" : ""}`}
          onClick={() => { setTab("by-ip"); setExpandedRowKey(null); }}
        >
          Grouped by IP Address
        </button>
        <button
          type="button"
          className={`access-tab ${tab === "by-path" ? "active" : ""}`}
          onClick={() => { setTab("by-path"); setExpandedRowKey(null); }}
        >
          Grouped by Endpoint
        </button>
        <button
          type="button"
          className={`access-tab ${tab === "by-status" ? "active" : ""}`}
          onClick={() => { setTab("by-status"); setExpandedRowKey(null); }}
        >
          Grouped by Status
        </button>
      </div>

      {error && <div className="access-alert error" role="alert">{error}</div>}

      {tab === "stream" && (
        <>
          <div className="access-filters-bar">
            <input
              type="text"
              placeholder="Search user, path, or IP..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              className="access-input search-input"
            />
            <input
              type="text"
              placeholder="Filter by IP..."
              value={ipFilter}
              onChange={(e) => { setIpFilter(e.target.value); setPage(1); }}
              className="access-input ip-input"
            />
            <select
              value={methodFilter}
              onChange={(e) => { setMethodFilter(e.target.value); setPage(1); }}
              className="access-select"
            >
              <option value="">All Methods</option>
              <option value="GET">GET</option>
              <option value="POST">POST</option>
              <option value="PATCH">PATCH</option>
              <option value="PUT">PUT</option>
              <option value="DELETE">DELETE</option>
            </select>
            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
              className="access-select"
            >
              <option value="">All Statuses</option>
              <option value="errors">Any Error (4xx & 5xx)</option>
              <option value="client_errors">Client Errors (4xx)</option>
              <option value="server_errors">Server Errors (5xx)</option>
              <option value="200">200 OK</option>
              <option value="401">401 Unauthorized</option>
              <option value="403">403 Forbidden</option>
              <option value="404">404 Not Found</option>
            </select>
          </div>

          <div className="access-table-wrap">
            <table className="access-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>User / Role</th>
                  <th>IP Address</th>
                  <th>Method</th>
                  <th>Path & Query</th>
                  <th>Status</th>
                  <th>Latency</th>
                  <th>Device / Browser</th>
                </tr>
              </thead>
              <tbody>
                {loading && items.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="access-loading-cell">Loading access records...</td>
                  </tr>
                ) : items.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="access-empty-cell">No access events match your filters.</td>
                  </tr>
                ) : (
                  items.map((row) => (
                    <tr key={row.id}>
                      <td className="time-cell">
                        {row.created_at ? new Date(row.created_at).toLocaleString("en-US", {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        }) : "—"}
                      </td>
                      <td>
                        <strong>{row.user_name}</strong>
                        <small className="user-role-badge">{row.user_role}</small>
                        {row.user_email && <small className="user-email-text">{row.user_email}</small>}
                      </td>
                      <td className="ip-cell">
                        <code>{row.ip_address}</code>
                      </td>
                      <td>
                        <span className={`method-badge ${row.method.toLowerCase()}`}>{row.method}</span>
                      </td>
                      <td className="path-cell">
                        <span className="path-text" title={row.path}>{row.path}</span>
                        {row.query_params && <small className="query-text">?{row.query_params}</small>}
                      </td>
                      <td>
                        <span className={`status-badge status-${String(row.status_code)[0]}xx`}>
                          {row.status_code}
                        </span>
                      </td>
                      <td className="duration-cell">{row.duration_ms} ms</td>
                      <td className="agent-cell" title={row.user_agent}>
                        <small>{row.user_agent.slice(0, 75)}{row.user_agent.length > 75 ? "…" : ""}</small>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="access-pagination">
            <span>
              Showing {items.length ? (page - 1) * limit + 1 : 0}–
              {Math.min(page * limit, total)} of {total.toLocaleString()}
            </span>
            <div className="access-page-buttons">
              <button
                type="button"
                disabled={page <= 1 || loading}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                ‹ Previous
              </button>
              <span>Page {page} of {totalPages}</span>
              <button
                type="button"
                disabled={page >= totalPages || loading}
                onClick={() => setPage((p) => p + 1)}
              >
                Next ›
              </button>
            </div>
          </div>
        </>
      )}

      {tab === "by-user" && (
        <>
          <div className="access-filters-bar">
            <input
              type="text"
              placeholder="Search by user name or email..."
              value={groupSearch}
              onChange={(e) => setGroupSearch(e.target.value)}
              className="access-input search-input"
            />
          </div>
          <div className="access-table-wrap">
            <table className="access-table">
              <thead>
                <tr>
                  <th style={{ width: 34 }}></th>
                  <th>User</th>
                  <th>Role</th>
                  <th>Total Requests</th>
                  <th>Distinct IPs</th>
                  <th>Errors Encountered</th>
                  <th>Avg Response Time</th>
                  <th>Last Active</th>
                </tr>
              </thead>
              <tbody>
                {groupedLoading ? (
                  <tr>
                    <td colSpan={8} className="access-loading-cell">Aggregating user statistics...</td>
                  </tr>
                ) : groupedUsers.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="access-empty-cell">No user records found.</td>
                  </tr>
                ) : (
                  groupedUsers.map((u, idx) => {
                    const rowKey = `user-${u.user_id || "anon"}-${idx}`;
                    const isExpanded = expandedRowKey === rowKey;

                    return (
                      <Fragment key={rowKey}>
                        <tr
                          className={`expandable-row ${isExpanded ? "row-expanded" : ""}`}
                          onClick={() => toggleExpand(rowKey)}
                        >
                          <td className="expand-indicator">
                            <span className="expand-icon">{isExpanded ? "▾" : "▸"}</span>
                          </td>
                          <td>
                            <strong>{u.user_name}</strong>
                            {u.user_email && <small className="user-email-text">{u.user_email}</small>}
                          </td>
                          <td><span className="user-role-badge">{u.user_role}</span></td>
                          <td><strong>{u.total_requests.toLocaleString()}</strong></td>
                          <td>
                            <span className={`pill-badge ${u.distinct_ips > 3 ? "warning" : "neutral"}`}>
                              {u.distinct_ips} IP{u.distinct_ips === 1 ? "" : "s"}
                            </span>
                          </td>
                          <td>
                            {u.total_errors > 0 ? (
                              <span className="pill-badge error">{u.total_errors} errors</span>
                            ) : (
                              <span className="pill-badge success">0 errors</span>
                            )}
                          </td>
                          <td>{u.avg_duration_ms} ms</td>
                          <td className="time-cell">
                            {u.last_active ? new Date(u.last_active).toLocaleString("en-US") : "—"}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="expanded-detail-row">
                            <td colSpan={8} className="expanded-detail-cell">
                              <DrilldownPanel
                                initialFilter={u.user_id ? { user_id: u.user_id } : { user_id: "anonymous" }}
                                title={`Drill-down for User: ${u.user_name}`}
                                onClose={() => setExpandedRowKey(null)}
                                token={token}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "by-ip" && (
        <>
          <div className="access-filters-bar">
            <input
              type="text"
              placeholder="Search IP address..."
              value={groupSearch}
              onChange={(e) => setGroupSearch(e.target.value)}
              className="access-input search-input"
            />
          </div>
          <div className="access-table-wrap">
            <table className="access-table">
              <thead>
                <tr>
                  <th style={{ width: 34 }}></th>
                  <th>IP Address</th>
                  <th>Total Requests</th>
                  <th>Distinct Users</th>
                  <th>Total Errors</th>
                  <th>Last Active</th>
                  <th>Sample User Agent</th>
                </tr>
              </thead>
              <tbody>
                {groupedLoading ? (
                  <tr>
                    <td colSpan={7} className="access-loading-cell">Aggregating IP statistics...</td>
                  </tr>
                ) : groupedIps.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="access-empty-cell">No IP records found.</td>
                  </tr>
                ) : (
                  groupedIps.map((ipRow) => {
                    const rowKey = `ip-${ipRow.ip_address}`;
                    const isExpanded = expandedRowKey === rowKey;

                    return (
                      <Fragment key={rowKey}>
                        <tr
                          className={`expandable-row ${isExpanded ? "row-expanded" : ""}`}
                          onClick={() => toggleExpand(rowKey)}
                        >
                          <td className="expand-indicator">
                            <span className="expand-icon">{isExpanded ? "▾" : "▸"}</span>
                          </td>
                          <td className="ip-cell">
                            <code>{ipRow.ip_address}</code>
                          </td>
                          <td><strong>{ipRow.total_requests.toLocaleString()}</strong></td>
                          <td>
                            <span className={`pill-badge ${ipRow.distinct_users > 2 ? "warning" : "neutral"}`}>
                              {ipRow.distinct_users} user{ipRow.distinct_users === 1 ? "" : "s"}
                            </span>
                          </td>
                          <td>
                            {ipRow.total_errors > 0 ? (
                              <span className="pill-badge error">{ipRow.total_errors} errors</span>
                            ) : (
                              <span className="pill-badge success">0 errors</span>
                            )}
                          </td>
                          <td className="time-cell">
                            {ipRow.last_active ? new Date(ipRow.last_active).toLocaleString("en-US") : "—"}
                          </td>
                          <td className="agent-cell" title={ipRow.sample_user_agent}>
                            <small>{ipRow.sample_user_agent.slice(0, 80)}{ipRow.sample_user_agent.length > 80 ? "…" : ""}</small>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="expanded-detail-row">
                            <td colSpan={7} className="expanded-detail-cell">
                              <DrilldownPanel
                                initialFilter={{ ip_address: ipRow.ip_address }}
                                title={`Drill-down for IP: ${ipRow.ip_address}`}
                                onClose={() => setExpandedRowKey(null)}
                                token={token}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "by-path" && (
        <>
          <div className="access-filters-bar">
            <input
              type="text"
              placeholder="Filter endpoint path..."
              value={groupSearch}
              onChange={(e) => setGroupSearch(e.target.value)}
              className="access-input search-input"
            />
          </div>
          <div className="access-table-wrap">
            <table className="access-table">
              <thead>
                <tr>
                  <th style={{ width: 34 }}></th>
                  <th>Method</th>
                  <th>Endpoint Path</th>
                  <th>Total Hits</th>
                  <th>Failed Hits</th>
                  <th>Avg Latency</th>
                  <th>Last Accessed</th>
                </tr>
              </thead>
              <tbody>
                {groupedLoading ? (
                  <tr>
                    <td colSpan={7} className="access-loading-cell">Aggregating endpoint metrics...</td>
                  </tr>
                ) : groupedPaths.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="access-empty-cell">No endpoint records found.</td>
                  </tr>
                ) : (
                  groupedPaths.map((p, idx) => {
                    const rowKey = `path-${p.method}-${p.path}-${idx}`;
                    const isExpanded = expandedRowKey === rowKey;

                    return (
                      <Fragment key={rowKey}>
                        <tr
                          className={`expandable-row ${isExpanded ? "row-expanded" : ""}`}
                          onClick={() => toggleExpand(rowKey)}
                        >
                          <td className="expand-indicator">
                            <span className="expand-icon">{isExpanded ? "▾" : "▸"}</span>
                          </td>
                          <td>
                            <span className={`method-badge ${p.method.toLowerCase()}`}>{p.method}</span>
                          </td>
                          <td className="path-cell">
                            <code>{p.path}</code>
                          </td>
                          <td><strong>{p.total_requests.toLocaleString()}</strong></td>
                          <td>
                            {p.total_errors > 0 ? (
                              <span className="pill-badge error">{p.total_errors} errors</span>
                            ) : (
                              <span className="pill-badge success">0</span>
                            )}
                          </td>
                          <td>{p.avg_duration_ms} ms</td>
                          <td className="time-cell">
                            {p.last_active ? new Date(p.last_active).toLocaleString("en-US") : "—"}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="expanded-detail-row">
                            <td colSpan={7} className="expanded-detail-cell">
                              <DrilldownPanel
                                initialFilter={{ method: p.method, path: p.path }}
                                title={`Drill-down for Endpoint: ${p.method} ${p.path}`}
                                onClose={() => setExpandedRowKey(null)}
                                token={token}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "by-status" && (
        <>
          <div className="access-filters-bar">
            <input
              type="text"
              placeholder="Filter status code (e.g. 401, 200, 500)..."
              value={groupSearch}
              onChange={(e) => setGroupSearch(e.target.value)}
              className="access-input search-input"
            />
          </div>
          <div className="access-table-wrap">
            <table className="access-table">
              <thead>
                <tr>
                  <th style={{ width: 34 }}></th>
                  <th>Status Code</th>
                  <th>Total Requests</th>
                  <th>Distinct Users</th>
                  <th>Distinct IPs</th>
                  <th>Avg Latency</th>
                  <th>Last Active</th>
                </tr>
              </thead>
              <tbody>
                {groupedLoading ? (
                  <tr>
                    <td colSpan={7} className="access-loading-cell">Aggregating status statistics...</td>
                  </tr>
                ) : groupedStatuses.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="access-empty-cell">No status records found.</td>
                  </tr>
                ) : (
                  groupedStatuses.map((st) => {
                    const rowKey = `status-${st.status_code}`;
                    const isExpanded = expandedRowKey === rowKey;
                    return (
                      <Fragment key={rowKey}>
                        <tr
                          className={`expandable-row ${isExpanded ? "row-expanded" : ""}`}
                          onClick={() => toggleExpand(rowKey)}
                        >
                          <td className="expand-indicator">
                            <span className="expand-icon">{isExpanded ? "▾" : "▸"}</span>
                          </td>
                          <td>
                            <span className={`status-badge status-${String(st.status_code)[0]}xx`}>
                              {st.status_code}
                            </span>
                          </td>
                          <td><strong>{st.total_requests.toLocaleString()}</strong></td>
                          <td>{st.distinct_users} user{st.distinct_users === 1 ? "" : "s"}</td>
                          <td>{st.distinct_ips} IP{st.distinct_ips === 1 ? "" : "s"}</td>
                          <td>{st.avg_duration_ms} ms</td>
                          <td className="time-cell">
                            {st.last_active ? new Date(st.last_active).toLocaleString("en-US") : "—"}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="expanded-detail-row">
                            <td colSpan={7} className="expanded-detail-cell">
                              <DrilldownPanel
                                initialFilter={{ status_filter: String(st.status_code) }}
                                title={`Drill-down for Status Code ${st.status_code}`}
                                onClose={() => setExpandedRowKey(null)}
                                token={token}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
