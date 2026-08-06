import { BrowserRouter, Routes, Route, Navigate, useLocation, NavLink } from "react-router-dom";
import { lazy, Suspense, useEffect, useState } from "react";
import { AuthProvider, useAuth } from "./AuthContext";

const LoginPage = lazy(() => import("./LoginPage"));
const ChangePasswordPage = lazy(() => import("./ChangePasswordPage"));
const LeadsList = lazy(() => import("./LeadsList"));
const LeadDetail = lazy(() => import("./LeadDetail"));
const OutreachEventsPage = lazy(() => import("./OutreachEventsPage"));
const PeriodAssignPage = lazy(() => import("./PeriodAssignPage"));
const SalesRepsPage = lazy(() => import("./SalesRepsPage"));
const DispatchPage = lazy(() => import("./DispatchPage"));
const CompaniesPage = lazy(() => import("./CompaniesPage"));
const CompanyTemplatesPage = lazy(() => import("./CompanyTemplatesPage"));
const SettingsPage = lazy(() => import("./SettingsPage"));
const AutoAssignTrackerPage = lazy(() => import("./AutoAssignTrackerPage"));
const AdminUsersPage = lazy(() => import("./AdminUsersPage"));
const SalesCalendarPage = lazy(() => import("./SalesCalendarPage"));
const PendingDuplicationsPage = lazy(() => import("./PendingDuplicationsPage"));
const PricingPage = lazy(() => import("./PricingPage"));
const SalesPerformancePage = lazy(() => import("./SalesPerformancePage"));
const ForemenPage = lazy(() => import("./ForemenPage"));
const ImpersonateUsersPage = lazy(() => import("./ImpersonateUsersPage"));

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
  const { token, loading, logout, user, isImpersonating, previousUser, stopImpersonating } = useAuth();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  useEffect(() => setMobileMenuOpen(false), [location.pathname]);
  const isDispatchUser = user?.role === "dispatch";
  const isForemanUser = user?.role === "foreman";
  const isDispatchAllowedPath =
    location.pathname === "/dispatch" ||
    location.pathname === "/sales-calendar" ||
    location.pathname === "/sales-performance" ||
    location.pathname === "/foremen" ||
    location.pathname === "/settings/impersonate" ||
    location.pathname === "/settings" ||
    location.pathname === "/change-password" ||
    /^\/leads\/[^/]+$/.test(location.pathname);
  if (loading) return <div style={{ padding: 24 }}>Loading…</div>;
  if (!token) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (user?.must_change_password && !isImpersonating && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  const isForemanAllowedPath =
    location.pathname === "/dispatch" ||
    location.pathname === "/settings" ||
    location.pathname === "/change-password" ||
    /^\/leads\/[^/]+$/.test(location.pathname);
  if (isDispatchUser && !isDispatchAllowedPath) {
    return <Navigate to="/dispatch" replace />;
  }
  if (isForemanUser && !isForemanAllowedPath) {
    return <Navigate to="/dispatch" replace />;
  }
  return (
    <div className="crm-shell" style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      {isImpersonating ? <div className="impersonation-banner"><span>Viewing CRM as <strong>{user?.name}</strong> ({user?.role}).</span><button type="button" onClick={() => { stopImpersonating(); window.location.assign("/settings/impersonate"); }}>Return to {previousUser?.name || "Previous User"}</button></div> : null}
      <nav className="crm-nav" style={{
        background: "#032d60",
        display: "flex",
        alignItems: "center",
        padding: "0 20px",
        height: 52,
        flexShrink: 0,
        boxShadow: "0 2px 4px rgba(0,0,0,.25)",
      }}>
        <span className="crm-brand" style={{ color: "#fff", fontWeight: 700, fontSize: 16, marginRight: 24, letterSpacing: "-0.2px", whiteSpace: "nowrap" }}>
          Moving CRM
        </span>
        <button
          type="button"
          className="crm-mobile-menu-button"
          aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
          aria-expanded={mobileMenuOpen}
          onClick={() => setMobileMenuOpen((open) => !open)}
        >
          <span aria-hidden="true">{mobileMenuOpen ? "×" : "☰"}</span>
        </button>
        <div className="crm-nav-links" style={{ display: "flex", flex: 1 }}>
          {isForemanUser ? (
            <>
              <NavLink to="/dispatch" style={navLinkStyle}>My Jobs</NavLink>
              <NavLink to="/settings" style={navLinkStyle}>Settings</NavLink>
            </>
          ) : isDispatchUser ? (
            <>
              <NavLink to="/dispatch" style={navLinkStyle}>Dispatch Calendar</NavLink>
              <NavLink to="/sales-calendar" style={navLinkStyle}>Sales Calender</NavLink>
              <NavLink to="/sales-performance" style={navLinkStyle}>Performance</NavLink>
              <NavLink to="/settings" style={navLinkStyle}>Settings</NavLink>
            </>
          ) : (
            <>
              <NavLink to="/" end style={navLinkStyle}>Leads</NavLink>
              <NavLink to="/sales-calendar" style={navLinkStyle}>Sales Calender</NavLink>
              <NavLink to="/sales-performance" style={navLinkStyle}>Performance</NavLink>
              <NavLink to="/outreach" style={navLinkStyle}>Outreach</NavLink>
                  <NavLink to="/settings" style={navLinkStyle}>Settings</NavLink>
                  <NavLink to="/pricing" style={navLinkStyle}>Pricing</NavLink>
              {user?.role === "admin" && (
                <>
                  <NavLink to="/dispatch" style={navLinkStyle}>Dispatch Calendar</NavLink>
                </>
              )}
            </>
          )}
        </div>
        <div className="crm-user-actions" style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {user && <span style={{ color: "#9dc9e8", fontSize: 13 }}>{user.name}</span>}
          {!isDispatchUser && !isImpersonating ? (
            <NavLink to="/change-password" style={({ isActive }) => ({ ...navLinkStyle({ isActive }), padding: "0 8px", fontSize: 13 })}>
              Change Password
            </NavLink>
          ) : null}
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
      {mobileMenuOpen ? (
        <>
          <button
            type="button"
            className="crm-mobile-menu-backdrop"
            aria-label="Close navigation menu"
            onClick={() => setMobileMenuOpen(false)}
          />
          <aside className="crm-mobile-menu" aria-label="Main navigation">
            <div className="crm-mobile-menu-user">
              <strong>{user?.name || "User"}</strong>
              <span>{user?.role || ""}</span>
            </div>
            <div className="crm-mobile-menu-links">
              {isForemanUser ? (
                <>
                  <NavLink to="/dispatch">My Jobs</NavLink>
                  <NavLink to="/settings">Settings</NavLink>
                  {!isImpersonating ? <NavLink to="/change-password">Change Password</NavLink> : null}
                </>
              ) : isDispatchUser ? (
                <>
                  <NavLink to="/dispatch">Dispatch Calendar</NavLink>
                  <NavLink to="/sales-calendar">Sales Calendar</NavLink>
                  <NavLink to="/sales-performance">Sales Performance</NavLink>
                  <NavLink to="/settings">Settings</NavLink>
                </>
              ) : (
                <>
                  <NavLink to="/">Leads</NavLink>
                  <NavLink to="/sales-calendar">Sales Calendar</NavLink>
                  <NavLink to="/sales-performance">Sales Performance</NavLink>
                  <NavLink to="/outreach">Outreach</NavLink>
                  <NavLink to="/settings">Settings</NavLink>
                  <NavLink to="/pricing">Pricing</NavLink>
                  {user?.role === "admin" ? (
                    <>
                      <NavLink to="/dispatch">Dispatch Calendar</NavLink>
                    </>
                  ) : null}
                  {!isImpersonating ? <NavLink to="/change-password">Change Password</NavLink> : null}
                </>
              )}
            </div>
            <button type="button" className="crm-mobile-signout" onClick={logout}>Sign Out</button>
          </aside>
        </>
      ) : null}
      <div className="crm-main" style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
        <Routes>
          <Route path="/" element={<LeadsList />} />
          <Route path="/outreach" element={<OutreachEventsPage />} />
          <Route path="/sales-calendar" element={<SalesCalendarPage />} />
          <Route path="/sales-performance" element={<SalesPerformancePage />} />
          <Route path="/assign-period" element={<PeriodAssignPage />} />
          <Route path="/sales-reps" element={<SalesRepsPage />} />
          <Route path="/admin-users" element={<AdminUsersPage />} />
          <Route path="/dispatch" element={<DispatchPage mode="calendar" />} />
          <Route path="/dispatch-users" element={<DispatchPage mode="manage" />} />
          <Route path="/foremen" element={<ForemenPage />} />
          <Route path="/settings/companies" element={<CompaniesPage />} />
          <Route path="/settings/templates" element={<CompanyTemplatesPage />} />
          <Route path="/settings/pending-duplications" element={<PendingDuplicationsPage />} />
          <Route path="/settings/impersonate" element={<ImpersonateUsersPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/pricing" element={<PricingPage />} />
          <Route path="/auto-assign-tracker" element={<AutoAssignTrackerPage />} />
          <Route path="/leads/:leadId" element={<LeadDetail />} />
          <Route path="/change-password" element={<ChangePasswordPage />} />
          <Route path="*" element={<Navigate to={isDispatchUser || isForemanUser ? "/dispatch" : "/"} replace />} />
        </Routes>
      </div>
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Suspense fallback={<div style={{ padding: 24 }}>Loading…</div>}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/*" element={<ProtectedRoutes />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
