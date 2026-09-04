import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

const displayPhone = (value: string) => {
  const digits = value.replace(/\D/g, "");
  return digits.length === 10 ? `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}` : value;
};

export default function IgnoredCallNumbersPage() {
  const { token } = useAuth();
  const [numbers, setNumbers] = useState<{ number: string; direction: "from" | "to" | "both" }[]>([]);
  const [input, setInput] = useState("");
  const [direction, setDirection] = useState<"from" | "to" | "both">("both");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/unanswered-messages/ignored-call-numbers`, { headers: authHeaders(token) })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
        setNumbers(body.items || []);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load ignored numbers"))
      .finally(() => setLoading(false));
  }, [token]);

  async function addNumber() {
    if (!input.trim()) return;
    setSaving(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/unanswered-messages/ignored-call-numbers`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ number: input, direction }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
      setNumbers(body.items || []); setInput("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not add number"); }
    finally { setSaving(false); }
  }

  async function removeNumber(number: string, entryDirection: string) {
    setSaving(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/unanswered-messages/ignored-call-numbers/${encodeURIComponent(number)}?direction=${encodeURIComponent(entryDirection)}`, { method: "DELETE", headers: authHeaders(token) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
      setNumbers(body.items || []);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not remove number"); }
    finally { setSaving(false); }
  }

  return <main style={{ padding: 24, width: "100%", maxWidth: 760, margin: "0 auto", boxSizing: "border-box" }}>
    <Link to="/settings" style={{ color: "#0176d3", textDecoration: "none", fontSize: 13 }}>← Back to Settings</Link>
    <h1 style={{ color: "#032d60", fontSize: 24, margin: "18px 0 4px" }}>Ignored Communication Numbers</h1>
    <p style={{ color: "#64748b", margin: "0 0 20px" }}>Messages and missed calls involving these client or destination numbers will not enter the Sales Work Queue.</p>
    <section style={{ border: "1px solid #d8dde6", borderRadius: 8, background: "#fff", overflow: "hidden" }}>
      <div style={{ padding: 16, display: "flex", flexWrap: "wrap", gap: 8, borderBottom: "1px solid #e2e8f0" }}>
        <input value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void addNumber(); }} placeholder="Enter phone number" disabled={saving} style={{ flex: 1, minWidth: 180, border: "1px solid #cbd5e1", borderRadius: 5, padding: "9px 11px", fontSize: 14 }} />
        <select value={direction} onChange={(event) => setDirection(event.target.value as "from" | "to" | "both")} disabled={saving} style={{ border: "1px solid #cbd5e1", borderRadius: 5, padding: "9px 11px", background: "#fff" }}>
          <option value="from">From this number</option>
          <option value="to">To this number</option>
          <option value="both">Both directions</option>
        </select>
        <button type="button" onClick={() => void addNumber()} disabled={saving || !input.trim()} style={{ border: 0, borderRadius: 5, padding: "9px 15px", background: "#0176d3", color: "#fff", fontWeight: 700 }}>Add number</button>
      </div>
      {error ? <p style={{ color: "#b91c1c", padding: "0 16px" }}>{error}</p> : null}
      {loading ? <p style={{ color: "#64748b", padding: 16 }}>Loading…</p> : null}
      {!loading && numbers.length === 0 ? <p style={{ color: "#64748b", padding: 16 }}>No ignored numbers.</p> : null}
      {numbers.map((entry) => <div key={`${entry.number}:${entry.direction}`} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "12px 16px", borderTop: "1px solid #e2e8f0" }}>
        <div><strong style={{ color: "#334155" }}>{displayPhone(entry.number)}</strong><div style={{ color: "#64748b", fontSize: 12, marginTop: 3 }}>{entry.direction === "from" ? "Ignore messages/calls from this number" : entry.direction === "to" ? "Ignore messages/calls to this number" : "Ignore both directions"}</div></div>
        <button type="button" disabled={saving} onClick={() => void removeNumber(entry.number, entry.direction)} style={{ border: "1px solid #dc2626", borderRadius: 5, background: "#fff", color: "#dc2626", padding: "6px 10px", fontWeight: 700 }}>Remove</button>
      </div>)}
    </section>
  </main>;
}
