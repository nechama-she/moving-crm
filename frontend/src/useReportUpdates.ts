import { useEffect, useRef, useState } from 'react';
import { authHeaders } from './AuthContext';

/** One authenticated socket; requests happen on events, never on a polling timer. */
export function useReportUpdates(base: string, token: string | null, refresh: () => Promise<void>) {
  const callback = useRef(refresh);
  callback.current = refresh;
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    if (!token) return;
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
        const response = await fetch(`${base}/report-events-token`, {method: 'POST',
          headers: authHeaders(token), signal: controller.signal});
        if (response.status === 401 || response.status === 404) { setUnavailable(true); return; }
        if (!response.ok) throw new Error('Connection unavailable');
        const {token: socketToken} = await response.json();
        if (stopped) return;
        socket = new WebSocket(`${window.__WS_URL__}?token=${encodeURIComponent(socketToken)}`);
        socket.onopen = () => {
          if (stopped) return;
          failures = 0; setUnavailable(false);
          // Close the gap between the initial load and subscription (also on reconnect).
          void update();
        };
        socket.onmessage = ({data}) => {
          if (stopped) return;
          try { if (JSON.parse(data).type === 'report_updated') void update(); }
          catch { /* Ignore malformed notifications. */ }
        };
        socket.onclose = retry;
      } catch { if (!stopped) retry(); }
    };
    setUnavailable(false);
    void connect();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); socket?.close(); };
  }, [base, token]);
  return unavailable;
}
