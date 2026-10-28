// Recently opened leads for the global search, kept per user in this browser only.
export type RecentLead = {
  id: string;
  full_name?: string;
  status?: string;
  phone_number?: string;
  email?: string;
  company_name?: string;
  quote_number?: string;
};

const MAX_RECENT = 6;
const storageKey = (userId: string) => `recentLeads:${userId}`;

export function readRecentLeads(userId: string | undefined): RecentLead[] {
  if (!userId) return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(userId)) || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item.id === "string") : [];
  } catch {
    return [];
  }
}

export function rememberRecentLead(userId: string | undefined, lead: RecentLead) {
  if (!userId || !lead.id) return;
  const entry: RecentLead = {
    id: lead.id,
    full_name: lead.full_name,
    status: lead.status,
    phone_number: lead.phone_number,
    email: lead.email,
    company_name: lead.company_name,
    quote_number: lead.quote_number,
  };
  const next = [entry, ...readRecentLeads(userId).filter((item) => item.id !== lead.id)].slice(0, MAX_RECENT);
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(next));
  } catch {
    // Storage unavailable; recent leads are a convenience only.
  }
}

export function forgetRecentLead(userId: string | undefined, leadId: string) {
  if (!userId) return;
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(readRecentLeads(userId).filter((item) => item.id !== leadId)));
  } catch {
    // Storage unavailable.
  }
}
