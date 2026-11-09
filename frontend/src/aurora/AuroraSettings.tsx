// Settings hub for the new look: the same entries and role rules as SettingsPage, shown as icon tiles.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../AuthContext";
import LiveSwitchSettings from "../LiveSwitchSettings";
import Icon, { type IconName } from "./Icon";

type Tone = "blue" | "violet" | "amber" | "green";
type Setting = { label: string; to?: string; description: string; icon: IconName };
type Group = { title: string; tone: Tone; items: Setting[] };
const entry = (label: string, to: string, description: string, icon: IconName): Setting => ({ label, to, description, icon });

export default function AuroraSettings() {
  const { user } = useAuth();
  const admin = user?.role === "admin";
  const dispatch = user?.role === "dispatch";
  const [search, setSearch] = useState("");
  const [integrationOpen, setIntegrationOpen] = useState(false);

  useEffect(() => {
    if (!integrationOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setIntegrationOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [integrationOpen]);

  // "Change password" is left out: the new look has it in the sidebar footer.
  const groups: Group[] = [
    { title: "Company & pricing", tone: "blue", items: [
      ...(admin ? [entry("Companies", "/settings/companies", "Company profiles, communication and SmartMoving settings.", "building")] : []),
      ...(admin || user?.role === "sales_rep" ? [entry("Pricing books", "/pricing", "Rates, exceptions and additional services.", "pricing")] : []),
      ...(admin ? [
        entry("Inventory catalog", "/settings/inventory-catalog", "Shared items, volume and weight.", "box"),
        entry("Moving terms", "/settings/moving-terms", "Restrictions, preparation and customer acknowledgments.", "terms"),
        entry("Documents", "/settings/documents", "Company estimate documents, formatting and links.", "document"),
      ] : []),
    ] },
    { title: "Team & access", tone: "violet", items: [
      ...(admin ? [
        entry("Admin users", "/admin-users", "Manage administrators.", "shield"),
        entry("System users", "/system-users", "Manage system accounts.", "monitor"),
        entry("Sales reps", "/sales-reps", "Manage your sales team.", "leads"),
        entry("Dispatch users", "/dispatch-users", "Manage dispatch access.", "truck"),
      ] : []),
      ...(admin || dispatch ? [
        entry("Foremen", "/foremen", "Manage foremen and company access.", "hardhat"),
        entry(dispatch ? "View as foreman" : "View as user", "/settings/impersonate", "Check another user's CRM experience.", "eye"),
      ] : []),
      ...(admin ? [entry("Access history", "/settings/access-history", "Review logins and activity logs.", "history")] : []),
    ] },
    { title: "Lead rules & assignment", tone: "amber", items: admin ? [
      entry("Assignment rules", "/assign-period", "Rep availability and admin unavailability windows.", "rules"),
      entry("Assignment tracker", "/auto-assign-tracker", "Review automatic lead assignments.", "tracker"),
      entry("Duplication rules", "/settings/duplication-rules", "Configure lead duplication.", "duplicate"),
    ] : [] },
    { title: "Communication & integrations", tone: "green", items: admin ? [
      entry("SMS templates", "/settings/templates", "Welcome, assignment and follow-up messages.", "template"),
      entry("Ignored numbers", "/settings/ignored-call-numbers", "Exclude numbers from the sales work queue.", "block"),
      { label: "LiveSwitch", description: "Virtual estimates over video.", icon: "video" },
    ] : [] },
  ];

  const query = search.trim().toLowerCase();
  const filtered = groups.map(group => ({ ...group, items: group.items.filter(item =>
    [group.title, item.label, item.description, item.to ? "" : "integrations virtual estimates video spark"].join(" ").toLowerCase().includes(query)
  ) })).filter(group => group.items.length);

  const tile = (item: Setting, tone: Tone) => {
    const body = <>
      <span className={`aur-set-icon is-${tone}`}><Icon name={item.icon} size={20} /></span>
      <span className="aur-set-text"><strong>{item.label}</strong><small>{item.description}</small></span>
      <span className="aur-set-go"><Icon name="chevron" size={16} /></span>
    </>;
    return item.to
      ? <Link to={item.to} key={item.label} className="aur-set-tile">{body}</Link>
      : <button type="button" key={item.label} className="aur-set-tile" onClick={() => setIntegrationOpen(true)}>{body}</button>;
  };

  return (
    <div className="aur-page aur-settings">
      <header className="aur-page-head">
        <div>
          <span className="aur-eyebrow">Workspace</span>
          <h1>Settings</h1>
          <p className="aur-muted">Manage your business, team and integrations.</p>
        </div>
      </header>

      <label className="aur-searchbox aur-set-search">
        <Icon name="search" size={16} />
        <input type="search" aria-label="Search settings" placeholder="Search settings, e.g. templates, foremen, pricing" value={search} onChange={e => setSearch(e.target.value)} autoFocus />
      </label>

      {filtered.map(group => (
        <section className="aur-set-group" key={group.title} aria-label={group.title}>
          <h2>{group.title} <span>{group.items.length}</span></h2>
          <div className="aur-set-grid">{group.items.map(item => tile(item, group.tone))}</div>
        </section>
      ))}

      {!filtered.length && <p className="aur-muted" role="status">No settings match &quot;{search}&quot;. Try another search.</p>}

      {integrationOpen && (
        <div className="aur-sheet-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setIntegrationOpen(false); }}>
          <aside className="aur-sheet" role="dialog" aria-modal="true" aria-label="LiveSwitch settings">
            <div className="aur-sheet-head">
              <span className="aur-set-icon is-green"><Icon name="video" size={20} /></span>
              <div><strong>LiveSwitch</strong><small className="aur-muted">Virtual estimates</small></div>
              <button type="button" className="aur-icon-btn" aria-label="Close" onClick={() => setIntegrationOpen(false)}><Icon name="close" size={16} /></button>
            </div>
            <div className="aur-sheet-body"><LiveSwitchSettings /></div>
          </aside>
        </div>
      )}
    </div>
  );
}
