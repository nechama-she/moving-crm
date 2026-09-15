import { useEffect, useState } from "react";

export default function LiveSwitchCallbackPage() {
  const [message, setMessage] = useState("Connecting LiveSwitch...");

  useEffect(() => {
    let cancelled = false;
    void fetch(`/api/liveswitch/oauth/callback${window.location.search}`)
      .then(async (response) => {
        const body = await response.text();
        if (!response.ok) {
          try {
            const detail = JSON.parse(body)?.detail;
            throw new Error(detail || "LiveSwitch authorization failed.");
          } catch (error) {
            throw error instanceof Error ? error : new Error("LiveSwitch authorization failed.");
          }
        }
        if (!cancelled) setMessage("LiveSwitch connected. You can close this window and return to the CRM.");
      })
      .catch((error) => {
        if (!cancelled) setMessage(error instanceof Error ? error.message : "LiveSwitch authorization failed.");
      });
    return () => { cancelled = true; };
  }, []);

  return <main style={{ padding: 32, color: "#032d60" }}>{message}</main>;
}
