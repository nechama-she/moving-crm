// Pieces shared by the Leads side panel and the lead page: stage stepper and smart summary.
import { useEffect, useState } from "react";
import { API_BASE } from "../apiConfig";
import { authHeaders, useAuth } from "../AuthContext";
import Icon from "./Icon";

const STAGES = ["new", "contacted", "quoted", "booked"];

export function StageStepper({ status }: { status: string }) {
  const stage = (status || "new").toLowerCase();
  const stageIndex = STAGES.indexOf(["scheduled", "completed"].includes(stage) ? "booked" : stage);
  if (stageIndex < 0) return <span className={`aur-stage stage-${stage}`}>{stage}</span>;
  return (
    <ol className="aur-stepper" aria-label="Stage">
      {STAGES.map((s, i) => <li key={s} className={i <= stageIndex ? (i === stageIndex ? "is-current" : "is-done") : undefined}><span />{s}</li>)}
    </ol>
  );
}

export function SmartSummary({ leadId }: { leadId: string }) {
  const { token } = useAuth();
  const [summary, setSummary] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setSummary("");
    fetch(`${API_BASE}/api/leads/${encodeURIComponent(leadId)}/ai-summary`, { headers: authHeaders(token), signal: controller.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => setSummary(d?.summary ? String(d.summary) : ""))
      .catch(() => {});
    return () => controller.abort();
  }, [leadId, token]);

  // Shown only once the server returns a summary, so nothing appears while the assistant is not connected.
  if (!summary) return null;
  return (
    <div className="aur-ai-card" aria-live="polite">
      <span className="aur-ai-label"><Icon name="spark" size={14} />Smart summary</span>
      <p>{summary}</p>
    </div>
  );
}
