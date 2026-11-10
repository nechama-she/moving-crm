import { useEffect, useRef, useState } from 'react';
import { CUSTOMER_SESSION_EXPIRED, customerSessionActive, expireCustomerSession } from './customerSession';

/** One authenticated socket; requests happen on events, never on a polling timer. pageId marks this page's own saves,
 *  which it already shows, so only the move's other open pages load again. */
export function useCustomerUpdates(base: string, key: string, session: string, pageId: string, refresh: (initial?: boolean) => Promise<void>,
                                   onChange?: (change: { change: string; by: string; name: string }) => void) {
  const callback = useRef(refresh);
  callback.current = refresh;
  // What another page changed and who changed it, for the page to show.
  const changeCallback = useRef(onChange);
  changeCallback.current = onChange;
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    if (!session) return;
    let stopped = false;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    // When the connection was lost; changes made meanwhile were missed.
    let closedAt = 0;
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
      let initial = !initialized;
      initialized = true;
      try {
        do { pending = false; await callback.current(initial); initial = false; } while (pending && valid());
      } finally { loading = false; }
    };
    const fallback = () => { if (!initialized && valid()) void update(); };
    const retry = () => {
      clearTimeout(connectionTimer);
      if (!valid()) return;
      closedAt ||= Date.now();
      // The server closes a connection idle for 10 minutes: reconnect at once, without a notice.
      if (failures++ === 0) { void connect(); return; }
      setUnavailable(true);
      fallback();
      // A few retries; after that, the next try waits for the network or for the page to be looked at again.
      if (failures <= 4) timer = setTimeout(() => void connect(), 1000 * 2 ** failures);
    };
    const resume = () => {
      if (failures > 4 && valid() && document.visibilityState === 'visible') { failures = 1; void connect(); }
    };
    window.addEventListener('online', resume);
    document.addEventListener('visibilitychange', resume);
    const connect = async () => {
      if (!valid()) return;
      try {
        const response = await fetch(`${base}/realtime-token`, {method: 'POST',
          headers: {'x-public-link': key, 'x-public-session': session}, signal: controller.signal});
        if (response.status === 401) { expireCustomerSession(session); stop(); return; }
        if (!response.ok) throw new Error('Connection unavailable');
        const {token} = await response.json();
        if (!valid()) return;
        socket = new WebSocket(`${window.__WS_URL__}?token=${encodeURIComponent(token)}`);
        // One fallback for a stalled connection, never a data polling timer.
        connectionTimer = setTimeout(fallback, 5000);
        socket.onopen = () => {
          clearTimeout(connectionTimer);
          if (!valid()) return;
          setUnavailable(false);
          failures = 0;
          // Opening a transport is not a data change, so a quick reconnect loads nothing. After a longer outage,
          // changes may have been missed: load once.
          if (closedAt && Date.now() - closedAt > 5000) void update();
          closedAt = 0;
        };
        socket.onmessage = ({data}) => {
          if (!valid()) return;
          try {
            const event = JSON.parse(data);
            if (event.type === 'customer_move_updated' && event.origin !== pageId) {
              void update();
              if (event.change) changeCallback.current?.({ change: String(event.change), by: String(event.by || ''), name: String(event.name || '') });
            }
          } catch { /* Ignore malformed notifications. */ }
        };
        socket.onclose = retry;
      } catch { if (valid()) retry(); }
    };
    setUnavailable(false);
    fallback(); // Load the page without waiting for the realtime connection.
    if (!window.__WS_URL__) { setUnavailable(true); fallback(); }
    else void connect();
    return () => {
      stop(); window.removeEventListener(CUSTOMER_SESSION_EXPIRED, expired);
      window.removeEventListener('online', resume); document.removeEventListener('visibilitychange', resume);
    };
  }, [base, key, session, pageId]);
  return unavailable;
}
