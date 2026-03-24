import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext";
import LoginPage from "./LoginPage";
import LeadsList from "./LeadsList";
import LeadDetail from "./LeadDetail";

function ProtectedRoutes() {
  const { token, loading, logout } = useAuth();
  if (loading) return <p style={{ padding: 24 }}>Loading…</p>;
  if (!token) return <Navigate to="/login" replace />;
  return (
    <>
      <div style={{
        display: "flex", justifyContent: "flex-end", padding: "8px 24px",
        borderBottom: "1px solid #eee", background: "#fafafa",
      }}>
        <button onClick={logout} style={{
          background: "none", border: "1px solid #ccc", borderRadius: 4,
          padding: "4px 12px", cursor: "pointer", fontSize: 13,
        }}>
          Sign Out
        </button>
      </div>
      <Routes>
        <Route path="/" element={<LeadsList />} />
        <Route path="/leads/:leadId" element={<LeadDetail />} />
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
