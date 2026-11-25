// The browser tab's title: the page's name, then the app's. The one place page names for the tab are kept.
const APP = 'Moving CRM';

const TITLES: Record<string, string> = {
  '/': 'Leads',
  '/chats': 'Inbox',
  '/sales-work-queue': 'Work queue',
  '/reports/booking-percentage': 'Booking percentage',
  '/reports/customer-page-bookings': 'Customer page bookings',
  '/walkthrough-requests': 'Meetings',
  '/stats': 'Stats',
  '/outreach': 'Outreach',
  '/sales-calendar': 'Sales calendar',
  '/sales-performance': 'Sales performance',
  '/assign-period': 'Assignment rules',
  '/sales-reps': 'Sales reps',
  '/admin-users': 'Admin users',
  '/system-users': 'System users',
  '/dispatch': 'Dispatch',
  '/dispatch-users': 'Dispatch users',
  '/foremen': 'Foremen',
  '/settings': 'Settings',
  '/settings/companies': 'Companies',
  '/settings/documents': 'Documents',
  '/settings/inventory-catalog': 'Inventory catalog',
  '/settings/moving-terms': 'Moving terms',
  '/settings/templates': 'Automated SMS templates',
  '/settings/email-templates': 'Automated email templates',
  '/settings/message-templates': 'Message templates',
  '/pending-duplications': 'Pending duplications',
  '/settings/duplication-rules': 'Duplication rules',
  '/settings/ignored-call-numbers': 'Ignored numbers',
  '/settings/impersonate': 'View as user',
  '/settings/access-history': 'Access history',
  '/pricing': 'Pricing',
  '/auto-assign-tracker': 'Assignment tracker',
  '/change-password': 'Change password',
};

// The page's name for a path: a lead's page is "Lead" until it names its client.
export function pageName(pathname: string): string {
  const path = pathname.replace(/\/+$/, '') || '/';
  return TITLES[path] ?? (path.startsWith('/leads/') ? 'Lead' : '');
}

export function setPageTitle(name: string) {
  document.title = name ? `${name} · ${APP}` : APP;
}
