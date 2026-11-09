// Local demo mode: answers the CRM's /api requests in the browser with invented data,
// so the UI can be reviewed without a backend or real customer data.
// Loaded only when Vite runs with `--mode demo` (npm run dev:demo); never part of a production build.
import type { Lead } from "../leadUtils";
import { demoCompanies, demoLeads, demoReps, demoSummary, demoUser } from "./fixtures";
import * as more from "./moreRoutes";
import * as pricing from "./pricing";

type Handler = (ctx: { url: URL; method: string; body: unknown; params: string[] }) => unknown;

const toBase64Url = (value: string) => btoa(value).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const demoToken = () => [
  toBase64Url(JSON.stringify({ alg: "none", typ: "JWT" })),
  toBase64Url(JSON.stringify({ sub: demoUser.id, role: demoUser.role, exp: Math.floor(Date.now() / 1000) + 30 * 86400 })),
  "demo",
].join(".");

const leads: Lead[] = demoLeads.map(lead => ({ ...lead }));
const conversations = more.buildConversations(leads);
const websiteChats = more.buildWebsiteChats(leads);

function listLeads(url: URL) {
  const q = url.searchParams;
  const search = (q.get("search") || "").toLowerCase();
  const status = q.get("status") || "";
  const company = q.get("company_id") || "";
  const assigned = q.get("assigned_to") || "";
  const sortBy = q.get("sort_by") || "created_time";
  const dir = q.get("sort_dir") === "asc" ? 1 : -1;
  const offset = Number(q.get("offset") || 0);
  const limit = Number(q.get("limit") || 50);
  let rows = leads.filter(l =>
    (!search || [l.full_name, l.email, l.phone_number, l.id, l.pickup_zip, l.delivery_zip].some(v => String(v).toLowerCase().includes(search))) &&
    (!status || l.status === status) &&
    (!company || (company === "__unassigned__" ? !l.company_id : l.company_id === company)) &&
    (!assigned || (assigned === "__unassigned__" ? !l.assigned_to : l.assigned_to === assigned)));
  rows = [...rows].sort((a, b) => String(a[sortBy] ?? "").localeCompare(String(b[sortBy] ?? "")) * dir);
  return {
    summary: offset === 0 ? demoSummary(rows, status) : null,
    items: rows.slice(offset, offset + limit),
    total: rows.length,
    has_more: offset + limit < rows.length,
  };
}

function money(lead: Lead) {
  const total = (lead.estimatedTotal as { finalTotal?: number } | null)?.finalTotal;
  return total ? `$${Math.round(total).toLocaleString("en-US")}` : "—";
}

// Scripted "Ask the CRM" answers. The real assistant will run on the server once connected in AWS.
function askCrm(body: unknown) {
  const question = String((body as { question?: string } | null)?.question || "").toLowerCase();
  const quoted = leads.filter(l => l.status === "quoted");
  if (/wait|repl|answer/.test(question)) {
    const items = leads.filter(l => ["new", "contacted"].includes(String(l.status))).slice(0, 5);
    return {
      answer: `${items.length} customers are waiting for a reply. The longest has waited 5 hours.`,
      detail: "Sorted by waiting time. Missed calls are included.",
      items: items.map((l, i) => ({ id: l.id, name: l.full_name, detail: `${l.company_name} · ${l.pickup_zip}`, value: money(l), flag: `Waiting ${5 - i} h`, tone: "warn" })),
      actions: ["Draft replies (review before sending)", "Assign to me", "Save as a view"],
    };
  }
  const items = [...quoted].sort((a, b) => Number((b.estimatedTotal as { finalTotal?: number } | null)?.finalTotal || 0) - Number((a.estimatedTotal as { finalTotal?: number } | null)?.finalTotal || 0)).slice(0, 5);
  const sum = items.reduce((s, l) => s + Number((l.estimatedTotal as { finalTotal?: number } | null)?.finalTotal || 0), 0);
  return {
    answer: `${items.length} open quotes are worth $${Math.round(sum).toLocaleString("en-US")} together.`,
    detail: `${Math.min(3, items.length)} have not heard from anyone in over 2 days. The first two are the most likely to book.`,
    items: items.map((l, i) => ({ id: l.id, name: l.full_name, detail: `${l.pickup_zip} → ${l.delivery_zip} · ${l.company_name}`, value: money(l), flag: i < 2 ? "Likely to book" : "No reply 2+ days", tone: i < 2 ? "good" : "warn" })),
    actions: ["Draft follow-up texts (review before sending)", "Add call tasks for tomorrow", "Save as a view"],
  };
}

function leadSummary(lead: Lead) {
  return {
    summary: `${String(lead.move_size || "Move")} from ${String(lead.pickup_zip)} to ${String(lead.delivery_zip)}. ` +
      (lead.status === "quoted" ? `Quote ${money(lead)} sent; the customer compared prices and asked about storage. Best next step: call before Friday.`
        : lead.status === "new" ? "New lead with no contact yet. Best next step: call within 15 minutes."
        : "Customer is in touch with the team. Best next step: confirm the move date and send a quote."),
  };
}

const routes: Array<[string, RegExp, Handler]> = [
  ["POST", /^auth\/login$/, () => ({ token: demoToken(), user: demoUser })],
  ["GET", /^auth\/me$/, () => demoUser],
  ["POST", /^auth\/change-password$/, () => ({ ok: true })],
  ["GET", /^leads$/, ({ url }) => listLeads(url)],
  ["GET", /^leads\/([^/]+)$/, ({ params }) => leads.find(l => l.id === params[0]) || leads[0]],
  ["GET", /^leads\/([^/]+)\/ai-summary$/, ({ params }) => leadSummary(leads.find(l => l.id === params[0]) || leads[0])],
  // Estimate panel: the customer link with any walkthrough, and the report media.
  ["GET", /^leads\/([^/]+)\/customer-page$/, ({ params }) => ({ url: `https://example.com/move/demo-${params[0]}`, revoked: false, requests: [] })],
  ["GET", /^leads\/[^/]+\/customer-page\/media$/, () => ({ files: [] })],
  ["GET", /^companies(\/mine)?$/, () => demoCompanies],
  ["GET", /^users\/mine-reps$/, () => demoReps.filter(r => r.role === "sales_rep")],
  ["GET", /^users$/, () => demoReps],
  ["POST", /^ai\/ask$/, ({ body }) => askCrm(body)],
  // The search box checks that the assistant exists before offering "Ask the CRM".
  ["GET", /^ai\/ask$/, () => ({ ready: true })],
  ["GET", /^chats$/, ({ url }) => more.chatList(conversations, url.searchParams.get("source") || "sms", websiteChats)],
  ["GET", /^chats\/website_gorillah_bot\/([^/]+)$/, ({ params }) => more.websiteHistory(websiteChats, params[0])],
  ["GET", /^chats\/calls$/, () => more.callList(conversations)],
  ["GET", /^chats\/calls\/history$/, ({ url }) => more.callHistory(conversations, url.searchParams.get("phone") || "")],
  ["GET", /^sms\/([^/]+)$/, ({ params }) => more.smsHistory(conversations, params[0])],
  ["GET", /^meta\/[^/]+\/([^/]+)$/, ({ params }) => more.metaHistory(conversations, params[0])],
  ["GET", /^unanswered-messages$/, () => more.queueMessages(conversations)],
  ["GET", /^unanswered-messages\/summary$/, () => more.queueSummary(conversations, leads)],
  ["GET", /^unanswered-messages\/missed-calls$/, () => more.queueMissedCalls(conversations)],
  ["GET", /^unanswered-messages\/first-contact-leads$/, () => more.queueFirstContact(leads)],
  ["GET", /^unanswered-messages\/followup-calls$/, () => more.queueFollowups(leads)],
  ["GET", /^sales-calendar$/, () => more.salesCalendar(leads)],
  ["GET", /^walkthrough-requests$/, () => more.walkthroughs(leads)],
  ["GET", /^stats\/booking-percentage$/, () => more.bookingReport(leads)],
  ["GET", /^sales-performance$/, () => more.salesPerformance()],
  ["GET", /^pricing$/, () => pricing.pricingBooks()],
  ["GET", /^pricing\/local\/[^/]+$/, () => pricing.localPricing()],
  ["POST", /^pricing\/local\/[^/]+\/calculate$/, ({ body }) => pricing.localQuote(body as { cubic_feet?: number; crew_size?: number | null })],
  ["GET", /^pricing\/(pb-[^/]+)$/, ({ params }) => pricing.pricingBook(params[0])],
  ["GET", /^companies\/(templates\/defaults|[^/]+\/templates)$/, ({ params }) => more.templates(params[0])],
  ["GET", /^companies\/[^/]+\/documents$/, () => ({ items: [], fields: [] })],
  ["GET", /^inventory-catalog\/sets$/, () => ({ sets: [] })],
  ["GET", /^referral-assignment-rules$/, () => ({ rules: [], companies: demoCompanies, reps: demoReps.map(r => ({ ...r, email: `${r.id}@example.com`, company_ids: demoCompanies.map(c => c.id) })), referral_sources: {} })],
];

// Endpoints whose pages read fields like `.items` or `.companies` from the response.
const OBJECT_ENDPOINTS = [
  /^auto-assign-(events|filters)$/, /^communication-associations\//, /^customer-questions\//, /^dispatch-(calendar|calendar-days|job-search)$/,
  /^inventory-catalog$/, /^lead-duplication-rules$/, /^lead-duplications\/pending/, /^leads\/[^/]+\/(copy-conflicts|jobs|logs)$/,
  /^leads\/[^/]+\/jobs\/[^/]+\/attachments$/, /^outreach-(events|filters)$/, /^pricing\//, /^stats\//, /^unanswered-messages\//,
];
const EMPTY_OBJECT = { items: [], companies: [], reps: [], rules: [], rows: [], days: [], options: {}, counts: {}, total: 0, has_more: false, next_cursor: "" };

export function installDemoApi() {
  const original = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/")) return original(input, init);
    const method = (init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    const path = url.pathname.slice("/api/".length).replace(/\/$/, "");
    let body: unknown = null;
    if (typeof init?.body === "string") { try { body = JSON.parse(init.body); } catch { body = init.body; } }
    await new Promise(resolve => setTimeout(resolve, 120 + Math.random() * 180));
    for (const [m, pattern, handler] of routes) {
      const match = method === m ? path.match(pattern) : null;
      if (match) return json(handler({ url, method, body, params: match.slice(1).map(decodeURIComponent) }));
    }
    // Anything not modelled yet answers safely: an empty list (or an empty object for pages that
    // read named fields), success for writes.
    if (method === "GET" && OBJECT_ENDPOINTS.some(pattern => pattern.test(path))) return json(EMPTY_OBJECT);
    return json(method === "GET" ? [] : { ok: true });
  };
  console.info("[demo] Moving CRM is running with invented demo data.");
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}
