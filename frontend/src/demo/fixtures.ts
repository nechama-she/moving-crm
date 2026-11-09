// Invented sample data for local demo mode (npm run dev:demo). No real customers.
import type { Lead } from "../leadUtils";

export const demoUser = { id: "u-maya", email: "demo@example.com", name: "Maya Rosen", role: "admin", must_change_password: false };

export const demoCompanies = [
  { id: "c-top", name: "Top Tier Van Lines" },
  { id: "c-gorilla", name: "Gorilla Haulers" },
  { id: "c-wilson", name: "Wilson Bros Van Lines" },
  { id: "c-m95", name: "Movers 95" },
];

export const demoReps = [
  { id: "u-sara", name: "Sara Levi", role: "sales_rep" },
  { id: "u-dan", name: "Dan Kerr", role: "sales_rep" },
  { id: "u-avi", name: "Avi Ben-Ami", role: "sales_rep" },
  { id: "u-maya", name: "Maya Rosen", role: "admin" },
];

const first = ["Rachel", "Daniel", "Priya", "Grace", "Marcus", "Hannah", "Leo", "Olivia", "Noah", "Ethan", "Mia", "Jonah", "Ava", "Lucas", "Chloe", "Isaac", "Nora", "Owen", "Zoe", "Eli"];
const last = ["Moreno", "Ortiz", "Natarajan", "Whitfield", "Bell", "Cole", "Fischer", "Grant", "Kim", "Brooks", "Laurent", "Weiss", "Turner", "Park", "Hayes", "Romero", "Bishop", "Quinn", "Foster", "Shaw"];
const places = [
  "Oxon Hill, MD 20745", "Englewood, CO 80110", "Rockville, MD 20852", "Raleigh, NC 27601", "Leland, NC 28451",
  "Mount Sinai, NY 11766", "Naples, FL 34120", "Cheraw, SC 29520", "Glen Burnie, MD 21060", "Brooklyn, NY 11201",
  "Lakeland, FL 33801", "Chicago, IL 60614", "Columbus, OH 43215", "Silver Spring, MD 20910", "Arlington, VA 22201",
  "Denver, CO 80202", "Austin, TX 78701", "Atlanta, GA 30303", "Boston, MA 02108", "Miami, FL 33130",
];
const sizes = ["Studio", "1 Bedroom", "2 Bedrooms", "3 Bedrooms", "4 Bedrooms", "Room or Less", "Storage Unit"];
const statuses = ["new", "new", "contacted", "quoted", "quoted", "quoted", "booked", "scheduled", "completed", "lost"];

function seeded(seed: number) {
  let s = seed;
  return () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
}

function isoDaysFromNow(days: number, hour = 12) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(hour, (days * 7) % 60, 0, 0);
  return d.toISOString();
}

export function buildDemoLeads(count = 64): Lead[] {
  const rand = seeded(42);
  const leads: Lead[] = [];
  for (let i = 0; i < count; i += 1) {
    const company = demoCompanies[Math.floor(rand() * demoCompanies.length)];
    const rep = rand() < 0.15 ? null : demoReps[Math.floor(rand() * demoReps.length)];
    const status = statuses[Math.floor(rand() * statuses.length)];
    const name = `${first[i % first.length]} ${last[(i * 7) % last.length]}`;
    const pickup = places[Math.floor(rand() * places.length)];
    let delivery = places[Math.floor(rand() * places.length)];
    if (delivery === pickup) delivery = places[(places.indexOf(pickup) + 3) % places.length];
    const createdHoursAgo = i < 6 ? i * 0.4 : Math.floor(rand() * 24 * 25);
    const created = new Date(Date.now() - createdHoursAgo * 3600 * 1000).toISOString();
    const moveIn = Math.floor(rand() * 120) - 5;
    const quoted = ["quoted", "booked", "scheduled", "completed"].includes(status);
    const total = quoted ? Math.round((800 + rand() * 9200) / 10) * 10 : 0;
    leads.push({
      id: `lead-${48200 + i}`,
      leadgen_id: String(910000 + i * 13),
      company_id: company.id,
      company_name: company.name,
      assigned_to: rep?.id || "",
      assigned_to_name: rep?.name || "",
      full_name: name,
      email: `${name.toLowerCase().replace(/[^a-z]+/g, ".")}@example.com`,
      phone_number: `555${String(1000000 + Math.floor(rand() * 8999999)).slice(0, 7)}`,
      pickup_zip: pickup,
      delivery_zip: delivery,
      move_size: sizes[Math.floor(rand() * sizes.length)],
      "when_is_the_move?": isoDaysFromNow(moveIn).slice(0, 10),
      move_type: pickup.slice(-8, -6) === delivery.slice(-8, -6) ? "local" : "long_distance",
      status,
      priority: rand() < 0.3 ? 1 : 0,
      source: ["website", "facebook", "messenger", "referral"][Math.floor(rand() * 4)],
      created_time: created,
      created_at: created,
      smartmoving_id: quoted ? `sm-${100000 + i}` : "",
      estimatedTotal: quoted ? { subtotal: total, taxableAmount: 0, tax: 0, finalTotal: total } : null,
      payments: [],
      notes: "",
    });
  }
  return leads;
}

export const demoLeads = buildDemoLeads();

// Invented background volume on top of the demo rows, split by status like a real month, so a status
// filter (the Leads funnel asks per status) changes the numbers the way the server does.
const STATUS_SHARE: Record<string, number> = { new: 0.2, contacted: 0.19, quoted: 0.24, booked: 0.11, scheduled: 0.07, completed: 0.05, lost: 0.12, cancelled: 0.02 };

export function demoSummary(leads: Lead[], status = "") {
  const share = status ? STATUS_SHARE[status] ?? 0 : 1;
  const dayStart = new Date(); dayStart.setHours(0, 0, 0, 0);
  const monthStart = new Date(); monthStart.setDate(1); monthStart.setHours(0, 0, 0, 0);
  const created = (l: Lead) => new Date(String(l.created_time));
  const total = (l: Lead) => Number((l.estimatedTotal as { finalTotal?: number } | null)?.finalTotal || 0);
  const inMonth = leads.filter(l => created(l) >= monthStart);
  // Same shape as the server: daily series for the month and the same period one month earlier.
  const days = new Date().getDate();
  const wave = (base: number, amp: number, seed: number) => Array.from({ length: days }, (_, i) => Math.max(0, Math.round(base + amp * Math.sin((i + seed) / 2.3) + ((i * 7 + seed) % 5) - 2)));
  const trend = {
    new_leads: wave(32, 9, 1), quotes: wave(11, 4, 3),
    quote_value: wave(11, 4, 3).map((q, i) => q * (2600 + ((i * 37) % 900))),
    booked_value: wave(3, 2, 5).map((b, i) => b * (2100 + ((i * 53) % 1400))),
  };
  return {
    previous: { new_today: 25, new_month: 840, quotes: 289, quote_value: 912000, booked_value: 214000 },
    trend,
    new_today: leads.filter(l => created(l) >= dayStart).length + 29,
    new_month: inMonth.length + Math.round(900 * share),
    quotes: inMonth.filter(l => l.status === "quoted").length + 290,
    quote_value: inMonth.filter(l => l.status === "quoted").reduce((s, l) => s + total(l), 0) + 880000,
    booked_value: inMonth.filter(l => ["booked", "scheduled", "completed"].includes(String(l.status))).reduce((s, l) => s + total(l), 0) + 170000,
  };
}
