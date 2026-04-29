import { useState, FormEvent } from "react";
import { useAuth } from "./AuthContext";
import { Navigate, useNavigate, useLocation } from "react-router-dom";

export default function LoginPage() {
  const { login, token } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string })?.from || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (token) return <Navigate to={from} replace />;

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "9px 12px", border: "1px solid #dddbda",
    borderRadius: 4, fontSize: 14, outline: "none", background: "#fff",
    boxSizing: "border-box",
  };
  const labelStyle: React.CSSProperties = {
    display: "block", marginBottom: 16,
  };
  const labelText: React.CSSProperties = {
    display: "block", marginBottom: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c",
  };

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "#f3f2f2",
    }}>
      <div style={{ width: 380 }}>
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <div style={{
            width: 48, height: 48, background: "#032d60", borderRadius: 12,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            marginBottom: 12,
          }}>
            <span style={{ color: "#fff", fontWeight: 800, fontSize: 18 }}>M</span>
          </div>
          <h1 style={{ fontSize: 22, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Moving CRM</h1>
          <p style={{ margin: 0, color: "#706e6b", fontSize: 14 }}>Sign in to your account</p>
        </div>

        <form onSubmit={handleSubmit} style={{
          background: "#fff",
          padding: "28px 28px 24px",
          borderRadius: 8,
          boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
          border: "1px solid #dddbda",
        }}>
          {error && (
            <div style={{
              background: "#fef3f2", border: "1px solid #f9b9b5", color: "#ba0517",
              padding: "8px 12px", borderRadius: 4, marginBottom: 16, fontSize: 13,
            }}>
              {error}
            </div>
          )}

          <label style={labelStyle}>
            <span style={labelText}>Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={inputStyle}
            />
          </label>

          <label style={{ ...labelStyle, marginBottom: 20 }}>
            <span style={labelText}>Password</span>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={inputStyle}
            />
          </label>

          <button type="submit" disabled={submitting} style={{
            width: "100%", padding: "10px 0",
            background: submitting ? "#5a9fd4" : "#0176d3",
            color: "#fff", border: "none", borderRadius: 4, fontSize: 14, fontWeight: 600,
            cursor: submitting ? "default" : "pointer",
            transition: "background .15s",
          }}>
            {submitting ? "Signing in…" : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
}
