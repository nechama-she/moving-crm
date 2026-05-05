import { Link } from "react-router-dom";
import { useAuth } from "./AuthContext";

export default function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div style={{ padding: "20px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Settings</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Central setup for users, assignment rules, and account preferences.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
        <section style={card}>
          <h2 style={sectionHeader}>User Management</h2>
          <p style={desc}>Create and maintain users who work leads in the CRM.</p>
          <div style={actionsRow}>
            <Link to="/sales-reps" style={primaryLink}>Manage Sales Reps</Link>
          </div>
        </section>

        <section style={card}>
          <h2 style={sectionHeader}>Company Management</h2>
          <p style={desc}>Add, edit, and delete companies with communication and SmartMoving settings.</p>
          <div style={actionsRow}>
            <Link to="/settings/companies" style={primaryLink}>Manage Companies</Link>
          </div>
        </section>

        <section style={card}>
          <h2 style={sectionHeader}>Lead Assignment</h2>
          <p style={desc}>Configure admin unavailability windows and which reps are available during those windows.</p>
          <div style={actionsRow}>
            <Link to="/assign-period" style={primaryLink}>Open Assignment Rules</Link>
            <Link to="/auto-assign-tracker" style={ghostLink}>Open Assignment Tracker</Link>
          </div>
        </section>

        <section style={card}>
          <h2 style={sectionHeader}>Profile & Security</h2>
          <p style={desc}>Manage password and account-level security settings.</p>
          <div style={actionsRow}>
            <Link to="/change-password" style={ghostLink}>Change Password</Link>
          </div>
        </section>
      </div>

      {!isAdmin ? (
        <div style={{ marginTop: 16, border: "1px solid #dddbda", borderRadius: 4, background: "#fff", padding: 12 }}>
          <strong style={{ color: "#ba0517", fontSize: 13 }}>Admin Required:</strong>
          <span style={{ marginLeft: 8, color: "#3e3e3c", fontSize: 13 }}>
            Some setup actions are only available for admin users.
          </span>
        </div>
      ) : null}
    </div>
  );
}

const card: React.CSSProperties = {
  border: "1px solid #dddbda",
  borderRadius: 4,
  background: "#fff",
  padding: 14,
  boxShadow: "0 1px 2px rgba(0,0,0,.06)",
};

const sectionHeader: React.CSSProperties = {
  margin: "0 0 8px",
  fontSize: 13,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "#3e3e3c",
};

const desc: React.CSSProperties = {
  margin: "0 0 12px",
  fontSize: 13,
  color: "#706e6b",
};

const actionsRow: React.CSSProperties = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap",
};

const primaryLink: React.CSSProperties = {
  background: "#0176d3",
  color: "#fff",
  borderRadius: 4,
  padding: "8px 12px",
  textDecoration: "none",
  fontSize: 13,
  fontWeight: 600,
};

const ghostLink: React.CSSProperties = {
  border: "1px solid #0176d3",
  color: "#0176d3",
  borderRadius: 4,
  padding: "7px 11px",
  textDecoration: "none",
  fontSize: 13,
  fontWeight: 600,
  background: "#fff",
};
