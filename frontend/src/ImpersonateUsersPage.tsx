import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { authHeaders, useAuth, User } from "./AuthContext";
import { API_BASE } from "./apiConfig";

type ManagedUser = User & { email: string; companies?: Array<{ id: string; name: string }> };

const roleLabel: Record<string, string> = {
  admin: "Admin",
  sales_rep: "Sales Rep",
  dispatch: "Dispatch",
  foreman: "Foreman",
};

export default function ImpersonateUsersPage() {
  const { token, user, impersonate } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/auth/impersonation-targets`, { headers: authHeaders(token) })
      .then(async (response) => {
        const data = await response.json().catch(() => null);
        if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
        setUsers(Array.isArray(data) ? data : []);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Failed to load users"))
      .finally(() => setLoading(false));
  }, [token]);

  const visibleUsers = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return users.filter((item) => item.id !== user?.id && (role === "all" || item.role === role) && (!needle || `${item.name} ${item.email} ${item.role}`.toLowerCase().includes(needle)));
  }, [users, user?.id, role, query]);

  async function beginImpersonation(target: ManagedUser) {
    if (!window.confirm(`Continue as ${target.name}? You will see exactly what this ${roleLabel[target.role] || target.role} can see.`)) return;
    setBusyId(target.id);
    setError("");
    try {
      await impersonate(target.id);
      navigate(target.role === "dispatch" || target.role === "foreman" ? "/dispatch" : "/", { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to impersonate user");
    } finally {
      setBusyId("");
    }
  }

  return (
    <main className="impersonate-page">
      <header className="impersonate-heading">
        <div><span>{user?.role === "admin" ? "ADMIN TOOL" : "DISPATCH TOOL"}</span><h1>{user?.role === "admin" ? "Impersonate a User" : "View as a Foreman"}</h1><p>{user?.role === "admin" ? "Open the CRM with another user's exact permissions. No password is required." : "Open the CRM as one of the foremen within your assigned companies."}</p></div>
      </header>
      <section className={`impersonate-toolbar${user?.role === "dispatch" ? " single" : ""}`}>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by name or email" aria-label="Search users" />
        {user?.role === "admin" ? <select value={role} onChange={(event) => setRole(event.target.value)} aria-label="Filter by role">
          <option value="all">All roles</option><option value="admin">Admins</option><option value="sales_rep">Sales reps</option><option value="dispatch">Dispatch</option><option value="foreman">Foremen</option>
        </select> : null}
      </section>
      {error ? <div className="impersonate-error">{error}</div> : null}
      {loading ? <div className="impersonate-state">Loading users...</div> : null}
      {!loading ? <section className="impersonate-list">
        {visibleUsers.map((item) => (
          <article key={item.id}>
            <div className="impersonate-avatar">{item.name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase()}</div>
            <div className="impersonate-user"><strong>{item.name}</strong><span>{item.email}</span><small>{item.companies?.length ? `${item.companies.length} companies` : "No company scope"}</small></div>
            <span className={`impersonate-role role-${item.role}`}>{roleLabel[item.role] || item.role}</span>
            <button type="button" disabled={Boolean(busyId)} onClick={() => void beginImpersonation(item)}>{busyId === item.id ? "Opening..." : "View as user"}</button>
          </article>
        ))}
        {!visibleUsers.length ? <div className="impersonate-state">No users match your search.</div> : null}
      </section> : null}
    </main>
  );
}
