import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Lead, formatLabel, formatValue } from "./leadUtils";
import ChatMessages from "./ChatMessages";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";

const HIDDEN_FIELDS = new Set(["entry_id", "inbox_url"]);

const USER_FIELDS = ["full_name", "phone_number", "email"];
const MOVE_FIELDS = [
  "pickup_zip",
  "delivery_zip",
  "move_size",
  "when_is_the_move?",
  "are_you_moving_within_the_state_or_out_of_state?",
];
const META_FIELDS = ["leadgen_id", "created_time", "page_id", "form_id", "adgroup_id", "ad_id"];

export default function LeadDetail() {
  const { leadId } = useParams<{ leadId: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const [lead, setLead] = useState<Lead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/leads/${leadId}`, { headers: authHeaders(token) })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setLead)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [leadId]);

  if (loading) return <p style={{ padding: 24 }}>Loading…</p>;
  if (error)
    return <p style={{ padding: 24, color: "red" }}>Error: {error}</p>;
  if (!lead) return <p style={{ padding: 24 }}>Lead not found.</p>;

  // Extract user_id from inbox_url for chat lookup
  const inboxUrl = lead.inbox_url ? String(lead.inbox_url) : "";
  const urlMatch = inboxUrl.match(/\/latest\/(\d+)/);
  const chatUserId = urlMatch ? urlMatch[1] : (lead.user_id ? String(lead.user_id) : "");

  const allKeys = Object.keys(lead).filter((k) => !HIDDEN_FIELDS.has(k));
  const categorized = new Set([...USER_FIELDS, ...MOVE_FIELDS, ...META_FIELDS]);
  const otherFields = allKeys.filter((k) => !categorized.has(k));

  const sectionStyle: React.CSSProperties = {
    marginBottom: 28,
    border: "1px solid #e0e0e0",
    borderRadius: 8,
    overflow: "hidden",
  };
  const sectionHeader: React.CSSProperties = {
    padding: "10px 16px",
    background: "#f5f5f5",
    fontWeight: 700,
    fontSize: 15,
    borderBottom: "1px solid #e0e0e0",
    color: "#333",
  };
  const cellLabel: React.CSSProperties = {
    padding: "10px 16px",
    borderBottom: "1px solid #eee",
    fontWeight: 600,
    width: 180,
    color: "#555",
    verticalAlign: "top",
  };
  const cellValue: React.CSSProperties = {
    padding: "10px 16px",
    borderBottom: "1px solid #eee",
    wordBreak: "break-word",
    userSelect: "text",
  };

  function renderRow(key: string) {
    const val = lead![key];
    if (val == null || val === "") return null;
    const isInbox = key === "inbox_url";
    if (isInbox && !String(val).trim().startsWith("http")) return null;
    return (
      <tr key={key}>
        <td style={cellLabel}>{formatLabel(key)}</td>
        <td style={cellValue}>
          {isInbox ? (
            <a href={String(val)} target="_blank" rel="noopener noreferrer">
              Open Inbox
            </a>
          ) : (
            formatValue(key, val)
          )}
        </td>
      </tr>
    );
  }

  function renderSection(title: string, keys: string[]) {
    const present = keys.filter((k) => allKeys.includes(k));
    if (present.length === 0) return null;
    return (
      <div style={sectionStyle}>
        <div style={sectionHeader}>{title}</div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>{present.map(renderRow)}</tbody>
        </table>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, fontFamily: "sans-serif", maxWidth: 700 }}>
      <button
        onClick={() => navigate("/")}
        style={{
          marginBottom: 16,
          padding: "6px 16px",
          cursor: "pointer",
          border: "1px solid #ccc",
          borderRadius: 4,
          background: "#fff",
          fontSize: 14,
        }}
      >
        ← Back to Leads
      </button>

      <h1 style={{ marginBottom: 24 }}>
        {String(lead.full_name || "Lead Details")}
      </h1>

      {renderSection("User Details", USER_FIELDS)}

      <div style={sectionStyle}>
        <div style={sectionHeader}>Move Details</div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>
            <tr>
              <td style={cellLabel}>Route</td>
              <td style={cellValue}>
                {formatValue("pickup_zip", lead.pickup_zip)} → {formatValue("delivery_zip", lead.delivery_zip)}
              </td>
            </tr>
            {renderRow("move_size")}
            {renderRow("when_is_the_move?")}
            {renderRow("are_you_moving_within_the_state_or_out_of_state?")}
          </tbody>
        </table>
      </div>

      {(otherFields.length > 0 || META_FIELDS.some((k) => allKeys.includes(k))) &&
        renderSection("Other Info", [...META_FIELDS, ...otherFields])}

      {chatUserId || lead.phone_number ? (
        <div style={{ marginTop: 32 }}>
          <h2 style={{ marginBottom: 12 }}>Conversations</h2>
          <ChatMessages userId={chatUserId} userName={String(lead.full_name || "Client")} phoneNumber={lead.phone_number ? String(lead.phone_number) : ""} inboxUrl={inboxUrl} />
        </div>
      ) : null}
    </div>
  );
}
