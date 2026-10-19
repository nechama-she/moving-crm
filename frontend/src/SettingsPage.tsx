import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "./AuthContext";
import LiveSwitchSettings from "./LiveSwitchSettings";
import "./SettingsPage.css";

type Setting = { label: string; to: string; description: string };
type Group = { title: string; items: Setting[] };
const entry = (label: string, to: string, description: string): Setting => ({ label, to, description });

export default function SettingsPage() {
  const { user } = useAuth();
  const admin = user?.role === "admin";
  const dispatch = user?.role === "dispatch";
  const [search, setSearch] = useState("");
  const groups: Group[] = [
    { title: "Company & pricing", items: [
      ...(admin ? [entry("Companies", "/settings/companies", "Company profiles, communication and SmartMoving settings.")] : []),
      ...(admin || user?.role === "sales_rep" ? [entry("Pricing books", "/pricing", "Rates, exceptions and additional services.")] : []),
      ...(admin ? [
        entry("Inventory catalog", "/settings/inventory-catalog", "Shared items, volume and weight."),
        entry("Moving terms", "/settings/moving-terms", "Restrictions, preparation and customer acknowledgments."),
      ] : []),
    ] },
    { title: "Team & access", items: [
      ...(admin ? [
        entry("Admin users", "/admin-users", "Manage administrators."),
        entry("System users", "/system-users", "Manage system accounts."),
        entry("Sales reps", "/sales-reps", "Manage your sales team."),
        entry("Dispatch users", "/dispatch-users", "Manage dispatch access."),
      ] : []),
      ...(admin || dispatch ? [
        entry("Foremen", "/foremen", "Manage foremen and company access."),
        entry(dispatch ? "View as foreman" : "View as user", "/settings/impersonate", "Check another user's CRM experience."),
      ] : []),
      ...(admin ? [entry("Access history", "/settings/access-history", "Review logins and activity logs.")] : []),
    ] },
    { title: "Lead rules & assignment", items: admin ? [
      entry("Assignment rules", "/assign-period", "Rep availability and admin unavailability windows."),
      entry("Assignment tracker", "/auto-assign-tracker", "Review automatic lead assignments."),
      entry("Duplication rules", "/settings/duplication-rules", "Configure lead duplication."),
    ] : [] },
    { title: "Communication", items: admin ? [
      entry("SMS templates", "/settings/templates", "Welcome, assignment and follow-up messages."),
      entry("Ignored numbers", "/settings/ignored-call-numbers", "Exclude numbers from the sales work queue."),
    ] : [] },
    { title: "My account", items: [
      entry("Change password", "/change-password", "Update your account password."),
    ] },
  ];
  const query = search.trim().toLowerCase();
  const filtered = groups.map(group => ({ ...group, items: group.items.filter(item =>
    [group.title, item.label, item.description].join(" ").toLowerCase().includes(query)
  ) })).filter(group => group.items.length);
  const showIntegrations = admin && "integrations liveswitch virtual estimates video spark".includes(query);
  return <div className="settings-hub">
    <header className="settings-hub-header">
      <div><h1>Settings</h1><p>Manage your business, team and account.</p></div>
      <label className="settings-search">Find a setting
        <input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search settings" />
      </label>
    </header>
    <div className="settings-groups">
      {filtered.map(group => <section className="settings-group" key={group.title}>
        <h2>{group.title}</h2>
        {group.items.map(item => <Link to={item.to} key={item.to} className="settings-entry">
          <span><strong>{item.label}</strong><small>{item.description}</small></span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true" style={{ flexShrink: 0 }}><path d="m9 5 7 7-7 7" /></svg>
        </Link>)}
      </section>)}
    </div>
    {showIntegrations && <section className="settings-integrations">
      <h2>Integrations</h2>
      <details><summary>LiveSwitch: Virtual estimates</summary><LiveSwitchSettings /></details>
    </section>}
    {!filtered.length && !showIntegrations && <p role="status">No settings match &quot;{search}&quot;. Try another search.</p>}
  </div>;
}
