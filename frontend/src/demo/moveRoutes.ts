// Demo answers for the customer move page (/move/:accessId), with invented data.
// The access id picks how far the move is, so each step of the page (and its assistant) can be reviewed:
//   /move/demo-inventory  no inventory yet (step 1)
//   /move/demo-services   inventory added, an extra-services question open (step 2)
//   /move/demo-sign       price ready, waiting for the signature (step 3)
//   /move/demo-signed     everything done
//   /move/demo-sign-rep   the same, as the rep's link
// Any code verifies.

type Stage = "inventory" | "services" | "sign" | "signed";
// A "-rep" ending opens the same stage as the rep's link (/move/demo-sign-rep).
const stageOf = (accessId: string): Stage =>
  accessId.includes("services") ? "services" : accessId.includes("signed") ? "signed" : accessId.includes("sign") ? "sign" : "inventory";

const company = {
  name: "Northwind Movers",
  phone: "(555) 010-2040",
  office_address: "120 Harbor Way, Tampa, FL",
  color: "#1f5f8b",
};

const move = {
  name: "Sarah Mitchell",
  phone: "(555) 010-0142",
  email: "sarah.m@example.com",
  move_date: "2026-12-14",
  pickup: "4812 Bayshore Blvd, Tampa, FL 33611",
  delivery: "2210 Peachtree Rd NW, Atlanta, GA 30309",
  company: company.name,
  company_details: company,
  stops: [],
  contacts: [],
};

const livingRoom = {
  id: "room-living", room_type_id: "living", name: "Living room", items: {},
  custom_items: [
    { id: "it-sofa", name: "Sofa, 3 seat", cuft: 45, quantity: 1, going: true },
    { id: "it-tv", name: "TV, flat 55 in", cuft: 10, quantity: 1, going: true },
    { id: "it-table", name: "Coffee table", cuft: 8, quantity: 1, going: true },
  ],
};
const bedroom = {
  id: "room-bed", room_type_id: "bedroom", name: "Main bedroom", items: {},
  custom_items: [
    { id: "it-bed", name: "Queen bed", cuft: 60, quantity: 1, going: true },
    { id: "it-dresser", name: "Dresser", cuft: 30, quantity: 1, going: true },
    { id: "it-boxes", name: "Medium box", cuft: 3, quantity: 14, going: true },
  ],
};

const elevator = {
  tiers: [{ up_to_cuft: null, fee: 150 }], terms: "", cubic_feet: 620, fee: 150,
  locations: [{ location: "pickup", address: move.pickup, revision: "1", uses_elevator: null, discount_percent: 0,
    question: "Will the movers use an elevator at your pickup address?" }],
};

// The assistant can move the date; the page then shows the new one.
const dateKey = (accessId: string) => `demo_move_date_${accessId}`;
const moveOf = (accessId: string) => {
  let date = "";
  try { date = sessionStorage.getItem(dateKey(accessId)) || ""; } catch { /* The planned date. */ }
  return { ...move, move_date: date || move.move_date };
};

function sections(stage: Stage, section: string, accessId: string) {
  const priced = stage === "sign" || stage === "signed";
  switch (section) {
    case "move": return moveOf(accessId);
    case "media": return { files: [], editable_files: [], walkthrough: null, participant_url: "" };
    case "estimate": return priced
      ? { estimate: { price: "$4,280.00", cuft: "620", charges: [] }, spark: { id: "demo-report", status: "completed", cuft: 620 } }
      : { estimate: null, spark: stage === "services" ? { id: "demo-report", status: "completed", cuft: 620 } : null };
    case "pricing": return {
      unanswered_questions: stage === "inventory" ? [] : stage === "services" ? ["elevator"] : [],
      elevator: stage === "inventory" ? null : { ...elevator, locations: elevator.locations.map(row => ({ ...row, uses_elevator: stage === "services" ? null : false })) },
      packing_items: [], packing_package: null, packing_saved: stage !== "inventory" && stage !== "services",
      item_questions: [],
      signature_status: stage === "signed" ? "signed" : "unsigned",
      bill_of_lading: null,
      report_history: [],
    };
    default: return {};
  }
}

// A one-page PDF, so the estimate viewer has something to show.
const DEMO_SIGNATURE = "demo-signature-1";
const DEMO_PDF = (() => {
  const text = "BT /F1 18 Tf 72 720 Td (Northwind Movers - Estimate for Sarah Mitchell) Tj 0 -30 Td /F1 12 Tf (Total: $4,280.00 - 620 cu ft - demo data) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${text.length} >>\nstream\n${text}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = objects.map((object, index) => { const at = pdf.length; pdf += `${index + 1} 0 obj\n${object}\nendobj\n`; return at; });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map(at => `${String(at).padStart(10, "0")} 00000 n \n`).join("")}`;
  return `${pdf}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
})();

// A fake BoxBot for POST /api/customer-chat/<access id>, with BoxBot's answer shape: a greeting on the first
// open (the conversation after that), quick replies, video walkthrough slots, and open_signing on "sign".
// Test words: "test busy" (429 without detail), "test timeout" (504), "test session" (401), "test reverify".
type Turn = { role: "user" | "assistant"; text: string; ts: number };
const chatKey = (accessId: string, audience: string) => `demo_chat_${accessId}_${audience}`;
function chatHistory(key: string): Turn[] { try { return JSON.parse(sessionStorage.getItem(key) || "[]"); } catch { return []; } }

function weekdaySlots() {
  const days = [];
  for (let day = new Date(); days.length < 3;) {
    day = new Date(day.getFullYear(), day.getMonth(), day.getDate() + 1);
    if (day.getDay() === 0 || day.getDay() === 6) continue;
    const date = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
    days.push({ date, label: day.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }),
      slots: [[10, "10 AM - 12 PM"], [13, "1 PM - 3 PM"], [16, "4 PM - 6 PM"]].map(([hour, label]) => ({
        start: `${date}T${String(hour).padStart(2, "0")}:00:00-05:00`, end: `${date}T${String(Number(hour) + 2).padStart(2, "0")}:00:00-05:00`, label })) });
  }
  return days;
}

async function fakeBoxBot(accessId: string, stage: Stage, request: { message?: string; event?: { type?: string }; audience?: string }) {
  await new Promise(resolve => setTimeout(resolve, 900 + Math.random() * 900));
  const key = chatKey(accessId, request.audience === "rep" ? "rep" : "customer");
  const history = chatHistory(key);
  const step = stage === "inventory" ? "inventory" : stage === "services" ? "questions" : stage === "sign" ? "estimate" : "signed";
  const next = {
    inventory: ["Help me list my items", "Can I send photos?", "Book a video walkthrough"],
    services: ["Why do you need this?", "No elevator at pickup", "What's left to do?"],
    sign: ["Explain my estimate", "I want to sign", "Move my date to December 3"],
    signed: ["What happens next?", "Move my date to December 3", "Talk to a person"],
  }[stage];
  const answer = (reply: string, extra: Record<string, unknown> = {}) => {
    const message = request.message?.trim();
    sessionStorage.setItem(key, JSON.stringify([...history, ...(message ? [{ role: "user", text: message, ts: Date.now() / 1000 }] : []), { role: "assistant", text: reply, ts: Date.now() / 1000 }]));
    return { body: { reply, quick_replies: next, step, ...extra } };
  };
  if (request.event?.type === "open") {
    if (history.length) return { body: { reply: null, history, quick_replies: next, step } };
    return answer({
      inventory: "Hi Sarah! I'm the Northwind Movers assistant. To price your move I need your items. Tell me what's in each room, send photos, or book a short video walkthrough.",
      services: "Hi Sarah! Your inventory is in. One question is left before your price: will the movers use an elevator at your pickup address?",
      sign: "Hi Sarah! Your estimate is ready: **$4,280.00** for about 620 cubic feet. Ask me anything about it, or tell me when you want to sign.",
      signed: "Hi Sarah! Your estimate is signed. Your move is set for **Monday, December 14**. I'm here if anything changes.",
    }[stage]);
  }
  const text = String(request.message || "").toLowerCase();
  if (text.includes("test busy")) return { status: 429, body: { error: "Too many requests" } };
  if (text.includes("test timeout")) return { status: 504, body: {} };
  if (text.includes("test session")) return { status: 401, body: { detail: "Session expired" } };
  if (text.includes("test reverify")) return answer("Done. Your main phone is now (555) 010-0199. We sent a new code there, so please verify again.", { reverify: true });
  if (/^book \d{4}-/.test(text)) return answer("You're booked. A Northwind Movers estimator will call you on video at that time. You'll get a reminder text.");
  if (/video|walkthrough/.test(text)) return answer("Sure. Pick a time for a short video walkthrough:", { cards: [{ type: "slots", days: weekdaySlots() }] });
  if (/\bsign\b/.test(text)) return stage === "sign"
    ? answer("Opening your estimate now. Review it and sign at the bottom.", { action: { type: "open_signing", signature_id: DEMO_SIGNATURE } })
    : answer(stage === "signed" ? "Your estimate is already signed." : "Your estimate isn't ready to sign yet. Let's finish your inventory and questions first.");
  if (/date|december/.test(text)) {
    sessionStorage.setItem(dateKey(accessId), "2026-12-03");
    return answer("Done. I moved your move date to **Thursday, December 3**. The page shows the new date.");
  }
  if (/elevator/.test(text)) return answer("Got it: no elevator at pickup. Your price is being updated now.");
  return answer("Got it. Your move is from Tampa to Atlanta. Is there anything you'd like to change, or a question about your estimate?");
}

export async function moveRoute(method: string, path: string, body?: unknown): Promise<{ status?: number; body: unknown; contentType?: string } | null> {
  const chat = path.match(/^customer-chat\/([^/]+)$/);
  if (chat && method === "POST") return fakeBoxBot(chat[1], stageOf(chat[1]), (body || {}) as Parameters<typeof fakeBoxBot>[2]);
  const match = path.match(/^public-moves\/([^/]+)\/(.+)$/);
  if (!match) return null;
  const [, accessId, rest] = match;
  const stage = stageOf(accessId);
  if (rest === "verify-options") return { body: { audience: accessId.endsWith("-rep") ? "rep" : "customer", customer_can_edit: true, company,
    options: [{ channel: "sms", destination: "(•••) •••-0142" }, { channel: "email", destination: "s•••@example.com" }] } };
  if (rest === "send-code") return { body: { ok: true } };
  if (rest === "verify") return { body: { session: `demo-session-${accessId}`, expires_in: 4 * 3600, move } };
  if (rest === "summary" || rest === "details") return { body: { ...moveOf(accessId), ...sections(stage, "estimate", accessId), ...sections(stage, "pricing", accessId) } };
  const section = rest.match(/^sections\/(\w+)$/);
  if (section && method === "GET") return { body: sections(stage, section[1], accessId) };
  if (rest === "inventory/editor") return { body: {
    revision: "demo-1", report_id: stage === "inventory" ? null : "demo-report",
    room_types: [{ id: "living", name: "Living room" }, { id: "bedroom", name: "Bedroom" }, { id: "kitchen", name: "Kitchen" }],
    rooms: stage === "inventory" ? [] : [livingRoom, bedroom],
  } };
  if (rest === "estimate-signatures" && method === "GET") return { body: { items: [] } };
  if (rest === "estimate-signatures") return { body: { id: DEMO_SIGNATURE, signed: false, approved: true } };
  if (/^(estimate|bill-of-lading)-signatures\/[^/]+\/pdf$/.test(rest)) return { body: DEMO_PDF, contentType: "application/pdf" };
  if (rest.startsWith("inventory-catalog")) return { body: { items: [], sets: [], set_items: [] } };
  // No live updates in the demo: the page then offers its own refresh.
  if (rest === "realtime-token") return { status: 503, body: { detail: "Live updates are not part of the demo." } };
  return { body: method === "GET" ? {} : { ok: true } };
}
