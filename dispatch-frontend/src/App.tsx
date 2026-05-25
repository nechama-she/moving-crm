import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext";
import LoginPage from "./LoginPage";
import CalendarPage from "./CalendarPage";

function ProtectedRoutes() {
  const { token, loading, logout, user } = useAuth();
  const location = useLocation();

  if (loading) return <div className="loading-screen">Loading…</div>;
  if (!token) return <Navigate to="/login" state={{ from: location.pathname }} replace />;

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-logo">Dispatch</span>
        <div className="header-right">
          <span className="header-user">{user?.name}</span>
          <button className="btn-ghost" onClick={logout}>
            Sign Out
          </button>
        </div>
      </header>
      <main className="app-content">
        <Routes>
          <Route path="/" element={<CalendarPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/*" element={<ProtectedRoutes />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
