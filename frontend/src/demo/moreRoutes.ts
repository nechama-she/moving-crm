// Demo answers for communications, the work queue, calendars and meetings. Invented data only.
import type { Lead } from "../leadUtils";
import { demoCompanies, demoReps } from "./fixtures";

const now = () => Math.floor(Date.now() / 1000);
const companyPhone: Record<string, string> = { "c-top": "5550105939", "c-gorilla": "5550192625", "c-wilson": "5550136786", "c-m95": "5550178230" };
const iso = (sec: number) => new Date(sec * 1000).toISOString();

const SCRIPTS = [
  ["Hi! Can you hold our things one extra day? We close on the condo Tuesday.", "Yes, we can store everything overnight. It's $95 for the extra day.", "Perfect, please add it."],
  ["Is the truck still on schedule for tomorrow?", "Yes, the crew arrives between 8 and 9 AM.", "Great, thank you!"],
  ["Can I get a price for a 2 bedroom move to Raleigh?", "Of course. Do you have a date in mind?", "Mid November, flexible by a few days."],
  ["Do you also do packing?", "We do: full packing or just fragile items.", "Just the kitchen, please."],
  ["We need to change the delivery address.", "No problem, what is the new address?"],
];

export function buildConversations(leads: Lead[]) {
  const base = now();
  const conversations = leads.slice(0, 14).map((lead, i) => {
    const client = String(lead.phone_number || `555010${1000 + i}`);
    const companyNumber = companyPhone[String(lead.company_id)] || "5550100000";
    const script = SCRIPTS[i % SCRIPTS.length];
    const start = base - (i * 47 + 12) * 60;
    const messages = script.map((text, j) => ({
      message_id: `${lead.id}-m${j}`,
      text,
      direction: j % 2 === 0 ? "inbound" : "outbound",
      timestamp: start - (script.length - 1 - j) * 22 * 60 - (i % 3) * 86400,
      platform: i % 5 === 3 ? "messenger" : "sms",
      phone_number: client,
      role: j % 2 === 0 ? "user" : "agent",
    }));
    const calls = i % 3 === 1 ? [
      { message_id: `${lead.id}-c0`, direction: "inbound", answered: false, timestamp: start - 3 * 3600 },
      { message_id: `${lead.id}-c1`, direction: "outbound", answered: true, timestamp: start - 3 * 3600 + 7 * 60 },
    ] : [];
    return { lead, client, companyNumber, messages, calls, platform: messages[0].platform };
  });
  return conversations;
}

// The website chat bot on gorillahaulers.com: one chat that made a lead, one visitor without a lead.
// Messages are in the conversations table's shape; lead_id appears once the chat sent the request.
const WEBSITE_BOT = "website_gorillah_bot";
type WebsiteMessage = { user_id: string; timestamp: number; message_id: string; text: string; platform: string; page_id: string; role: string; record_type: string; lead_id?: string };

export function buildWebsiteChats(leads: Lead[]) {
  // A Gorilla Haulers 2-bedroom lead, so the chat matches the lead's details.
  const lead = leads.find(l => l.company_id === "c-gorilla" && l.move_size === "2 Bedrooms")
    || leads.find(l => l.move_size === "2 Bedrooms") || leads[20];
  const moveDate = new Date(`${String(lead["when_is_the_move?"] || "")}T12:00:00`);
  const when = Number.isNaN(moveDate.getTime()) ? "next month" : moveDate.toLocaleDateString("en-US", { month: "long", day: "numeric" });
  const chat = (userId: string, start: number, lines: Array<[string, string]>, leadFrom = Infinity): WebsiteMessage[] =>
    lines.map(([role, text], j) => ({
      user_id: userId, timestamp: start + j * 90_000, message_id: `${userId}-${j}`, text, platform: WEBSITE_BOT,
      page_id: "gorillahaulers.com", role, record_type: "message", ...(j >= leadFrom ? { lead_id: lead.id } : {}),
    }));
  const base = Date.now();
  return [
    { lead, messages: chat("web-6f1c2a9e-4b7d-4e10-9a53-2d8e7c41b5f0", base - 2 * 3600_000, [
      ["user", "Hi, I need a quote for moving a 2-bedroom apartment."],
      ["assistant", "Happy to help! Where are you moving from and to, and do you have a date in mind?"],
      ["user", `From ${lead.pickup_zip} to ${lead.delivery_zip}, around ${when}.`],
      ["assistant", "Thanks! A 2-bedroom local move usually needs a 3-mover crew. What name and phone number should the estimate go to?"],
      ["user", `${lead.full_name}, ${lead.phone_number}`],
      ["assistant", "All set! I've sent your request to the Gorilla Haulers team. A mover will call you shortly to confirm the details."],
    ], 5) },
    { lead: null, messages: chat("web-b83d07e2-91a4-4f6c-8e2b-5c0a1f9d3e67", base - 25 * 60_000, [
      ["user", "How much does a local move cost?"],
      ["assistant", "Local moves are priced by the hour, based on crew size and travel time. Most 1-bedroom moves take 3 to 4 hours. Want a quote? I just need your move date and ZIP codes."],
    ]) },
  ];
}

// One row per website conversation, in the backend's Messenger row shape.
function websiteRows(chats: ReturnType<typeof buildWebsiteChats>) {
  return chats.map(({ lead, messages }) => {
    const last = messages[messages.length - 1];
    const leadId = messages.find(m => m.lead_id)?.lead_id || "";
    return {
      conversation_id: leadId ? `lead:${leadId}:${WEBSITE_BOT}` : `unmatched:${WEBSITE_BOT}:${last.user_id}`,
      platform: WEBSITE_BOT,
      lead_id: leadId,
      client: lead && leadId ? String(lead.full_name) : "Website visitor",
      rep: lead && leadId ? String(lead.assigned_to_name || "") : "",
      company: lead && leadId ? String(lead.company_name) : "",
      timestamp: last.timestamp,
      message: last.text,
      attachments: [],
      direction: last.role,
      message_partition_key: last.user_id,
      company_identifier: "gorillahaulers.com",
      company_phone_identifier: "",
      destination_name: "gorillahaulers.com",
      destination_phone: "",
      destination_type: "company",
      sender_label: last.role === "assistant" ? "AI" : "",
    };
  });
}

export function websiteHistory(chats: ReturnType<typeof buildWebsiteChats>, userId: string) {
  return { messages: chats.find(c => c.messages[0].user_id === userId)?.messages || [] };
}

export function chatList(conversations: ReturnType<typeof buildConversations>, source: string, website: ReturnType<typeof buildWebsiteChats> = []) {
  const items: Record<string, unknown>[] = conversations
    .filter(c => (source === "meta" ? c.platform === "messenger" : c.platform === "sms"))
    .map(c => {
      const last = c.messages[c.messages.length - 1];
      return {
        platform: c.platform,
        lead_id: c.lead.id,
        client: String(c.lead.full_name),
        rep: String(c.lead.assigned_to_name || "Unassigned"),
        company: String(c.lead.company_name),
        timestamp: last.timestamp,
        message: last.text,
        direction: last.direction,
        message_partition_key: c.client,
        company_phone_identifier: c.companyNumber,
        company_identifier: c.platform === "sms" ? `aircall-${c.companyNumber}` : `page-${c.lead.company_id}`,
        destination_name: String(c.lead.company_name),
        destination_phone: c.companyNumber,
        destination_type: "company",
        sender_label: "",
      };
    });
  if (source === "meta") items.push(...websiteRows(website));
  return { items, next_cursor: "", has_more: false };
}

export function callList(conversations: ReturnType<typeof buildConversations>) {
  const items = conversations.filter(c => c.calls.length).map(c => {
    const last = c.calls[c.calls.length - 1];
    return {
      platform: "calls", call_id: last.message_id, lead_id: c.lead.id, client: String(c.lead.full_name),
      rep: String(c.lead.assigned_to_name || "Unassigned"), company: String(c.lead.company_name), timestamp: last.timestamp,
      direction: last.direction, answered: last.answered, client_identifier: c.client, company_identifier: c.companyNumber,
      destination_name: String(c.lead.company_name), destination_phone: c.companyNumber, destination_type: "company",
    };
  });
  items.push({
    platform: "calls", call_id: "unknown-1", lead_id: "", client: "(555) 018-3301", rep: "Unassigned", company: "",
    timestamp: now() - 40 * 60, direction: "inbound", answered: false, client_identifier: "5550183301", company_identifier: "5550192625",
    destination_name: "Gorilla Haulers", destination_phone: "5550192625", destination_type: "company",
  });
  return { items, next_cursor: "", has_more: false };
}

export function smsHistory(conversations: ReturnType<typeof buildConversations>, phone: string) {
  const c = conversations.find(x => x.client.endsWith(phone.replace(/\D/g, "").slice(-10)));
  return { messages: c ? c.messages.filter(m => m.platform === "sms") : [] };
}
export function metaHistory(conversations: ReturnType<typeof buildConversations>, partition: string) {
  const c = conversations.find(x => x.client === partition);
  return { messages: c ? c.messages.map(m => ({ ...m, platform: "messenger" })) : [] };
}
export function callHistory(conversations: ReturnType<typeof buildConversations>, phone: string) {
  const c = conversations.find(x => x.client.endsWith(phone.replace(/\D/g, "").slice(-10)));
  return { calls: c ? c.calls : [] };
}

// Work queue
export function queueMessages(conversations: ReturnType<typeof buildConversations>) {
  const items = conversations.filter(c => c.messages[c.messages.length - 1].direction === "inbound").map(c => {
    const last = c.messages[c.messages.length - 1];
    return {
      channel: c.platform, message_id: last.message_id, lead_id: c.lead.id, client_identifier: c.client, company_identifier: c.companyNumber,
      client: String(c.lead.full_name), client_number: c.client, message: last.text, rep: String(c.lead.assigned_to_name || "Unassigned"),
      company: String(c.lead.company_name), destination_number: c.companyNumber, destination_name: String(c.lead.company_name),
      occurred_at: iso(last.timestamp), smartmoving_id: String(c.lead.smartmoving_id || ""), quote_number: "",
    };
  });
  return { items, next_cursor: "", has_more: false, counts: { unanswered: items.length, ended: 0 }, global_counts: { unanswered: items.length, ended: 0 } };
}
export function queueMissedCalls(conversations: ReturnType<typeof buildConversations>) {
  const items = conversations.filter(c => c.calls.length).slice(0, 4).map((c, i) => ({
    call_id: `${c.lead.id}-missed`, lead_id: c.lead.id, client_identifier: c.client, company_identifier: c.companyNumber,
    client: String(c.lead.full_name), rep: String(c.lead.assigned_to_name || "Unassigned"), company: String(c.lead.company_name),
    ring_number: c.companyNumber, ring_target: String(c.lead.company_name), missed_count: 1 + (i % 2),
    first_missed_at: iso(now() - (i + 2) * 3600), latest_missed_at: iso(now() - (i + 1) * 3600), smartmoving_id: "", quote_number: "",
  }));
  return { items, count: items.length, global_count: items.length };
}
export function queueFirstContact(leads: Lead[]) {
  const items = leads.filter(l => l.status === "new").slice(0, 3).map((l, i) => ({
    lead_id: l.id, client: String(l.full_name), client_phone: String(l.phone_number), rep: String(l.assigned_to_name || "Unassigned"),
    company: String(l.company_name), status: "new", created_at: iso(now() - (i * 9 + 4) * 60), age_minutes: i * 9 + 4, smartmoving_id: "", quote_number: "",
  }));
  return { items, counts: { new: items.length, overdue: 0 }, global_counts: { new: items.length, overdue: 0 }, has_more: false };
}
export function queueFollowups(leads: Lead[]) {
  const items = leads.filter(l => l.status === "quoted").slice(0, 8).map((l, i) => {
    const attempt = (n: number, status: string) => ({ kind: "call", label: `Call ${n}`, period: `Day ${n}`, number: n, scheduled_start: iso(now() - (3 - n) * 86400), scheduled_end: iso(now() - (3 - n) * 86400 + 3600), completed_at: status === "completed" ? iso(now() - (3 - n) * 86400 + 1200) : "", status });
    const attempts = [attempt(1, "completed"), attempt(2, i % 3 === 0 ? "overdue" : "completed"), attempt(3, "open")];
    return {
      lead_id: l.id, client: String(l.full_name), client_phone: String(l.phone_number), rep: String(l.assigned_to_name || "Unassigned"),
      company: String(l.company_name), status: "quoted", priority: Number(l.priority || 0), created_at: String(l.created_at),
      smartmoving_created_time: String(l.created_time), created_time_source: "smartmoving", completed_count: 2 - (i % 3 === 0 ? 1 : 0),
      completed_message_count: 1, overdue_count: i % 3 === 0 ? 1 : 0, overdue_message_count: 0, attempts, message_attempts: [], timeline: attempts,
      smartmoving_id: String(l.smartmoving_id || ""), quote_number: "",
    };
  });
  const overdue = items.filter(i => i.overdue_count).length;
  return {
    items, counts: { all: items.length, overdue, due: items.length - overdue }, priority_counts: {}, global_counts: { all: items.length, overdue, due: items.length - overdue },
    filter_options: { reps: demoReps.map(r => r.name), companies: demoCompanies.map(c => c.name) }, has_more: false,
  };
}
export function queueSummary(conversations: ReturnType<typeof buildConversations>, leads: Lead[]) {
  const m = queueMessages(conversations).counts;
  const f = queueFollowups(leads).counts;
  return {
    enabled: true, ready: true, stale: false, updated_at: new Date().toISOString(), messages: m,
    missed_calls: queueMissedCalls(conversations).count, first_contact: queueFirstContact(leads).counts, followups: f,
  };
}

// Calendars and meetings
const COLORS: Record<string, string> = { "c-top": "#4B4DF7", "c-gorilla": "#E2552B", "c-wilson": "#0E9F8A", "c-m95": "#B7791F" };
export function salesCalendar(leads: Lead[]) {
  const items = leads.filter(l => ["booked", "scheduled", "completed"].includes(String(l.status))).map((l, i) => ({
    id: `${l.id}-job`, lead_id: l.id, company_id: l.company_id, company_name: l.company_name, company_color: COLORS[String(l.company_id)] || "#4B4DF7",
    job_order: 1, full_name: l.full_name, move_date: l["when_is_the_move?"], booked_move_date: l["when_is_the_move?"], pickup_zip: l.pickup_zip,
    delivery_zip: l.delivery_zip, price: (l.estimatedTotal as { finalTotal?: number } | null)?.finalTotal ?? null, estimatedTotal: l.estimatedTotal,
    payments: i % 3 === 0 ? [{ amount: Math.round(Number((l.estimatedTotal as { finalTotal?: number } | null)?.finalTotal || 0) * 0.3), takenByUser: String(l.assigned_to_name || "Maya Rosen") }] : [],
    status: l.status, assigned_to: l.assigned_to, assigned_to_name: l.assigned_to_name, assigned_to_role: "sales_rep",
  }));
  return { items };
}
export function walkthroughs(leads: Lead[]) {
  const statuses = ["requested", "requested", "approved", "completed"];
  const items = leads.slice(20, 26).map((l, i) => {
    const at = new Date(Date.now() + (i - 2) * 86400000); at.setHours(15 + (i % 3), 0, 0, 0);
    const end = new Date(at.getTime() + 2 * 3600000);
    return {
      phone: l.phone_number, pickup: l.pickup_zip, delivery: l.delivery_zip, move_date: l["when_is_the_move?"], lead_id: l.id, name: l.full_name,
      company: l.company_name, company_id: l.company_id,
      requests: [{ id: `wr-${i}`, status: statuses[i % statuses.length], availability: `${at.toISOString()} - ${end.toISOString()}`, timezone: "America/New_York", scheduled_at: statuses[i % 4] === "requested" ? null : at.toISOString(), assigned_to: statuses[i % 4] === "requested" ? "" : "u-sara", created_at: new Date(at.getTime() - 3 * 86400000).toISOString() }],
    };
  });
  return { items, companies: demoCompanies, reps: demoReps.filter(r => r.role === "sales_rep") };
}

// Reports and settings
export function bookingReport(leads: Lead[]) {
  const moves = leads.slice(0, 24).map(l => ({
    id: `move-${l.id}`, customer: String(l.full_name), first_signup: String(l.created_time), move_date: String(l["when_is_the_move?"]),
    pickup: String(l.pickup_zip), delivery: String(l.delivery_zip), booked: ["booked", "scheduled", "completed"].includes(String(l.status)), issues: [],
    leads: [{ id: l.id, company: String(l.company_name), status: String(l.status), created_time: String(l.created_time), created_at: String(l.created_at), issues: [] }],
  }));
  const booked = moves.filter(m => m.booked).length;
  return {
    options: { companies: demoCompanies.map(c => c.name), reps: demoReps.map(r => r.name) },
    total_moves: moves.length, booked_moves: booked, percentage: Math.round((booked / moves.length) * 1000) / 10, lead_count: leads.length,
    duplicates_removed: 3, review_count: 0, undated_moves: 0, moves,
  };
}
// Twelve months, oldest first, of cumulative booked sales by day for each rep (the server's shape):
// days after the end of the month, or after today in the current month, are null.
export function salesPerformance() {
  const today = new Date();
  const months = Array.from({ length: 12 }, (_, i) => {
    const m = new Date(today.getFullYear(), today.getMonth() - 11 + i, 1);
    return { date: m, month: `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`, label: m.toLocaleDateString("en-US", { month: "short", year: "numeric" }) };
  });
  let seed = 7;
  const random = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  const reps = demoReps.slice(0, 4).map((rep, r) => ({
    id: rep.id,
    name: rep.name,
    series: months.map(({ date, month, label }, m) => {
      const lastDay = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
      const finalDay = m === months.length - 1 ? today.getDate() : lastDay;
      const pace = 1 + 0.35 * Math.sin((m + r * 2) / 1.9) + r * 0.08;
      let total = 0;
      const values = Array.from({ length: 31 }, (_, d) => {
        if (d + 1 > finalDay) return null;
        if (random() < 0.42) total += Math.round((1400 + random() * 5200) * pace / 10) * 10;
        return total;
      });
      return { month, label, values, total };
    }),
  }));
  return { months: months.map(({ month, label }) => ({ month, label })), reps };
}
export function templates(which: string) {
  const defaults = {
    welcome_sms: "Hi {first_name}, thanks for reaching out to {company}! A moving specialist will contact you shortly.",
    rep_assignment_sms: "Hi {first_name}, I'm {rep_name} from {company}. I'll help with your move. Call or text me anytime.",
    day2_followup_sms: "Hi {first_name}, just checking in about your move. Any questions about the estimate?",
    day3_followup_sms: "Hi {first_name}, we'd love to help with your move. Reply here and I'll call you back.",
  };
  return { company_id: which.startsWith("templates") ? "" : which.split("/")[0], ...defaults, updated_by: "Maya Rosen", updated_at: new Date().toISOString(), defaults };
}
