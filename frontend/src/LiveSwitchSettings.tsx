import { useEffect, useState } from "react";
import { authHeaders, useAuth } from "./AuthContext";
import { API_BASE } from "./apiConfig";

type SparkTemplate = {
  id: string;
  name?: string;
  title?: string;
  description?: string;
  codeName?: string;
};

export default function LiveSwitchSettings() {
  const { token } = useAuth();
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [callback, setCallback] = useState(`${window.location.origin}/liveswitch/callback`);
  const [hasSecret, setHasSecret] = useState(false);
  const [authorized, setAuthorized] = useState(false);
  const [sparkTemplateId, setSparkTemplateId] = useState("");
  const [templates, setTemplates] = useState<SparkTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [templateNotice, setTemplateNotice] = useState("");
  const [busy, setBusy] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetch(`${API_BASE}/api/liveswitch/settings`, { headers: authHeaders(token), cache: "no-store" })
      .then(async response => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not load LiveSwitch settings.");
        if (!active) return;
        setClientId(data.client_id || "");
        if (data.redirect_uri) setCallback(data.redirect_uri);
        setHasSecret(data.has_secret);
        setAuthorized(data.authorization_saved);
        setSparkTemplateId(data.spark_template_id || "");
        setLoaded(true);

        if (data.authorization_saved) {
          setLoadingTemplates(true);
          fetch(`${API_BASE}/api/liveswitch/spark-templates`, { headers: authHeaders(token) })
            .then(res => res.ok ? res.json() : [])
            .then(list => {
              if (active) setTemplates(Array.isArray(list) ? list : []);
            })
            .catch(() => {})
            .finally(() => { if (active) setLoadingTemplates(false); });
        }
      })
      .catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [token]);

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setTemplateNotice("");
    try {
      const saved = await fetch(`${API_BASE}/api/liveswitch/settings`, {
        method: "PUT", headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          client_secret: secret,
          redirect_uri: callback,
          spark_template_id: sparkTemplateId,
        }),
      });
      if (!saved.ok) {
        const data = await saved.json();
        throw new Error(data.detail || "Could not save LiveSwitch settings.");
      }
      setSecret("");
      setHasSecret(true);
      setAuthorized(false);
      const response = await fetch(`${API_BASE}/api/liveswitch/oauth/start`, {
        headers: authHeaders(token), credentials: "include", cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not connect to LiveSwitch.");
      sessionStorage.setItem('liveswitch-connect-trace',JSON.stringify(data.trace || []));
      window.location.assign(data.authorization_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect to LiveSwitch.");
    } finally { setBusy(false); }
  }

  async function saveSparkTemplate(selectedId: string) {
    setSparkTemplateId(selectedId);
    setSavingTemplate(true);
    setTemplateNotice("");
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/liveswitch/settings`, {
        method: "PUT", headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          client_secret: "",
          redirect_uri: callback,
          spark_template_id: selectedId,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Could not save Spark template.");
      }
      setTemplateNotice("Spark template saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save Spark template.");
    } finally {
      setSavingTemplate(false);
    }
  }

  return <section style={{ border: "1px solid #dddbda", borderRadius: 4, background: "white", padding: 14 }}>
    <h2 style={{ margin: "0 0 8px", fontSize: 13, color: "#3e3e3c", textTransform: "uppercase" }}>LiveSwitch</h2>
    <p style={{ fontSize: 13, color: "#706e6b" }}>
      {authorized ? "LiveSwitch authorization saved. You can reconnect here if needed." : "Paste the Client ID and Client Secret from the LiveSwitch email, then connect and sign in."}
    </p>

    {authorized && (
      <div style={{ marginBottom: 16, padding: 12, background: "#f8fafc", borderRadius: 6, border: "1px solid #e2e8f0" }}>
        <label style={label}>Spark Template (AI Prompts)
          <select
            style={input}
            value={sparkTemplateId}
            disabled={loadingTemplates || savingTemplate}
            onChange={(e) => void saveSparkTemplate(e.target.value)}
          >
            <option value="">{loadingTemplates ? "Loading templates..." : "-- Select a Spark template --"}</option>
            {templates.map((tpl) => (
              <option key={tpl.id} value={tpl.id}>
                {tpl.name || tpl.title || tpl.codeName || tpl.id}
              </option>
            ))}
          </select>
        </label>
        {templateNotice && <p style={{ color: "#2e844a", fontSize: 12, margin: "6px 0 0" }}>{templateNotice}</p>}
      </div>
    )}

    <form onSubmit={connect} style={{ display: "grid", gap: 10 }}>
      <label style={label}>Client ID
        <input style={input} value={clientId} onChange={e => setClientId(e.target.value)} required disabled={busy || !loaded} autoComplete="off" />
      </label>
      <label style={label}>Client Secret
        <input style={input} type="password" value={secret} onChange={e => setSecret(e.target.value)} required={!hasSecret}
          placeholder={hasSecret ? "Saved securely — leave blank to keep" : "Paste from the email"} disabled={busy || !loaded} autoComplete="new-password" />
      </label>
      <details>
        <summary style={{ fontSize: 12, color: "#0176d3", cursor: "pointer" }}>Connection details</summary>
        <p style={{ fontSize: 12 }}>Sign-in domain: id.liveswitch.com</p>
        <label style={label}>Return address (filled automatically)
          <input style={input} type="url" value={callback} onChange={e => setCallback(e.target.value)} required disabled={busy || !loaded} />
        </label>
        <p style={{ fontSize: 12, color: "#706e6b" }}>If LiveSwitch reports an unapproved return address, this is the address their support team needs to approve.</p>
      </details>
      {error && <p role="alert" style={{ color: "#ba0517", fontSize: 13, margin: 0 }}>{error}</p>}
      <button className="slds-button" type="submit" disabled={busy || !loaded} style={{ background: "#0176d3", color: "white", border: 0, borderRadius: 4, padding: "9px 12px", cursor: "pointer" }}>
        {busy ? "Please wait…" : authorized ? "Reconnect LiveSwitch" : "Save & Connect LiveSwitch"}
      </button>
    </form>
  </section>;
}

const label: React.CSSProperties = { display: "grid", gap: 5, fontSize: 13, color: "#032d60" };
const input: React.CSSProperties = { width: "100%", boxSizing: "border-box", border: "1px solid #c9c9c9", borderRadius: 4, padding: 8 };
