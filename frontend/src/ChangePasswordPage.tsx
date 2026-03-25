import { useState, FormEvent } from "react";
import { useAuth, authHeaders } from "./AuthContext";
import { API_BASE } from "./apiConfig";
import { useNavigate } from "react-router-dom";

export default function ChangePasswordPage() {
  const { token, logout } = useAuth();
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (newPassword !== confirmPassword) {
      setError("New passwords do not match");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/change-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to change password");
      }
      setSuccess("Password changed! Redirecting to login…");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setTimeout(() => { logout(); navigate("/login"); }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      maxWidth: 420, margin: "60px auto", padding: "0 16px",
      fontFamily: "sans-serif",
    }}>
      <button
        onClick={() => navigate(-1)}
        style={{
          background: "none", border: "none", color: "#2563eb",
          cursor: "pointer", fontSize: 14, padding: 0, marginBottom: 16,
        }}
      >
        &larr; Back
      </button>

      <div style={{
        background: "#fff", padding: "32px 28px", borderRadius: 12,
        boxShadow: "0 2px 16px rgba(0,0,0,0.1)",
      }}>
        <h2 style={{ margin: "0 0 24px", fontSize: 20, color: "#333" }}>Change Password</h2>

        {error && (
          <div style={{
            background: "#fee", border: "1px solid #fcc", color: "#c33",
            padding: "8px 12px", borderRadius: 6, marginBottom: 16, fontSize: 13,
          }}>
            {error}
          </div>
        )}

        {success && (
          <div style={{
            background: "#efe", border: "1px solid #cfc", color: "#363",
            padding: "8px 12px", borderRadius: 6, marginBottom: 16, fontSize: 13,
          }}>
            {success}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <label style={{ display: "block", marginBottom: 14 }}>
            <span style={{ display: "block", marginBottom: 4, fontSize: 13, fontWeight: 600, color: "#444" }}>
              Current Password
            </span>
            <input
              type="password"
              required
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              style={{
                width: "100%", padding: "10px 12px", border: "1px solid #ccc",
                borderRadius: 6, fontSize: 14, boxSizing: "border-box",
              }}
            />
          </label>

          <label style={{ display: "block", marginBottom: 14 }}>
            <span style={{ display: "block", marginBottom: 4, fontSize: 13, fontWeight: 600, color: "#444" }}>
              New Password
            </span>
            <input
              type="password"
              required
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              style={{
                width: "100%", padding: "10px 12px", border: "1px solid #ccc",
                borderRadius: 6, fontSize: 14, boxSizing: "border-box",
              }}
            />
            <span style={{ display: "block", marginTop: 4, fontSize: 11, color: "#888" }}>
              Min 10 characters, with uppercase, lowercase, and a digit
            </span>
          </label>

          <label style={{ display: "block", marginBottom: 20 }}>
            <span style={{ display: "block", marginBottom: 4, fontSize: 13, fontWeight: 600, color: "#444" }}>
              Confirm New Password
            </span>
            <input
              type="password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              style={{
                width: "100%", padding: "10px 12px", border: "1px solid #ccc",
                borderRadius: 6, fontSize: 14, boxSizing: "border-box",
              }}
            />
          </label>

          <button
            type="submit"
            disabled={submitting}
            style={{
              width: "100%", padding: "12px", background: submitting ? "#93c5fd" : "#2563eb",
              color: "#fff", border: "none", borderRadius: 6, fontSize: 15,
              fontWeight: 600, cursor: submitting ? "not-allowed" : "pointer",
            }}
          >
            {submitting ? "Changing…" : "Change Password"}
          </button>
        </form>
      </div>
    </div>
  );
}
