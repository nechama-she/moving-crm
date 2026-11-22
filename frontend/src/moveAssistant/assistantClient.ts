// How the move page window talks to BoxBot.
//
// The window shows only when api-config.js turns it on, so a site without it is unchanged:
//   window.__MOVE_ASSISTANT__ = { url: '/api/customer-chat' }
// The path is on the site's own CloudFront distribution, which adds BoxBot's key on the way to BoxBot,
// so the browser never holds the key. Only a path on this site is accepted: the page's session goes with every
// message, so it must never be sent to another website. The local demo (npm run dev:demo) answers that path with a
// fake BoxBot.
//
// POST {url}/{access_id}, with the page's own x-public-link and x-public-session headers.
//   body    { message, audience }  or  { event: { type: 'open' }, audience }   ('rep' on the rep view)
//   answer  { reply, quick_replies, history (open only), cards, action, reverify }
//           (BoxBot also sends `step`; the page shows its own steps, so it is not read.)
//   401     the page's session is not valid: the page asks for its code again
//   429/503/504, or no answer in 65 seconds: the "busy" text (the server's `detail` when it sends one)
//   anything else: the window's own "couldn't answer" text, never the server's
import type { AssistantMessage, AssistantReply, Audience, BotAction, SlotCard } from './assistantTypes';

declare global {
  interface Window { __MOVE_ASSISTANT__?: { url?: string } }
}

export type AssistantConfig = { url: string };

export function assistantConfig(): AssistantConfig | null {
  const url = window.__MOVE_ASSISTANT__?.url || (import.meta.env.MODE === 'demo' ? '/api/customer-chat' : '');
  // A path on this site ("/api/..."), never a full address or "//host" (another website).
  return /^\/(?!\/)[\w\-/]+$/.test(url) ? { url: url.replace(/\/+$/, '') } : null;
}

export const BUSY_TEXT = "I'm busy right now. Please try again in a minute.";
const FAILED_TEXT = "I couldn't answer that just now. Please try again.";
const TIMEOUT_MS = 65000;

// A failed call. `session` means the page has to verify again; the rest show `message` with a retry.
export class AssistantError extends Error {
  constructor(message: string, readonly kind: 'session' | 'busy' | 'failed') { super(message); }
}

type Call = {
  config: AssistantConfig;
  accessId: string;
  audience: Audience;
  headers: Record<string, string>;
  signal: AbortSignal;
} & ({ message: string } | { open: true });

export async function callAssistant(call: Call): Promise<AssistantReply> {
  const timeout = new AbortController();
  const timer = window.setTimeout(() => timeout.abort(), TIMEOUT_MS);
  const stop = () => timeout.abort();
  call.signal.addEventListener('abort', stop, { once: true });
  let response: Response;
  try {
    response = await fetch(`${call.config.url}/${encodeURIComponent(call.accessId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-public-link': call.headers['x-public-link'] || '', 'x-public-session': call.headers['x-public-session'] || '' },
      body: JSON.stringify('open' in call ? { event: { type: 'open' }, audience: call.audience } : { message: call.message, audience: call.audience }),
      cache: 'no-store',
      signal: timeout.signal,
    });
  } catch (error) {
    if (call.signal.aborted) throw error;
    throw new AssistantError(timeout.signal.aborted ? BUSY_TEXT : FAILED_TEXT, timeout.signal.aborted ? 'busy' : 'failed');
  } finally {
    window.clearTimeout(timer);
    call.signal.removeEventListener('abort', stop);
  }
  const value = await response.json().catch(() => null);
  if (response.status === 401) throw new AssistantError('Please verify your phone or email to continue.', 'session');
  if ([429, 503, 504].includes(response.status)) throw new AssistantError(typeof value?.detail === 'string' && value.detail ? value.detail : BUSY_TEXT, 'busy');
  // Any other failure shows the window's own text: a server error ("Not Found", "Internal Server Error") means
  // nothing to a customer.
  if (!response.ok || !value || typeof value !== 'object') throw new AssistantError(FAILED_TEXT, 'failed');
  return readReply(value);
}

// Takes only what the window knows how to show; anything else in the answer is ignored.
function readReply(value: Record<string, unknown>): AssistantReply {
  const strings = (list: unknown) => Array.isArray(list) ? list.filter((item): item is string => typeof item === 'string' && !!item.trim()) : [];
  const history = Array.isArray(value.history) ? value.history.flatMap((row, index): AssistantMessage[] => {
    if (!row || typeof row.text !== 'string' || !row.text) return [];
    return [{ id: `history-${index}`, role: row.role === 'user' ? 'customer' : 'assistant', text: row.text }];
  }) : undefined;
  return {
    reply: typeof value.reply === 'string' && value.reply ? value.reply : null,
    quickReplies: strings(value.quick_replies).slice(0, 4),
    history,
    cards: Array.isArray(value.cards) ? value.cards.flatMap(readSlots) : [],
    action: readAction(value.action),
    reverify: value.reverify === true,
  };
}

function readAction(value: unknown): BotAction | undefined {
  const action = value as { type?: unknown; signature_id?: unknown } | null;
  if (action?.type === 'open_signing' && typeof action.signature_id === 'string' && action.signature_id) return { type: 'open_signing', signatureId: action.signature_id };
  if (action?.type === 'open_bol_signing') return { type: 'open_bol_signing' };
  return undefined;
}

function readSlots(value: unknown): SlotCard[] {
  const card = value as { type?: unknown; days?: unknown } | null;
  if (card?.type !== 'slots' || !Array.isArray(card.days)) return [];
  const days = card.days.flatMap(day => {
    const slots = Array.isArray(day?.slots) ? day.slots.filter((slot: { start?: unknown; label?: unknown }) => typeof slot?.start === 'string' && typeof slot?.label === 'string') : [];
    return slots.length && typeof day.label === 'string' ? [{ date: String(day.date || ''), label: day.label, slots }] : [];
  });
  return days.length ? [{ type: 'slots', days }] : [];
}

// "Book 2026-11-24T10:00:00-05:00", the message a slot sends, reads as a time in the conversation.
// The clock time is read as written (the company's time), not moved to the viewer's time zone.
export function displayText(text: string) {
  const booked = text.match(/^Book (\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::[\d.]+)?(?:Z|[+-]\d{2}:?\d{2})?$/);
  if (!booked) return text;
  const [, year, month, day, hour, minute] = booked.map(Number);
  const date = new Date(year, month - 1, day, 12);
  if (Number.isNaN(date.getTime()) || hour > 23 || minute > 59) return text;
  const time = `${hour % 12 || 12}${minute ? `:${String(minute).padStart(2, '0')}` : ''} ${hour < 12 ? 'AM' : 'PM'}`;
  return `Book ${date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })} at ${time}`;
}
