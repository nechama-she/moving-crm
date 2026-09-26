import { API_BASE } from './apiConfig';
export const SESSION_EXPIRED = 'crm-session-expired';
export function tokenExpiry(token: string): number | null {
  try { const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'); const exp = JSON.parse(atob(payload)).exp; return typeof exp === 'number' ? exp * 1000 : null; }
  catch { return null; }
}
export function installSessionFetch() {
  const original = window.fetch.bind(window);
  const rejected = new Set<string>();
  const pending = new Map<string, Set<AbortController>>();
  const api = new URL(`${API_BASE}/api/`, window.location.origin);
  function expire(token: string) {
    if (rejected.has(token)) return;
    rejected.add(token);
    pending.get(token)?.forEach(controller => controller.abort());
    if (localStorage.getItem('token') === token) window.dispatchEvent(new CustomEvent(SESSION_EXPIRED, { detail: token }));
  }
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.origin);
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    const bearer = headers.get('Authorization')?.match(/^Bearer (.+)$/i)?.[1];
    const staffRequest = url.origin === api.origin && url.pathname.startsWith(api.pathname) && !url.pathname.startsWith(`${api.pathname}public-moves/`);
    if (!staffRequest) return original(input, init);
    if (!bearer) {
      if (/^leads(?:\/|$)/.test(url.pathname.slice(api.pathname.length)))
        throw new DOMException('Sign in to continue.', 'AbortError');
      return original(input, init);
    }
    const expiry = tokenExpiry(bearer);
    if (expiry !== null && expiry <= Date.now()) expire(bearer);
    if (rejected.has(bearer) || localStorage.getItem('token') !== bearer) throw new DOMException('Session ended', 'AbortError');
    const controller = new AbortController();
    const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined);
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener('abort', abort, { once: true });
    const requests = pending.get(bearer) || new Set<AbortController>();
    pending.set(bearer, requests);
    requests.add(controller);
    try {
      const response = await original(input, { ...init, signal: controller.signal });
      requests.delete(controller);
      if (response.status === 401) expire(bearer);
      return response;
    } finally {
      requests.delete(controller);
      if (!requests.size) pending.delete(bearer);
      signal?.removeEventListener('abort', abort);
    }
  };
}
