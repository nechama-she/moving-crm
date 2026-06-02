import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Lead, formatLabel, formatValue } from "./leadUtils";
import ChatMessages from "./ChatMessages";
import FollowupPanel from "./FollowupPanel";
import TasksPanel from "./TasksPanel";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";

const HIDDEN_FIELDS = new Set(["entry_id", "inbox_url"]);

type CompanyOption = {
  id: string;
  name: string;
};

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
  const { token, user } = useAuth();
  const [lead, setLead] = useState<Lead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"conversations" | "activity">("conversations");
  const [editingUser, setEditingUser] = useState(false);
  const [editName, setEditName] = useState("");
  const [editPhone, setEditPhone] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [savingUser, setSavingUser] = useState(false);
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [companiesError, setCompaniesError] = useState("");
  const [editCompanyId, setEditCompanyId] = useState("");
  const [savingCompany, setSavingCompany] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/leads/${leadId}`, { headers: authHeaders(token) })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setLead(data);
        setEditCompanyId(String(data?.company_id || ""));
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [leadId]);

  useEffect(() => {
    fetch(`${API_BASE}/api/companies/mine`, { headers: authHeaders(token) })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: unknown) => {
        const rows = Array.isArray(data) ? data : [];
        const nextCompanies = rows
          .map((row) => {
            const item = row as Record<string, unknown>;
            return {
              id: String(item.id || ""),
              name: String(item.name || ""),
            };
          })
          .filter((c) => c.id);
        setCompanies(nextCompanies);
        setCompaniesError("");
      })
      .catch((err) => setCompaniesError(err.message));
  }, [token]);

  if (loading) return <p style={{ padding: 24 }}>Loading…</p>;
  if (error)
    return <p style={{ padding: 24, color: "#ba0517" }}>Error: {error}</p>;
  if (!lead) return <p style={{ padding: 24 }}>Lead not found.</p>;
  const canEditCompany = user?.role === "admin";

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

      <div style={{ display: "flex", gap: 20, alignItems: "flex-start", marginBottom: 16 }}>
        <div style={{ flex: 1 }} />
        <div style={{ width: 320, flexShrink: 0 }}>
          <FollowupPanel leadId={leadId!} />
        </div>
      </div>

      {/* Client highlights card */}
      {(() => {
        const name = String(lead.full_name || "").trim();
        const phone = String(lead.phone_number || "").trim();
        const email = String(lead.email || "").trim();
        const initials = name
          ? name.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("")
          : "?";

        function startEditUser() {
          setEditName(name);
          setEditPhone(phone);
          setEditEmail(email);
          setEditingUser(true);
        }

        async function saveUser() {
          setSavingUser(true);
          try {
            const res = await fetch(`${API_BASE}/api/leads/${leadId}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json", ...authHeaders(token) },
              body: JSON.stringify({
                full_name: editName,
                phone_number: editPhone,
                email: editEmail,
              }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const updated = await res.json();
            setLead(updated);
            setEditingUser(false);
          } catch (e) {
            alert(`Failed to save: ${e instanceof Error ? e.message : "error"}`);
          } finally {
            setSavingUser(false);
          }
        }

        async function saveCompany() {
          if (!editCompanyId) return;
          setSavingCompany(true);
          try {
            const res = await fetch(`${API_BASE}/api/leads/${leadId}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json", ...authHeaders(token) },
              body: JSON.stringify({
                company_id: editCompanyId,
              }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const updated = await res.json();
            setLead(updated);
            setEditCompanyId(String(updated.company_id || ""));
          } catch (e) {
            alert(`Failed to save company: ${e instanceof Error ? e.message : "error"}`);
          } finally {
            setSavingCompany(false);
          }
        }

        const tile: React.CSSProperties = {
          flex: 1,
          minWidth: 200,
          padding: "12px 14px",
          background: "#f3f6f9",
          border: "1px solid #e5e9ed",
          borderRadius: 6,
          display: "flex",
          alignItems: "center",
          gap: 10,
        };
        const tileLabel: React.CSSProperties = {
          fontSize: 10,
          fontWeight: 700,
          color: "#706e6b",
          textTransform: "uppercase",
          letterSpacing: 0.5,
        };

        return (
          <div style={{ ...sectionStyle, padding: 18 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 14 }}>
              <div
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: "50%",
                  background: "#0176d3",
                  color: "#fff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: 700,
                  fontSize: 18,
                  flexShrink: 0,
                }}
              >
                {initials}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                {editingUser ? (
                  <input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder="Full name"
                    style={{
                      width: "100%",
                      fontSize: 18,
                      fontWeight: 700,
                      color: "#032d60",
                      padding: "4px 8px",
                      border: "1px solid #dddbda",
                      borderRadius: 4,
                    }}
                  />
                ) : (
                  <div style={{ fontSize: 18, fontWeight: 700, color: "#032d60" }}>
                    {name || "—"}
                  </div>
                )}
              </div>
              {editingUser ? (
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    type="button"
                    onClick={() => setEditingUser(false)}
                    disabled={savingUser}
                    style={{ padding: "5px 12px", border: "1px solid #dddbda", borderRadius: 4, background: "#fff", fontSize: 12, cursor: "pointer" }}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={saveUser}
                    disabled={savingUser}
                    style={{ padding: "5px 12px", border: "1px solid #0176d3", borderRadius: 4, background: "#0176d3", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                  >
                    {savingUser ? "Saving…" : "Save"}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={startEditUser}
                  title="Edit"
                  style={{ padding: "5px 10px", border: "1px solid #dddbda", borderRadius: 4, background: "#fff", fontSize: 12, color: "#0176d3", cursor: "pointer" }}
                >
                  ✎ Edit
                </button>
              )}
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              <div style={tile}>
                <span style={{ fontSize: 18 }}>📞</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={tileLabel}>Phone</div>
                  {editingUser ? (
                    <input
                      value={editPhone}
                      onChange={(e) => setEditPhone(e.target.value)}
                      placeholder="Phone number"
                      style={{ width: "100%", fontSize: 14, padding: "3px 6px", border: "1px solid #dddbda", borderRadius: 4 }}
                    />
                  ) : phone ? (
                    <a href={`tel:${phone}`} style={{ fontSize: 14, color: "#0176d3", fontWeight: 600, textDecoration: "none" }}>
                      {phone}
                    </a>
                  ) : (
                    <span style={{ fontSize: 14, color: "#706e6b" }}>—</span>
                  )}
                </div>
              </div>
              <div style={tile}>
                <span style={{ fontSize: 18 }}>✉️</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={tileLabel}>Email</div>
                  {editingUser ? (
                    <input
                      value={editEmail}
                      onChange={(e) => setEditEmail(e.target.value)}
                      placeholder="Email address"
                      style={{ width: "100%", fontSize: 14, padding: "3px 6px", border: "1px solid #dddbda", borderRadius: 4 }}
                    />
                  ) : email ? (
                    <a href={`mailto:${email}`} style={{ fontSize: 14, color: "#0176d3", fontWeight: 600, textDecoration: "none", wordBreak: "break-all" }}>
                      {email}
                    </a>
                  ) : (
                    <span style={{ fontSize: 14, color: "#706e6b" }}>—</span>
                  )}
                </div>
              </div>

              <div style={tile}>
                <span style={{ fontSize: 18 }}>🏢</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={tileLabel}>Company</div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <select
                      value={editCompanyId}
                      onChange={(e) => setEditCompanyId(e.target.value)}
                      disabled={!canEditCompany}
                      style={{
                        flex: 1,
                        minWidth: 0,
                        fontSize: 13,
                        padding: "4px 6px",
                        border: "1px solid #dddbda",
                        borderRadius: 4,
                        background: "#fff",
                      }}
                    >
                      <option value="" disabled>
                        Select company
                      </option>
                      {companies.map((company) => (
                        <option key={company.id} value={company.id}>
                          {company.name}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={saveCompany}
                      disabled={
                        !canEditCompany ||
                        savingCompany ||
                        !editCompanyId ||
                        editCompanyId === String(lead.company_id || "")
                      }
                      style={{
                        padding: "4px 10px",
                        border: "1px solid #0176d3",
                        borderRadius: 4,
                        background: "#0176d3",
                        color: "#fff",
                        fontSize: 12,
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      {savingCompany ? "Saving…" : "Save"}
                    </button>
                  </div>
                  {companiesError ? (
                    <div style={{ marginTop: 4, color: "#ba0517", fontSize: 12 }}>{companiesError}</div>
                  ) : !canEditCompany ? (
                    <div style={{ marginTop: 4, color: "#706e6b", fontSize: 12 }}>Only admins can change company.</div>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        );
      })()}

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

      {/* Tabbed panel: Conversations / Activity */}
      <div style={{ marginTop: 32, border: "1px solid #dddbda", borderRadius: 4, background: "#fff", overflow: "hidden" }}>
        <div style={{ display: "flex", borderBottom: "1px solid #dddbda", background: "#f3f2f2" }}>
          <button
            onClick={() => setActiveTab("conversations")}
            style={{
              padding: "10px 18px",
              border: "none",
              borderBottom: activeTab === "conversations" ? "3px solid #0176d3" : "3px solid transparent",
              background: activeTab === "conversations" ? "#fff" : "transparent",
              fontWeight: 600,
              fontSize: 13,
              color: activeTab === "conversations" ? "#032d60" : "#3e3e3c",
              cursor: "pointer",
            }}
          >
            Conversations
          </button>
          <button
            onClick={() => setActiveTab("activity")}
            style={{
              padding: "10px 18px",
              border: "none",
              borderBottom: activeTab === "activity" ? "3px solid #0176d3" : "3px solid transparent",
              background: activeTab === "activity" ? "#fff" : "transparent",
              fontWeight: 600,
              fontSize: 13,
              color: activeTab === "activity" ? "#032d60" : "#3e3e3c",
              cursor: "pointer",
            }}
          >
            Activity
          </button>
        </div>
        <div style={{ padding: 16 }}>
          {activeTab === "conversations" ? (
            chatUserId || lead.phone_number ? (
              <ChatMessages
                userId={chatUserId}
                userName={String(lead.full_name || "Client")}
                phoneNumber={lead.phone_number ? String(lead.phone_number) : ""}
                inboxUrl={messengerInboxUrl}
                aircallNumberId={lead.aircall_number_id ? String(lead.aircall_number_id) : ""}
                companyName={lead.company_name ? String(lead.company_name) : ""}
              />
            ) : (
              <p style={{ color: "#706e6b", fontSize: 13 }}>No conversation available for this lead.</p>
            )
          ) : (
            <TasksPanel leadId={leadId!} token={token} />
          )}
        </div>
      </div>
    </div>
  );
}
