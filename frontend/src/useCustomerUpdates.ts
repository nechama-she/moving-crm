import { useEffect, useRef, useState } from 'react';
import { CUSTOMER_SESSION_EXPIRED, customerSessionActive, expireCustomerSession } from './customerSession';

/** One authenticated socket; requests happen on events, never on a polling timer. */
export function useCustomerUpdates(base: string, key: string, session: string, refresh: () => Promise<void>) {
  const callback = useRef(refresh);
  callback.current = refresh;
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    if (!session) return;
    let stopped = false;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let loading = false;
    let pending = false;
    const controller = new AbortController();
    let initialized = false;
    let connectionTimer: ReturnType<typeof setTimeout> | undefined;
    const valid = () => !stopped && customerSessionActive(session);
    const stop = () => {
      stopped = true; controller.abort(); clearTimeout(timer); clearTimeout(connectionTimer); socket?.close();
    };
    const expired = (event: Event) => { if ((event as CustomEvent).detail === session) stop(); };
    window.addEventListener(CUSTOMER_SESSION_EXPIRED, expired);
    const update = async () => {
      if (!valid()) return;
      if (loading) { pending = true; return; }
      loading = true;
      initialized = true;
      try {
        do { pending = false; await callback.current(); } while (pending && valid());
      } finally { loading = false; }
    };
    const fallback = () => { if (!initialized && valid()) void update(); };
    const retry = () => {
      clearTimeout(connectionTimer);
      if (!valid()) return;
      setUnavailable(true);
      fallback();
      // Bounded reconnects after a broken connection, not repeated data requests.
      if (++failures <= 3) timer = setTimeout(() => void connect(), 1000 * 2 ** failures);
    };
    const connect = async () => {
      if (!valid()) return;
      try {
        const response = await fetch(`${base}/realtime-token`, {method: 'POST',
          headers: {'x-public-link': key, 'x-public-session': session}, signal: controller.signal});
        if (response.status === 401 || response.status === 404) { expireCustomerSession(session); stop(); return; }
        if (!response.ok) throw new Error('Connection unavailable');
        const {token} = await response.json();
        if (!valid()) return;
        socket = new WebSocket(`${window.__WS_URL__}?token=${encodeURIComponent(token)}`);
        // One fallback for a stalled connection, never a data polling timer.
        connectionTimer = setTimeout(fallback, 5000);
        socket.onopen = () => {
          clearTimeout(connectionTimer);
          if (!valid()) return;
          failures = 0; setUnavailable(false);
          // Close the gap between the initial load and subscription (also on reconnect).
          void update();
        };
        socket.onmessage = ({data}) => {
          if (!valid()) return;
          try { if (JSON.parse(data).type === 'customer_move_updated') void update(); }
          catch { /* Ignore malformed notifications. */ }
        };
        socket.onclose = retry;
      } catch { if (valid()) retry(); }
    };
    setUnavailable(false);
    if (!window.__WS_URL__) { setUnavailable(true); fallback(); }
    else void connect();
    return () => { stop(); window.removeEventListener(CUSTOMER_SESSION_EXPIRED, expired); };
  }, [base, key, session]);
  return unavailable;
}
