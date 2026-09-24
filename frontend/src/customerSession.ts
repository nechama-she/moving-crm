import { API_BASE } from './apiConfig';

export const CUSTOMER_SESSION_EXPIRED = 'customer-session-expired';
const sessions = new Map<string, { expiresAt: number; requests: Set<AbortController> }>();

export function registerCustomerSession(token: string, expiresAt: number) {
  if (token && Number.isFinite(expiresAt) && expiresAt > Date.now())
    sessions.set(token, { expiresAt, requests: sessions.get(token)?.requests || new Set() });
}

export function expireCustomerSession(token: string) {
  const session = sessions.get(token);
  sessions.delete(token);
  session?.requests.forEach(controller => controller.abort());
  window.dispatchEvent(new CustomEvent(CUSTOMER_SESSION_EXPIRED, { detail: token }));
}

export function customerSessionActive(token: string) {
  const session = sessions.get(token);
  if (session && session.expiresAt > Date.now()) return true;
  if (token) expireCustomerSession(token);
  return false;
}

export function loadCustomerSession(storageKey: string) {
  const token = sessionStorage.getItem(storageKey) || '';
  const expiresAt = Number(sessionStorage.getItem(storageKey + ':expiresAt'));
  if (!token || !Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    sessionStorage.removeItem(storageKey);
    sessionStorage.removeItem(storageKey + ':expiresAt');
    return '';
  }
  registerCustomerSession(token, expiresAt);
  return token;
}

export function installCustomerSessionFetch() {
  const original = window.fetch.bind(window);
  const api = new URL(`${API_BASE}/api/public-moves/`, window.location.origin);
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.origin);
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    const token = headers.get('x-public-session');
    if (!token || url.origin !== api.origin || !url.pathname.startsWith(api.pathname)) return original(input, init);
    const ended = () => new DOMException('Please verify your phone or email to continue.', 'AbortError');
    if (!customerSessionActive(token)) throw ended();
    const session = sessions.get(token)!;
    const controller = new AbortController();
    const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined);
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener('abort', abort, { once: true });
    session.requests.add(controller);
    try {
      const response = await original(input, { ...init, signal: controller.signal });
      if (response.status === 401 || response.status === 404) expireCustomerSession(token);
      if (!customerSessionActive(token)) throw ended();
      return response;
    } finally {
      session.requests.delete(controller);
      signal?.removeEventListener('abort', abort);
    }
  };
}
