import { useEffect } from "react";

export default function LiveSwitchCallbackPage() {
  useEffect(() => {
    window.location.replace(`/api/liveswitch/oauth/callback${window.location.search}`);
  }, []);

  return <main style={{ padding: 32, color: "#032d60" }}>Connecting LiveSwitch...</main>;
}
