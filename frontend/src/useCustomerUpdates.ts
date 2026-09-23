import { useEffect, useRef, useState } from 'react';

/** One authenticated socket; requests happen on events, never on a polling timer. */
export function useCustomerUpdates(base: string, key: string, session: string, refresh: () => Promise<void>) {
  const callback = useRef(refresh);
  callback.current = refresh;
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    if (!session) return;
    if (!window.__WS_URL__) { setUnavailable(true); return; }
    let stopped = false;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let loading = false;
    let pending = false;
    const controller = new AbortController();
    const update = async () => {
      if (loading) { pending = true; return; }
      loading = true;
      try {
        do { pending = false; await callback.current(); } while (pending && !stopped);
      } finally { loading = false; }
    };
    const retry = () => {
      if (stopped) return;
      setUnavailable(true);
      // Bounded reconnects after a broken connection, not repeated data requests.
      if (++failures <= 3) timer = setTimeout(() => void connect(), 1000 * 2 ** failures);
    };
    const connect = async () => {
      try {
        const response = await fetch(`${base}/realtime-token`, {method: 'POST',
          headers: {'x-public-link': key, 'x-public-session': session}, signal: controller.signal});
        if (response.status === 401 || response.status === 404) { setUnavailable(true); return; }
        if (!response.ok) throw new Error('Connection unavailable');
        const {token} = await response.json();
        if (stopped) return;
        socket = new WebSocket(`${window.__WS_URL__}?token=${encodeURIComponent(token)}`);
        socket.onopen = () => {
          if (stopped) return;
          failures = 0; setUnavailable(false);
          // Close the gap between the initial load and subscription (also on reconnect).
          void update();
        };
        socket.onmessage = ({data}) => {
          if (stopped) return;
          try { if (JSON.parse(data).type === 'customer_move_updated') void update(); }
          catch { /* Ignore malformed notifications. */ }
        };
        socket.onclose = retry;
      } catch { if (!stopped) retry(); }
    };
    setUnavailable(false);
    void connect();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); socket?.close(); };
  }, [base, key, session]);
  return unavailable;
}
