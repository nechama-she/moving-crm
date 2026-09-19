import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Endpoint = {
  path: string;
  methods: string[];
  tag: string;
  summary: string;
};

type PermissionRule = {
  scope?: string;
  path?: string;
  methods: string[];
};

type AppUser = {
  id: string;
  name: string;
  email: string;
  role: string;
  system_permissions?: PermissionRule[] | null;
  created_at?: string;
};

const ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

export default function SystemUsersPage() {
  const { token, user } = useAuth();
  const canUse = user?.role === "admin";

  const [users, setUsers] = useState<AppUser[]>([]);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  // Create form state
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  // Permissions builder for Create / Edit
  const [rules, setRules] = useState<PermissionRule[]>([]);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);

  // Filter/search
  const [search, setSearch] = useState("");
  const [collapsedScopes, setCollapsedScopes] = useState<Record<string, boolean>>({});

  const systemUsers = useMemo(
    () => users.filter((u) => u.role === "system_user").sort((a, b) => a.name.localeCompare(b.name)),
    [users]
  );

  // Group endpoints by Tag (Scope)
  const groupedEndpoints = useMemo(() => {
    const groups: Record<string, Endpoint[]> = {};
    for (const ep of endpoints) {
      if (!groups[ep.tag]) groups[ep.tag] = [];
      groups[ep.tag].push(ep);
    }
    return groups;
  }, [endpoints]);

  useEffect(() => {
    if (!canUse) {
      setLoading(false);
      return;
    }
    void loadData();
  }, [token, canUse]);

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const [usersRes, epRes] = await Promise.all([
        fetch(`${API_BASE}/api/users`, { headers: authHeaders(token) }),
        fetch(`${API_BASE}/api/users/system-endpoints`, { headers: authHeaders(token) }),
      ]);
      if (!usersRes.ok) throw new Error(`Users HTTP ${usersRes.status}`);
      if (!epRes.ok) throw new Error(`Endpoints HTTP ${epRes.status}`);
      const userRows = (await usersRes.json()) as AppUser[];
      const epRows = (await epRes.json()) as Endpoint[];
      setUsers(userRows || []);
      setEndpoints(epRows || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load system users and endpoints");
    } finally {
      setLoading(false);
    }
  }

  function resetForm() {
    setName("");
    setEmail("");
    setPassword("");
    setRules([]);
    setEditingUserId(null);
  }

  function startEdit(u: AppUser) {
    setEditingUserId(u.id);
    setName(u.name);
    setEmail(u.email);
    setPassword("");
    setRules(u.system_permissions || []);
    setError("");
    setInfo("");
  }

  // Scope-level helpers
  function getScopeRule(scope: string): PermissionRule | undefined {
    return rules.find((r) => r.scope === scope && !r.path);
  }

  function toggleScopeMethod(scope: string, method: string) {
    setRules((prev) => {
      const existing = prev.find((r) => r.scope === scope && !r.path);
      if (!existing) {
        return [...prev, { scope, methods: [method] }];
      }
      const methods = existing.methods.includes("*") ? [...ALL_METHODS] : [...existing.methods];
      const nextMethods = methods.includes(method)
        ? methods.filter((m) => m !== method)
        : [...methods, method];

      if (nextMethods.length === 0) {
        return prev.filter((r) => !(r.scope === scope && !r.path));
      }
      return prev.map((r) => (r.scope === scope && !r.path ? { ...r, methods: nextMethods } : r));
    });
  }

  function toggleAllScopeMethods(scope: string, enabled: boolean) {
    setRules((prev) => {
      const filtered = prev.filter((r) => !(r.scope === scope && !r.path));
      if (!enabled) return filtered;
      return [...filtered, { scope, methods: ["*"] }];
    });
  }

  // Endpoint-level helpers
  function getEndpointRule(path: string): PermissionRule | undefined {
    return rules.find((r) => r.path === path);
  }

  function toggleEndpointMethod(path: string, method: string) {
    setRules((prev) => {
      const existing = prev.find((r) => r.path === path);
      if (!existing) {
        return [...prev, { path, methods: [method] }];
      }
      const methods = existing.methods.includes("*") ? [...ALL_METHODS] : [...existing.methods];
      const nextMethods = methods.includes(method)
        ? methods.filter((m) => m !== method)
        : [...methods, method];

      if (nextMethods.length === 0) {
        return prev.filter((r) => r.path !== path);
      }
      return prev.map((r) => (r.path === path ? { ...r, methods: nextMethods } : r));
    });
  }

  async function handleSave() {
    setError("");
    setInfo("");

    if (!name.trim()) {
      setError("User name is required");
      return;
    }
    if (!editingUserId && (!email.trim() || !password.trim())) {
      setError("Email and password are required for new system users");
      return;
    }

    setSaving(true);
    try {
      if (editingUserId) {
        const res = await fetch(`${API_BASE}/api/users/${editingUserId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json", ...authHeaders(token) },
          body: JSON.stringify({
            name: name.trim(),
            system_permissions: rules,
          }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        setInfo("System user permissions updated successfully.");
      } else {
        const res = await fetch(`${API_BASE}/api/users`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders(token) },
          body: JSON.stringify({
            name: name.trim(),
            email: email.trim(),
            password: password.trim(),
            role: "system_user",
            system_permissions: rules,
          }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        setInfo("System user created successfully.");
      }
      resetForm();
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save system user");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(u: AppUser) {
    if (!window.confirm(`Delete system user ${u.name} (${u.email})?`)) return;
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/${u.id}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setInfo("System user deleted.");
      if (editingUserId === u.id) resetForm();
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete user");
    }
  }

  if (!canUse) {
    return (
      <div style={{ padding: "20px 24px" }}>
        <h1 style={{ fontSize: 20, color: "#032d60", marginBottom: 8 }}>System Users</h1>
        <p style={{ color: "#ba0517" }}>Only admins can manage system users.</p>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>System Users</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Create service and system users with granular access to specific endpoints, scopes, and HTTP methods.
      </p>

      {/* Editor / Creation Card */}
      <div style={{ border: "1px solid #dddbda", borderRadius: 4, padding: 16, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)", marginBottom: 16 }}>
        <h2 style={{ fontSize: 14, fontWeight: 700, color: "#032d60", margin: "0 0 12px" }}>
          {editingUserId ? "Edit System User Permissions" : "Create System User"}
        </h2>

        <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", marginBottom: 16 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, fontWeight: 600, color: "#3e3e3c" }}>
            Name *
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. LiveSwitch Integration Service"
              style={{ padding: "7px 9px", border: "1px solid #c9c7c5", borderRadius: 4, fontSize: 13 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, fontWeight: 600, color: "#3e3e3c" }}>
            Email / Identity *
            <input
              value={email}
              disabled={!!editingUserId}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. svc-liveswitch@company.com"
              style={{ padding: "7px 9px", border: "1px solid #c9c7c5", borderRadius: 4, fontSize: 13, background: editingUserId ? "#f3f3f3" : "#fff" }}
            />
          </label>
          {!editingUserId && (
            <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, fontWeight: 600, color: "#3e3e3c" }}>
              Password / Secret *
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min 8 chars"
                  style={{ flex: 1, padding: "7px 9px", border: "1px solid #c9c7c5", borderRadius: 4, fontSize: 13 }}
                />
                <button
                  type="button"
                  className="slds-button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={{ padding: "0 10px", fontSize: 12 }}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </label>
          )}
        </div>

        {/* Permissions Builder */}
        <div style={{ borderTop: "1px solid #e5e5e5", paddingTop: 14 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
            <div>
              <strong style={{ fontSize: 13, color: "#032d60" }}>Allowed Scopes & Endpoints</strong>
              <p style={{ margin: "2px 0 0", fontSize: 11, color: "#706e6b" }}>
                Select entire scopes (tags) or specific endpoints, along with the permitted HTTP methods.
              </p>
            </div>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter scopes or paths..."
              style={{ padding: "6px 9px", border: "1px solid #c9c7c5", borderRadius: 4, fontSize: 12, width: 220 }}
            />
          </div>

          <div style={{ maxHeight: 380, overflowY: "auto", border: "1px solid #dddbda", borderRadius: 4, background: "#fafaf9", padding: 8 }}>
            {Object.keys(groupedEndpoints).length === 0 ? (
              <p style={{ margin: 12, fontSize: 12, color: "#706e6b" }}>Loading endpoints...</p>
            ) : null}

            {Object.entries(groupedEndpoints).map(([scope, eps]) => {
              const scopeRule = getScopeRule(scope);
              const scopeHasAll = scopeRule?.methods.includes("*");
              const isCollapsed = collapsedScopes[scope] ?? true;

              const filteredEps = eps.filter((ep) =>
                !search.trim() ||
                scope.toLowerCase().includes(search.toLowerCase()) ||
                ep.path.toLowerCase().includes(search.toLowerCase()) ||
                ep.summary.toLowerCase().includes(search.toLowerCase())
              );

              if (search.trim() && filteredEps.length === 0) return null;

              return (
                <div key={scope} style={{ marginBottom: 8, background: "#fff", border: "1px solid #e5e5e5", borderRadius: 4, overflow: "hidden" }}>
                  {/* Scope Master Row */}
                  <div
                    style={{
                      padding: "8px 12px",
                      background: scopeRule ? "#eef4ff" : "#f3f3f3",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      borderBottom: isCollapsed && !search.trim() ? "none" : "1px solid #e5e5e5",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
                      <button
                        type="button"
                        onClick={() => setCollapsedScopes((prev) => ({ ...prev, [scope]: !isCollapsed }))}
                        style={{ border: "none", background: "none", cursor: "pointer", padding: 2, fontSize: 11, color: "#706e6b" }}
                      >
                        {isCollapsed && !search.trim() ? "▶" : "▼"}
                      </button>
                      <strong style={{ fontSize: 13, color: "#032d60" }}>[{scope}]</strong>
                      <span style={{ fontSize: 11, color: "#706e6b" }}>({eps.length} endpoints)</span>
                    </div>

                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 11, color: "#3e3e3c", fontWeight: 600 }}>Scope Methods:</span>
                      <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={!!scopeHasAll}
                          onChange={(e) => toggleAllScopeMethods(scope, e.target.checked)}
                        />
                        ALL
                      </label>
                      {ALL_METHODS.map((m) => {
                        const isChecked = scopeHasAll || (scopeRule?.methods || []).includes(m);
                        return (
                          <label key={m} style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 11, cursor: "pointer" }}>
                            <input
                              type="checkbox"
                              checked={isChecked}
                              disabled={scopeHasAll}
                              onChange={() => toggleScopeMethod(scope, m)}
                            />
                            {m}
                          </label>
                        );
                      })}
                    </div>
                  </div>

                  {/* Individual Endpoints inside Scope */}
                  {(!isCollapsed || search.trim()) && (
                    <div style={{ padding: "6px 12px" }}>
                      {filteredEps.map((ep) => {
                        const epRule = getEndpointRule(ep.path);

                        return (
                          <div
                            key={ep.path}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              padding: "6px 0",
                              borderBottom: "1px solid #f3f3f3",
                              gap: 12,
                            }}
                          >
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <span style={{ fontFamily: "monospace", fontSize: 12, color: "#032d60", fontWeight: 600 }}>
                                {ep.path}
                              </span>
                              {ep.summary && (
                                <span style={{ marginLeft: 8, fontSize: 11, color: "#706e6b" }}>
                                  ({ep.summary})
                                </span>
                              )}
                            </div>

                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              {ep.methods.map((m) => {
                                const isPermittedByScope = scopeHasAll || (scopeRule?.methods || []).includes(m);
                                const isPermittedByEndpoint = (epRule?.methods || []).includes(m) || (epRule?.methods || []).includes("*");
                                const active = isPermittedByScope || isPermittedByEndpoint;

                                return (
                                  <label
                                    key={m}
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      gap: 3,
                                      fontSize: 10,
                                      cursor: isPermittedByScope ? "default" : "pointer",
                                      color: isPermittedByScope ? "#0284c7" : "#3e3e3c",
                                    }}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={active}
                                      disabled={isPermittedByScope}
                                      onChange={() => toggleEndpointMethod(ep.path, m)}
                                    />
                                    {m}
                                  </label>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Action Buttons */}
        <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
          <button
            type="button"
            className="slds-button"
            onClick={() => void handleSave()}
            disabled={saving}
            style={{
              border: "none",
              background: saving ? "#5a9fd4" : "#0176d3",
              color: "#fff",
              borderRadius: 4,
              padding: "8px 16px",
              fontWeight: 600,
            }}
          >
            {saving ? "Saving..." : editingUserId ? "Update System User" : "Create System User"}
          </button>
          {editingUserId && (
            <button
              type="button"
              className="slds-button"
              onClick={resetForm}
              style={{ border: "1px solid #c9c7c5", background: "#fff", color: "#3e3e3c", borderRadius: 4, padding: "8px 14px", fontWeight: 600 }}
            >
              Cancel Edit
            </button>
          )}
        </div>
      </div>

      {error ? <p style={{ marginBottom: 10, color: "#ba0517", fontSize: 13 }}>{error}</p> : null}
      {info ? <p style={{ marginBottom: 10, color: "#2e844a", fontSize: 13 }}>{info}</p> : null}

      {/* Existing System Users Directory */}
      <div style={{ border: "1px solid #dddbda", borderRadius: 4, overflow: "auto", background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)" }}>
        <div style={{ padding: 12, borderBottom: "1px solid #dddbda" }}>
          <strong style={{ color: "#032d60", fontSize: 14 }}>System Users ({systemUsers.length})</strong>
        </div>

        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 700 }}>
          <thead>
            <tr>
              <th style={th}>Name</th>
              <th style={th}>Identity (Email)</th>
              <th style={th}>Configured Permissions</th>
              <th style={th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td style={td} colSpan={4}>Loading system users...</td>
              </tr>
            ) : null}

            {!loading && systemUsers.length === 0 ? (
              <tr>
                <td style={td} colSpan={4}>No system users configured yet. Create one above to grant API access.</td>
              </tr>
            ) : null}

            {!loading && systemUsers.map((u) => {
              const perms = u.system_permissions || [];
              return (
                <tr key={u.id} style={{ borderTop: "1px solid #f1f0ef" }}>
                  <td style={{ ...td, fontWeight: 600, color: "#032d60" }}>{u.name}</td>
                  <td style={{ ...td, fontFamily: "monospace", fontSize: 12 }}>{u.email}</td>
                  <td style={td}>
                    {perms.length === 0 ? (
                      <span style={{ color: "#9ca3af", fontStyle: "italic" }}>No permissions (access blocked)</span>
                    ) : (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {perms.map((p, idx) => (
                          <span
                            key={idx}
                            style={{
                              background: "#f0fdf4",
                              border: "1px solid #bbf7d0",
                              color: "#166534",
                              borderRadius: 4,
                              padding: "2px 6px",
                              fontSize: 11,
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 4,
                            }}
                          >
                            <strong>{p.scope ? `[${p.scope}]` : p.path}</strong>
                            <span style={{ fontSize: 10, color: "#059669" }}>
                              ({p.methods.join(", ")})
                            </span>
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td style={td}>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        type="button"
                        className="slds-button"
                        onClick={() => startEdit(u)}
                        style={{ border: "1px solid #0176d3", color: "#0176d3", background: "#fff", borderRadius: 4, padding: "4px 10px", fontSize: 12, fontWeight: 600 }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="slds-button"
                        onClick={() => void handleDelete(u)}
                        style={{ border: "1px solid #ba0517", color: "#ba0517", background: "#fff", borderRadius: 4, padding: "4px 10px", fontSize: 12, fontWeight: 600 }}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 12px",
  fontSize: 11,
  textTransform: "uppercase",
  color: "#706e6b",
  borderBottom: "1px solid #dddbda",
  background: "#fafaf9",
};

const td: React.CSSProperties = {
  padding: "10px 12px",
  fontSize: 13,
  color: "#181818",
};
