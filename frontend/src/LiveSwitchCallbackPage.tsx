import { useEffect } from "react";
import { API_BASE } from "./apiConfig";

export default function LiveSwitchCallbackPage() {
  useEffect(() => {
    // Navigate once; an effect fetch can exchange the same one-use code twice in StrictMode.
    window.location.replace(`${API_BASE}/api/liveswitch/oauth/callback${window.location.search}`);
  }, []);

  return <main style={{ padding: 32, color: "#032d60" }}>Connecting LiveSwitch...</main>;
}
