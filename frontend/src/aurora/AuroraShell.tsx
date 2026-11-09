import "./aurora.css";
import "./aurora-theme.css";
import "./aurora-dark-pages.css";
import "./aurora-dark.css";
import { MouseEvent, ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import CommandPalette from "./CommandPalette";
import { initials } from "./initials";
import Icon from "./Icon";
import { revealPage, slideHighlight, withViewTransition } from "./motion";
import { isActive, navSections } from "./navItems";
import { useTheme } from "./theme";
import { setUiMode } from "./uiMode";

const COLLAPSE_KEY = "crm-aurora-collapsed";
// Pages whose tables become one card per row on phones (aurora.css), instead of scrolling sideways.
const CARD_TABLE_PAGES = new Set(["sales-work-queue"]);

export default function AuroraShell({ children, banner }: { children: ReactNode; banner?: ReactNode }) {
  const { user, logout, isImpersonating } = useAuth();
  const { pathname } = useLocation();
  const sections = useMemo(() => navSections(user?.role), [user?.role]);
  const pages = useMemo(() => sections.flatMap(s => s.items), [sections]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [theme, setTheme] = useTheme();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; } });
  const navRef = useRef<HTMLDivElement>(null);
  const highlightRef = useRef<HTMLSpanElement>(null);
  const placedPath = useRef("");
  // The highlight slides to the active link on navigation; on first paint, collapse or resize it just moves there.
  useLayoutEffect(() => {
    const nav = navRef.current, highlight = highlightRef.current;
    if (!nav || !highlight) return;
    const place = (animate: boolean) => slideHighlight(highlight, nav.querySelector<HTMLElement>(".aur-nav-link.is-active"), animate);
    place(placedPath.current !== "" && placedPath.current !== pathname);
    placedPath.current = pathname;
    let size = `${nav.clientWidth}x${nav.clientHeight}`;
    const observer = new ResizeObserver(() => {
      const next = `${nav.clientWidth}x${nav.clientHeight}`;
      if (next !== size) { size = next; place(false); }
    });
    observer.observe(nav);
    return () => observer.disconnect();
  }, [pathname, collapsed, sections]);
  // Sidebar navigation runs as a page transition: the page fades out and the new one rises in (aurora.css).
  function goTo(event: MouseEvent<HTMLAnchorElement>, to: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || to === pathname) return;
    event.preventDefault();
    withViewTransition("page", () => navigate(to));
  }

  useEffect(() => setMobileOpen(false), [pathname]);
  const mainRef = useRef<HTMLDivElement>(null);
  const page = pathname.split("/")[1] || "leads";
  // Each page builds itself in when it opens (motion.ts).
  useLayoutEffect(() => (mainRef.current ? revealPage(mainRef.current) : undefined), [pathname]);
  // Card rows show each value beside its column name, so copy the header text onto every cell.
  useEffect(() => {
    const main = mainRef.current;
    if (!main || !CARD_TABLE_PAGES.has(page)) return;
    const label = () => main.querySelectorAll("table").forEach(table => {
      const heads = [...table.querySelectorAll("thead th")].map(th => th.textContent?.trim() || "");
      table.querySelectorAll("tbody tr").forEach(row => [...row.children].forEach((cell, i) => {
        if (heads[i] && (cell as HTMLTableCellElement).colSpan === 1 && cell.getAttribute("data-label") !== heads[i]) cell.setAttribute("data-label", heads[i]);
      }));
    });
    label();
    const observer = new MutationObserver(label);
    observer.observe(main, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [page]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen(open => !open); }
      // "/" also opens search, as in the classic header, unless the person is typing.
      const target = e.target as HTMLElement | null;
      const typing = !!target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
      if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); setPaletteOpen(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function toggleCollapsed() {
    setCollapsed(c => { const next = !c; try { localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0"); } catch { /* ignore */ } return next; });
  }

  const current = pages.find(p => isActive(pathname, p.to));

  return (
    <div className={`aurora aur-shell${collapsed ? " is-collapsed" : ""}${mobileOpen ? " is-menu-open" : ""}`}>
      <header className="aur-mobilebar">
        <button type="button" className="aur-icon-btn" aria-label="Open menu" aria-expanded={mobileOpen} onClick={() => setMobileOpen(true)}><Icon name="menu" /></button>
        <span className="aur-mobilebar-title">{current?.label || "Moving CRM"}</span>
        <button type="button" className="aur-icon-btn" aria-label="Search or ask" onClick={() => setPaletteOpen(true)}><Icon name="search" /></button>
      </header>
      {mobileOpen && <button type="button" className="aur-scrim" aria-label="Close menu" onClick={() => setMobileOpen(false)} />}

      <nav className="aur-sidebar" aria-label="Main">
        <div className="aur-brand">
          <span className="aur-brand-mark"><Icon name="truck" size={20} /></span>
          <span className="aur-brand-text"><strong>Moving CRM</strong><small>All companies</small></span>
          <button type="button" className="aur-icon-btn aur-collapse" aria-label={collapsed ? "Expand menu" : "Collapse menu"} onClick={toggleCollapsed}><Icon name="collapse" size={16} /></button>
        </div>

        <button type="button" className="aur-search" onClick={() => setPaletteOpen(true)}>
          <Icon name="search" size={16} /><span>{"Search leads…"}</span><kbd>Ctrl K</kbd>
        </button>

        <div className="aur-nav has-highlight" ref={navRef}>
          <span className="aur-nav-highlight" ref={highlightRef} aria-hidden="true" />
          {sections.map((section, i) => (
            <div className="aur-nav-section" key={section.label || i}>
              {section.label && <span className="aur-nav-heading">{section.label}</span>}
              {section.items.map(item => (
                <NavLink key={item.to} to={item.to} end={item.to === "/"} title={collapsed ? item.label : undefined}
                  className={() => `aur-nav-link${isActive(pathname, item.to) ? " is-active" : ""}`} onClick={event => goTo(event, item.to)}>
                  <Icon name={item.icon} /><span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </div>

        <div className="aur-sidebar-foot">
          <div className="aur-foot-row">
            <button type="button" className="aur-look-switch" onClick={() => setUiMode("classic")}>
              <Icon name="swap" size={16} /><span>Switch to classic look</span>
            </button>
            <button type="button" className="aur-theme-btn" aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Light mode" : "Dark mode"} onClick={event => setTheme(theme === "dark" ? "light" : "dark", event.currentTarget)}>
              <Icon name={theme === "dark" ? "sun" : "moon"} size={16} />
            </button>
          </div>
          <div className="aur-user">
            <span className="aur-avatar">{initials(user?.name || "")}</span>
            <span className="aur-user-text"><strong>{user?.name}</strong><small>{user?.role?.replace("_", " ")}</small></span>
          </div>
          <div className="aur-user-actions">
            {user?.role !== "dispatch" && !isImpersonating && <NavLink to="/change-password" className="aur-text-btn"><Icon name="key" size={15} /><span>Password</span></NavLink>}
            <button type="button" className="aur-text-btn" onClick={logout}><Icon name="logout" size={15} /><span>Sign out</span></button>
          </div>
        </div>
      </nav>

      <div className="aur-main" ref={mainRef} data-page={page}>
        {banner}
        {children}
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} pages={pages} />
    </div>
  );
}
