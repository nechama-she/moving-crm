import { useState, FormEvent } from "react";
import { useAuth } from "./AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "#f0f2f5",
      fontFamily: "sans-serif",
    }}>
      <form onSubmit={handleSubmit} style={{
        background: "#fff",
        padding: "40px 32px",
        borderRadius: 12,
        boxShadow: "0 2px 16px rgba(0,0,0,0.1)",
        width: 360,
      }}>
        <h1 style={{ margin: "0 0 8px", fontSize: 24, color: "#333" }}>Moving CRM</h1>
        <p style={{ margin: "0 0 24px", color: "#666", fontSize: 14 }}>Sign in to your account</p>

        {error && (
          <div style={{
            background: "#fee", border: "1px solid #fcc", color: "#c33",
            padding: "8px 12px", borderRadius: 6, marginBottom: 16, fontSize: 13,
          }}>
            {error}
          </div>
        )}

        <label style={{ display: "block", marginBottom: 12 }}>
          <span style={{ display: "block", marginBottom: 4, fontSize: 13, fontWeight: 600, color: "#444" }}>Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{
              width: "100%", padding: "10px 12px", border: "1px solid #ccc",
              borderRadius: 6, fontSize: 14, boxSizing: "border-box",
            }}
          />
        </label>

        <label style={{ display: "block", marginBottom: 20 }}>
          <span style={{ display: "block", marginBottom: 4, fontSize: 13, fontWeight: 600, color: "#444" }}>Password</span>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{
              width: "100%", padding: "10px 12px", border: "1px solid #ccc",
              borderRadius: 6, fontSize: 14, boxSizing: "border-box",
            }}
          />
        </label>

        <button type="submit" disabled={submitting} style={{
          width: "100%", padding: "10px 0", background: submitting ? "#999" : "#1a73e8",
          color: "#fff", border: "none", borderRadius: 6, fontSize: 15, fontWeight: 600,
          cursor: submitting ? "default" : "pointer",
        }}>
          {submitting ? "Signing in…" : "Sign In"}
        </button>
      </form>
    </div>
  );
}
