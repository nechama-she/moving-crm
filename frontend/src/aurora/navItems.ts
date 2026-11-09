import type { IconName } from "./Icon";

export type NavItem = { label: string; to: string; icon: IconName; keywords?: string };
export type NavSection = { label?: string; items: NavItem[] };

// Same pages and role rules as MainNavigation, arranged for the side menu.
export function navSections(role?: string): NavSection[] {
  const admin = role === "admin", dispatch = role === "dispatch", foreman = role === "foreman";
  if (foreman) return [{ items: [{ label: "My jobs", to: "/dispatch", icon: "truck" }, { label: "Settings", to: "/settings", icon: "settings" }] }];
  const work: NavItem[] = [
    ...(!dispatch ? [{ label: "Leads", to: "/", icon: "leads" as const, keywords: "customers directory" }] : []),
    ...(admin ? [
      { label: "Inbox", to: "/chats", icon: "inbox" as const, keywords: "communications messages sms calls" },
      { label: "Work queue", to: "/sales-work-queue", icon: "queue" as const, keywords: "unanswered missed calls follow-ups" },
    ] : []),
  ];
  const sales: NavItem[] = dispatch ? [] : [
    ...(admin ? [{ label: "Pending duplications", to: "/pending-duplications", icon: "duplicate" as const }] : []),
    { label: "Outreach", to: "/outreach", icon: "outreach" },
  ];
  const calendars: NavItem[] = [
    { label: "Sales calendar", to: "/sales-calendar", icon: "calendar" },
    ...(admin ? [{ label: "Meetings", to: "/walkthrough-requests", icon: "meetings" as const, keywords: "walkthrough appointments" }] : []),
    ...(admin || dispatch ? [{ label: "Dispatch", to: "/dispatch", icon: "truck" as const, keywords: "jobs crews" }] : []),
  ];
  const reports: NavItem[] = [
    ...(admin ? [
      { label: "Booking percentage", to: "/reports/booking-percentage", icon: "reports" as const },
      { label: "Stats", to: "/stats", icon: "stats" as const },
    ] : []),
    { label: "Sales performance", to: "/sales-performance", icon: "performance" },
  ];
  const tail: NavItem[] = [
    ...(!dispatch ? [{ label: "Pricing", to: "/pricing", icon: "pricing" as const, keywords: "rates estimate" }] : []),
    { label: "Settings", to: "/settings", icon: "settings" },
  ];
  return [
    { items: work },
    { label: "Sales", items: sales },
    { label: "Calendars", items: calendars },
    { label: "Reports", items: reports },
    { items: tail },
  ].filter(section => section.items.length);
}

export function isActive(pathname: string, to: string) {
  if (to === "/") return pathname === "/" || pathname.startsWith("/leads/");
  if (to === "/settings") return pathname.startsWith("/settings") || ["/admin-users", "/system-users", "/sales-reps", "/dispatch-users", "/foremen", "/assign-period", "/auto-assign-tracker", "/change-password"].includes(pathname);
  return pathname === to || pathname.startsWith(to + "/");
}
