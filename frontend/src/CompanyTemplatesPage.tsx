import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Company = { id: string; name: string };

type TemplateKey =
  | "welcome_sms"
  | "rep_assignment_sms"
  | "day2_followup_sms"
  | "day3_followup_sms";

type TemplatesResponse = {
  company_id: string;
  welcome_sms: string;
  rep_assignment_sms: string;
  day2_followup_sms: string;
  day3_followup_sms: string;
  updated_by: string;
  updated_at: string;
  defaults: Record<TemplateKey, string>;
};

const FIELDS: { key: TemplateKey; label: string; description: string; placeholders: string }[] = [
  {
    key: "welcome_sms",
    label: "Welcome SMS",
    description: "Sent automatically when a new lead is created.",
    placeholders: "{first_name}, {company_name}, {company_phone}, {smartmoving_id}",
  },
  {
    key: "rep_assignment_sms",
    label: "Rep Assignment SMS",
    description: "Sent when a lead is assigned to a sales rep.",
    placeholders: "{first_name}, {rep_name}, {company_name}, {company_phone}",
  },
  {
    key: "day2_followup_sms",
    label: "Day 2 Followup SMS",
    description: "Sent ~2 days after lead creation if the client has not responded.",
    placeholders: "{first_name}, {company_name}",
  },
  {
    key: "day3_followup_sms",
    label: "Day 3 Followup SMS",
    description: "Sent ~3 days after lead creation if the client has not responded.",
    placeholders: "{first_name}, {company_name}",
  },
];

export default function CompanyTemplatesPage() {
  const { token, user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const [data, setData] = useState<TemplatesResponse | null>(null);
  const [values, setValues] = useState<Record<TemplateKey, string>>({
    welcome_sms: "",
    rep_assignment_sms: "",
    day2_followup_sms: "",
    day3_followup_sms: "",
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/companies/mine`, { headers: authHeaders(token) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as Company[];
        const sorted = (data || []).sort((a, b) => a.name.localeCompare(b.name));
        setCompanies(sorted);
        if (sorted.length && !companyId) setCompanyId(sorted[0].id);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load companies");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!companyId) return;
    void loadTemplates(companyId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  async function loadTemplates(cid: string) {
    setLoading(true);
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/companies/${cid}/templates`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = (await res.json()) as TemplatesResponse;
      setData(payload);
      setValues({
        welcome_sms: payload.welcome_sms,
        rep_assignment_sms: payload.rep_assignment_sms,
        day2_followup_sms: payload.day2_followup_sms,
        day3_followup_sms: payload.day3_followup_sms,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load templates");
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    if (!companyId || !isAdmin) return;
    setSaving(true);
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/companies/${companyId}/templates`, {
        method: "PUT",
        headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const payload = (await res.json()) as TemplatesResponse;
      setData(payload);
      setInfo("Saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  function resetToDefault(key: TemplateKey) {
    if (!data) return;
    setValues((prev) => ({ ...prev, [key]: "" }));
    setInfo(`Cleared ${key} — will use system default on save.`);
  }

  const selectedCompanyName = useMemo(
    () => companies.find((c) => c.id === companyId)?.name || "",
    [companies, companyId],
  );

  return (
    <div style={{ padding: "20px 24px", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>SMS Templates</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b", fontSize: 13 }}>
        Edit the SMS messages the system sends automatically per company. Leave a field blank to use the system default.
      </p>

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <label style={{ fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>Company</label>
        <select
          value={companyId}
          onChange={(e) => setCompanyId(e.target.value)}
          style={{ padding: "6px 8px", border: "1px solid #c9c7c5", borderRadius: 4, fontSize: 13, minWidth: 240 }}
        >
          {companies.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        {!isAdmin && (
          <span style={{ color: "#ba0517", fontSize: 12 }}>Read-only — admin required to save.</span>
        )}
      </div>

      {error && <div style={errorBox}>{error}</div>}
      {info && <div style={infoBox}>{info}</div>}

      {loading ? (
        <div style={{ padding: 24, color: "#706e6b" }}>Loading…</div>
      ) : !data ? (
        <div style={{ padding: 24, color: "#706e6b" }}>Select a company.</div>
      ) : (
        <div style={{ display: "grid", gap: 14 }}>
          {FIELDS.map((f) => {
            const current = values[f.key];
            const defaultBody = data.defaults[f.key];
            const usingDefault = !(current || "").trim();
            return (
              <section key={f.key} style={card}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <h2 style={sectionHeader}>{f.label}</h2>
                    <p style={desc}>{f.description}</p>
                    <p style={{ ...desc, marginTop: 2 }}>
                      <strong>Placeholders:</strong> {f.placeholders}
                    </p>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    {!usingDefault && isAdmin && (
                      <button type="button" onClick={() => resetToDefault(f.key)} style={ghostButton}>
                        Reset to default
                      </button>
                    )}
                  </div>
                </div>
                <textarea
                  value={current}
                  onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                  disabled={!isAdmin}
                  placeholder={usingDefault ? "Using system default — leave blank to keep using it" : ""}
                  rows={8}
                  style={textarea}
                />
                <details style={{ marginTop: 6 }}>
                  <summary style={{ fontSize: 12, color: "#0176d3", cursor: "pointer" }}>
                    {usingDefault ? "View system default (currently in use)" : "View system default"}
                  </summary>
                  <pre style={defaultPre}>{defaultBody}</pre>
                </details>
              </section>
            );
          })}

          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button
              type="button"
              onClick={() => companyId && loadTemplates(companyId)}
              disabled={loading || saving}
              style={ghostButton}
            >
              Reload
            </button>
            <button
              type="button"
              onClick={save}
              disabled={!isAdmin || saving}
              style={primaryButton}
            >
              {saving ? "Saving…" : `Save${selectedCompanyName ? ` (${selectedCompanyName})` : ""}`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const card: React.CSSProperties = {
  border: "1px solid #dddbda",
  borderRadius: 4,
  background: "#fff",
  padding: 14,
  boxShadow: "0 1px 2px rgba(0,0,0,.06)",
};

const sectionHeader: React.CSSProperties = {
  margin: "0 0 4px",
  fontSize: 13,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "#3e3e3c",
};

const desc: React.CSSProperties = {
  margin: 0,
  fontSize: 12,
  color: "#706e6b",
};

const textarea: React.CSSProperties = {
  marginTop: 10,
  width: "100%",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  fontSize: 13,
  padding: 10,
  border: "1px solid #c9c7c5",
  borderRadius: 4,
  resize: "vertical",
  boxSizing: "border-box",
};

const defaultPre: React.CSSProperties = {
  marginTop: 6,
  background: "#f3f3f3",
  border: "1px solid #e5e5e5",
  borderRadius: 4,
  padding: 10,
  fontSize: 12,
  whiteSpace: "pre-wrap",
  color: "#3e3e3c",
};

const ghostButton: React.CSSProperties = {
  background: "#fff",
  color: "#0176d3",
  border: "1px solid #0176d3",
  borderRadius: 4,
  padding: "6px 12px",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};

const primaryButton: React.CSSProperties = {
  background: "#0176d3",
  color: "#fff",
  border: "none",
  borderRadius: 4,
  padding: "8px 14px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};

const errorBox: React.CSSProperties = {
  marginBottom: 12,
  padding: 10,
  background: "#fdecea",
  border: "1px solid #f5b7b1",
  borderRadius: 4,
  color: "#ba0517",
  fontSize: 13,
};

const infoBox: React.CSSProperties = {
  marginBottom: 12,
  padding: 10,
  background: "#e8f4fd",
  border: "1px solid #b6dffb",
  borderRadius: 4,
  color: "#0176d3",
  fontSize: 13,
};
