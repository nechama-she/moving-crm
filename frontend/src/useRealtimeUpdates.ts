import { useEffect, useRef } from "react";

declare global { interface Window { __WS_URL__?: string; } }

export type RealtimeEvent = { type: "communication_updated"; lead_id: string; channel: string; direction: string; occurred_at: string };

export function useRealtimeUpdates(token: string | null, onEvent: (event: RealtimeEvent) => void) {
  const callbackRef = useRef(onEvent);
  callbackRef.current = onEvent;
  useEffect(() => {
    if (!token || !window.__WS_URL__) return;
    let socket: WebSocket | null = null;
    let stopped = false;
    let retry = 1000;
    let timer = 0;
    const connect = () => {
      socket = new WebSocket(`${window.__WS_URL__}?token=${encodeURIComponent(token)}`);
      socket.onopen = () => { retry = 1000; };
      socket.onmessage = ({ data }) => {
        try {
          const event = JSON.parse(data) as RealtimeEvent;
          if (event.type === "communication_updated") callbackRef.current(event);
        } catch { /* ignore malformed events */ }
      };
      socket.onclose = () => {
        if (stopped) return;
        timer = window.setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30000);
      };
    };
    connect();
    return () => { stopped = true; window.clearTimeout(timer); socket?.close(); };
  }, [token]);
}
