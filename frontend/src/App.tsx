import { BrowserRouter, Routes, Route, Navigate, useLocation, Link } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext";
import LoginPage from "./LoginPage";
import ChangePasswordPage from "./ChangePasswordPage";
import LeadsList from "./LeadsList";
import LeadDetail from "./LeadDetail";
import OutreachEventsPage from "./OutreachEventsPage";

function ProtectedRoutes() {
  const { token, loading, logout } = useAuth();
  const location = useLocation();
  if (loading) return <p style={{ padding: 24 }}>Loading…</p>;
  if (!token) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return (
    <>
      <div style={{
        display: "flex", justifyContent: "flex-end", gap: 8, padding: "8px 24px",
        borderBottom: "1px solid #eee", background: "#fafafa",
      }}>
        <Link to="/" style={{
          fontSize: 13, color: "#2563eb", textDecoration: "none",
          alignSelf: "center",
        }}>
          Leads
        </Link>
        <Link to="/outreach" style={{
          fontSize: 13, color: "#2563eb", textDecoration: "none",
          alignSelf: "center",
        }}>
          Outreach Activity
        </Link>
        <Link to="/change-password" style={{
          fontSize: 13, color: "#2563eb", textDecoration: "none",
          alignSelf: "center",
        }}>
          Change Password
        </Link>
        <button onClick={logout} style={{
          background: "none", border: "1px solid #ccc", borderRadius: 4,
          padding: "4px 12px", cursor: "pointer", fontSize: 13,
        }}>
          Sign Out
        </button>
      </div>
      <Routes>
        <Route path="/" element={<LeadsList />} />
        <Route path="/outreach" element={<OutreachEventsPage />} />
        <Route path="/leads/:leadId" element={<LeadDetail />} />
        <Route path="/change-password" element={<ChangePasswordPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
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
