import { useEffect, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import './MainNavigation.css';

type Item = { label: string; to: string };
type Group = { label: string; items: Item[] };
const item = (label: string, to: string): Item => ({ label, to });

export default function MainNavigation({ role, mobile = false }: { role?: string; mobile?: boolean }) {
  const { pathname } = useLocation();
  const [open, setOpen] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => setOpen(null), [pathname]);
  useEffect(() => {
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(null); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, []);
  const admin = role === 'admin', dispatch = role === 'dispatch', foreman = role === 'foreman';
  const groups: Group[] = foreman ? [] : [
    ...(!dispatch ? [{ label: 'Sales', items: [
      ...(admin ? [item('Communications', '/chats'), item('Sales Work Queue', '/sales-work-queue')] : []),
      item('Outreach', '/outreach'), item('Pricing', '/pricing'),
    ] }] : []),
    { label: 'Scheduling', items: [
      item('Sales Calendar', '/sales-calendar'),
      ...(admin ? [item('Schedule Meetings', '/walkthrough-requests')] : []),
      ...(admin || dispatch ? [item('Dispatch Calendar', '/dispatch')] : []),
    ] },
    { label: 'Reports', items: [
      ...(admin ? [item('Booking Percentage', '/reports/booking-percentage'), item('Stats', '/stats')] : []),
      item('Sales Performance', '/sales-performance'),
    ] },
  ];
  const active = (to: string) => pathname === to || (to !== '/' && pathname.startsWith(to + '/'));
  const link = (entry: Item) => <NavLink key={entry.to} to={entry.to} end={entry.to === '/'} onClick={() => setOpen(null)}>{entry.label}</NavLink>;
  return <div ref={root} className={`grouped-navigation ${mobile ? 'grouped-navigation-mobile' : ''}`} onKeyDown={event => {
    if (event.key === 'Escape') { root.current?.querySelector<HTMLButtonElement>('[aria-expanded="true"]')?.focus(); setOpen(null); }
  }}>
    {!dispatch && link(foreman ? item('My Jobs', '/dispatch') : item('Leads', '/'))}
    {groups.map(group => <div className="navigation-group" key={group.label}>
      {mobile ? <h3>{group.label}</h3> : <button type="button" className={group.items.some(entry => active(entry.to)) ? 'active' : ''} aria-expanded={open === group.label} aria-controls={`navigation-${group.label}`} onClick={() => setOpen(open === group.label ? null : group.label)}>{group.label}<span aria-hidden="true">⌄</span></button>}
      {(mobile || open === group.label) && <div id={mobile ? undefined : `navigation-${group.label}`} className="navigation-group-links">{group.items.map(link)}</div>}
    </div>)}
    {link(item('Settings', '/settings'))}
  </div>;
}
