import { useState, FormEvent } from "react";
import { useAuth, authHeaders } from "./AuthContext";
import { API_BASE } from "./apiConfig";
import { useNavigate } from "react-router-dom";

export default function ChangePasswordPage() {
  const { token, logout, user } = useAuth();
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
    <div style={{ padding: "40px 24px", maxWidth: 460, margin: "0 auto" }}>
      <button
        onClick={() => navigate(-1)}
        style={{
          background: "none", border: "none", color: "#0176d3",
          cursor: "pointer", fontSize: 14, padding: 0, marginBottom: 20, fontWeight: 500,
        }}
      >
        ← Back
      </button>

      <div style={{
        background: "#fff", padding: "28px 28px 24px", borderRadius: 8,
        boxShadow: "0 2px 4px rgba(0,0,0,0.1)", border: "1px solid #dddbda",
      }}>
        <h2 style={{ margin: "0 0 20px", fontSize: 18, color: "#032d60" }}>Change Password</h2>

        {user?.must_change_password ? (
          <div style={{
            background: "#eef4ff", border: "1px solid #bfd6ff", color: "#032d60",
            padding: "8px 12px", borderRadius: 4, marginBottom: 16, fontSize: 13,
          }}>
            You must change your temporary password before using the CRM.
          </div>
        ) : null}

        {error && (
          <div style={{
            background: "#fef3f2", border: "1px solid #f9b9b5", color: "#ba0517",
            padding: "8px 12px", borderRadius: 4, marginBottom: 16, fontSize: 13,
          }}>
            {error}
          </div>
        )}

        {success && (
          <div style={{
            background: "#f2fbf3", border: "1px solid #a0d9a8", color: "#2e844a",
            padding: "8px 12px", borderRadius: 4, marginBottom: 16, fontSize: 13,
          }}>
            {success}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {[
            { label: "Current Password", value: currentPassword, setter: setCurrentPassword, hint: "" },
            { label: "New Password", value: newPassword, setter: setNewPassword, hint: "Min 10 characters, with uppercase, lowercase, and a digit" },
            { label: "Confirm New Password", value: confirmPassword, setter: setConfirmPassword, hint: "" },
          ].map(({ label, value, setter, hint }) => (
            <label key={label} style={{ display: "block", marginBottom: 16 }}>
              <span style={{ display: "block", marginBottom: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
                {label}
              </span>
              <input
                type="password"
                required
                value={value}
                onChange={(e) => setter(e.target.value)}
                style={{
                  width: "100%", padding: "9px 12px", border: "1px solid #dddbda",
                  borderRadius: 4, fontSize: 14, boxSizing: "border-box", background: "#fff",
                }}
              />
              {hint && <span style={{ display: "block", marginTop: 4, fontSize: 11, color: "#706e6b" }}>{hint}</span>}
            </label>
          ))}

          <button
            type="submit"
            disabled={submitting}
            style={{
              width: "100%", padding: "10px", background: submitting ? "#5a9fd4" : "#0176d3",
              color: "#fff", border: "none", borderRadius: 4, fontSize: 14,
              fontWeight: 600, cursor: submitting ? "not-allowed" : "pointer",
              marginTop: 4,
            }}
          >
            {submitting ? "Changing…" : "Change Password"}
          </button>
        </form>
      </div>
    </div>
  );
}
