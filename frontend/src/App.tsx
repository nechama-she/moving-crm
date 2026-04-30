import { BrowserRouter, Routes, Route, Navigate, useLocation, NavLink } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext";
import LoginPage from "./LoginPage";
import ChangePasswordPage from "./ChangePasswordPage";
import LeadsList from "./LeadsList";
import LeadDetail from "./LeadDetail";
import OutreachEventsPage from "./OutreachEventsPage";
import PeriodAssignPage from "./PeriodAssignPage";
import SalesRepsPage from "./SalesRepsPage";
import SettingsPage from "./SettingsPage";

const navLinkStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
  color: isActive ? "#ffffff" : "#9dc9e8",
  fontSize: 14,
  fontWeight: isActive ? 600 : 400,
  padding: "0 16px",
  height: 52,
  display: "flex",
  alignItems: "center",
  textDecoration: "none",
  borderBottom: isActive ? "2px solid #fff" : "2px solid transparent",
  whiteSpace: "nowrap",
});

function ProtectedRoutes() {
  const { token, loading, logout, user } = useAuth();
  const location = useLocation();
  if (loading) return <div style={{ padding: 24 }}>Loading…</div>;
  if (!token) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (user?.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <nav style={{
        background: "#032d60",
        display: "flex",
        alignItems: "center",
        padding: "0 20px",
        height: 52,
        flexShrink: 0,
        boxShadow: "0 2px 4px rgba(0,0,0,.25)",
      }}>
        <span style={{ color: "#fff", fontWeight: 700, fontSize: 16, marginRight: 24, letterSpacing: "-0.2px", whiteSpace: "nowrap" }}>
          Moving CRM
        </span>
        <div style={{ display: "flex", flex: 1 }}>
          <NavLink to="/" end style={navLinkStyle}>Leads</NavLink>
          <NavLink to="/outreach" style={navLinkStyle}>Outreach</NavLink>
          <NavLink to="/assign-period" style={navLinkStyle}>Assign By Period</NavLink>
          {user?.role === "admin" ? <NavLink to="/sales-reps" style={navLinkStyle}>Sales Reps</NavLink> : null}
          <NavLink to="/settings" style={navLinkStyle}>Settings</NavLink>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {user && <span style={{ color: "#9dc9e8", fontSize: 13 }}>{user.name}</span>}
          <NavLink to="/change-password" style={({ isActive }) => ({ ...navLinkStyle({ isActive }), padding: "0 8px", fontSize: 13 })}>
            Change Password
          </NavLink>
          <button
            onClick={logout}
            style={{
              background: "none", border: "1px solid rgba(255,255,255,.35)",
              color: "#fff", borderRadius: 4, padding: "5px 14px",
              fontSize: 13,
            }}
          >
            Sign Out
          </button>
        </div>
      </nav>
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <Routes>
          <Route path="/" element={<LeadsList />} />
          <Route path="/outreach" element={<OutreachEventsPage />} />
          <Route path="/assign-period" element={<PeriodAssignPage />} />
          <Route path="/sales-reps" element={<SalesRepsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/leads/:leadId" element={<LeadDetail />} />
          <Route path="/change-password" element={<ChangePasswordPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/*" element={<ProtectedRoutes />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
