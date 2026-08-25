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
  const [numbers, setNumbers] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/unanswered-messages/ignored-call-numbers`, { headers: authHeaders(token) })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
        setNumbers(body.numbers || []);
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
        body: JSON.stringify({ number: input }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
      setNumbers(body.numbers || []); setInput("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not add number"); }
    finally { setSaving(false); }
  }

  async function removeNumber(number: string) {
    setSaving(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/unanswered-messages/ignored-call-numbers/${encodeURIComponent(number)}`, { method: "DELETE", headers: authHeaders(token) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
      setNumbers(body.numbers || []);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not remove number"); }
    finally { setSaving(false); }
  }

  return <main style={{ padding: 24, width: "100%", maxWidth: 760, margin: "0 auto", boxSizing: "border-box" }}>
    <Link to="/settings" style={{ color: "#0176d3", textDecoration: "none", fontSize: 13 }}>← Back to Settings</Link>
    <h1 style={{ color: "#032d60", fontSize: 24, margin: "18px 0 4px" }}>Ignored Communication Numbers</h1>
    <p style={{ color: "#64748b", margin: "0 0 20px" }}>Messages and missed calls received on these destination numbers will not enter the Sales Work Queue.</p>
    <section style={{ border: "1px solid #d8dde6", borderRadius: 8, background: "#fff", overflow: "hidden" }}>
      <div style={{ padding: 16, display: "flex", gap: 8, borderBottom: "1px solid #e2e8f0" }}>
        <input value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void addNumber(); }} placeholder="Enter destination phone number" disabled={saving} style={{ flex: 1, minWidth: 180, border: "1px solid #cbd5e1", borderRadius: 5, padding: "9px 11px", fontSize: 14 }} />
        <button type="button" onClick={() => void addNumber()} disabled={saving || !input.trim()} style={{ border: 0, borderRadius: 5, padding: "9px 15px", background: "#0176d3", color: "#fff", fontWeight: 700 }}>Add number</button>
      </div>
      {error ? <p style={{ color: "#b91c1c", padding: "0 16px" }}>{error}</p> : null}
      {loading ? <p style={{ color: "#64748b", padding: 16 }}>Loading…</p> : null}
      {!loading && numbers.length === 0 ? <p style={{ color: "#64748b", padding: 16 }}>No ignored numbers.</p> : null}
      {numbers.map((number) => <div key={number} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "12px 16px", borderTop: "1px solid #e2e8f0" }}>
        <strong style={{ color: "#334155" }}>{displayPhone(number)}</strong>
        <button type="button" disabled={saving} onClick={() => void removeNumber(number)} style={{ border: "1px solid #dc2626", borderRadius: 5, background: "#fff", color: "#dc2626", padding: "6px 10px", fontWeight: 700 }}>Remove</button>
      </div>)}
    </section>
  </main>;
}
