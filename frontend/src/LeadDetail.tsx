import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Lead, formatLabel, formatValue } from "./leadUtils";
import ChatMessages from "./ChatMessages";
import FollowupPanel from "./FollowupPanel";
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
    return <p style={{ padding: 24, color: "#ba0517" }}>Error: {error}</p>;
  if (!lead) return <p style={{ padding: 24 }}>Lead not found.</p>;

  // Extract user_id from inbox_url for chat lookup
  const inboxUrl = lead.inbox_url ? String(lead.inbox_url) : "";
  const urlMatch = inboxUrl.match(/\/latest\/(\d+)/);
  const chatUserId = urlMatch ? urlMatch[1] : (lead.user_id ? String(lead.user_id) : "");
  const messengerInboxUrl = inboxUrl || (chatUserId ? `https://www.facebook.com/latest/${chatUserId}` : "");

  const allKeys = Object.keys(lead).filter((k) => !HIDDEN_FIELDS.has(k));
  const categorized = new Set([...USER_FIELDS, ...MOVE_FIELDS, ...META_FIELDS]);
  const otherFields = allKeys.filter((k) => !categorized.has(k));

  const sectionStyle: React.CSSProperties = {
    marginBottom: 16,
    border: "1px solid #dddbda",
    borderRadius: 4,
    overflow: "hidden",
    background: "#fff",
    boxShadow: "0 1px 2px rgba(0,0,0,.06)",
  };
  const sectionHeader: React.CSSProperties = {
    padding: "10px 16px",
    background: "#f3f2f2",
    fontWeight: 700,
    fontSize: 12,
    borderBottom: "1px solid #dddbda",
    color: "#3e3e3c",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  };
  const cellLabel: React.CSSProperties = {
    padding: "9px 16px",
    borderBottom: "1px solid #f3f2f2",
    fontWeight: 600,
    width: 190,
    color: "#706e6b",
    verticalAlign: "top",
    fontSize: 13,
  };
  const cellValue: React.CSSProperties = {
    padding: "9px 16px",
    borderBottom: "1px solid #f3f2f2",
    wordBreak: "break-word",
    userSelect: "text",
    fontSize: 13,
    color: "#181818",
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
    <div style={{ padding: 20, fontFamily: "inherit", maxWidth: 960, overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <button
        onClick={() => navigate("/")}
        style={{
          marginBottom: 14,
          padding: "5px 14px",
          cursor: "pointer",
          border: "1px solid #dddbda",
          borderRadius: 4,
          background: "#fff",
          fontSize: 13,
          color: "#0176d3",
          fontWeight: 500,
        }}
      >
        ← Back to Leads
      </button>

      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        <h1 style={{ marginBottom: 16, flex: 1, fontSize: 20, color: "#032d60" }}>
          {String(lead.full_name || "Lead Details")}
        </h1>
        <div style={{ width: 320, flexShrink: 0 }}>
          <FollowupPanel leadId={leadId!} />
        </div>
      </div>

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
          <ChatMessages
            userId={chatUserId}
            userName={String(lead.full_name || "Client")}
            phoneNumber={lead.phone_number ? String(lead.phone_number) : ""}
            inboxUrl={messengerInboxUrl}
            aircallNumberId={lead.aircall_number_id ? String(lead.aircall_number_id) : ""}
            companyName={lead.company_name ? String(lead.company_name) : ""}
          />
        </div>
      ) : null}
    </div>
  );
}
