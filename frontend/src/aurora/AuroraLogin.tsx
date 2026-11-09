import "./aurora.css";
import "./aurora-dark.css";
import { FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import Icon from "./Icon";
import { useTheme } from "./theme";

export default function AuroraLogin() {
  const { login, token } = useAuth();
  useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string })?.from || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const demo = import.meta.env.MODE === "demo";

  async function submit(e: FormEvent) {
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
  }

  if (token) return <Navigate to={from} replace />;

  return (
    <div className="aurora aur-login">
      <section className="aur-login-brand" aria-hidden="true">
        <div className="aur-login-logo"><span className="aur-brand-mark"><Icon name="truck" size={22} /></span><strong>Moving CRM</strong></div>
        <div className="aur-login-pitch">
          <h2>Every lead, message and move in one calm place.</h2>
          <p>Search anything with Ctrl K, ask the CRM a question, and see what needs you first.</p>
        </div>
        <div className="aur-login-cards">
          <div className="aur-login-card"><span>Today's new leads</span><strong>At a glance</strong></div>
          <div className="aur-login-card"><span>Customers waiting for a reply</span><strong>First</strong></div>
          <div className="aur-login-card"><Icon name="inbox" size={14} /><span>Every channel in one inbox</span></div>
        </div>
      </section>

      <main className="aur-login-main">
        <form className="aur-login-form" onSubmit={submit}>
          <h1>Sign in</h1>
          <p className="aur-muted">Welcome back. Sign in to your workspace.</p>
          {demo && <p className="aur-login-demo">Demo mode: any email and password will work. All data is invented.</p>}
          {error && <div className="aur-alert" role="alert">{error}</div>}
          <label className="aur-field">
            <span>Email</span>
            <input type="email" required autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} />
          </label>
          <label className="aur-field">
            <span>Password</span>
            <input type="password" required autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} />
          </label>
          <button type="submit" className="aur-btn is-primary aur-login-submit" disabled={submitting}>{submitting ? "Signing in…" : "Sign in"}</button>
        </form>
      </main>
    </div>
  );
}
