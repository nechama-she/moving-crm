// Right-hand column of the lead page in the new look: stage, quick actions, smart summary and
// the lead's chat, tasks and log in tabs (the classic look shows these in a floating drawer).
import { useEffect, useState, type ReactNode } from "react";
import type { LeadSideAction } from "../LeadSidePanel";
import Icon, { type IconName } from "./Icon";
import { SmartSummary, StageStepper } from "./LeadBits";

type Tab = "chat" | "tasks" | "log";
const TABS: { id: Tab; label: string; icon: IconName }[] = [
  { id: "chat", label: "Chat", icon: "message" },
  { id: "tasks", label: "Tasks", icon: "queue" },
  { id: "log", label: "Log", icon: "history" },
];

export default function AuroraLeadRail({ leadId, status, phone, email, tasksRequested, chat, tasks, log, actions = [] }: {
  leadId: string; status: string; phone: string; email: string; tasksRequested: boolean;
  chat: ReactNode; tasks: ReactNode; log: ReactNode; actions?: LeadSideAction[];
}) {
  const [tab, setTab] = useState<Tab>(tasksRequested ? "tasks" : "chat");
  useEffect(() => { if (tasksRequested) setTab("tasks"); }, [tasksRequested]);
  const content = { chat, tasks, log }[tab];

  return (
    <aside className="aur-lead-rail" aria-label="Lead tools">
      <section className="aur-card aur-rail-card">
        <StageStepper status={status} />
        <div className="aur-quick">
          {phone ? <a className="aur-quick-btn" href={`tel:${phone}`}><Icon name="phone" size={16} />Call</a> : <span className="aur-quick-btn is-disabled"><Icon name="phone" size={16} />Call</span>}
          <button type="button" className="aur-quick-btn" onClick={() => setTab("chat")}><Icon name="message" size={16} />Text</button>
          {email ? <a className="aur-quick-btn" href={`mailto:${email}`}><Icon name="mail" size={16} />Email</a> : <span className="aur-quick-btn is-disabled"><Icon name="mail" size={16} />Email</span>}
        </div>
        {actions.length > 0 && <div className="aur-quick aur-quick-tools">
          {actions.map(action => <button key={action.key} type="button" className="aur-quick-btn" title={action.title} onClick={action.open}>{action.icon}{action.label}</button>)}
        </div>}
        <SmartSummary leadId={leadId} />
      </section>

      <section className="aur-card aur-rail-tools">
        <div className="aur-tabs" role="tablist" aria-label="Lead tools">
          {TABS.map(t => (
            <button key={t.id} type="button" role="tab" id={`aur-rail-tab-${t.id}`} aria-selected={tab === t.id} aria-controls="aur-rail-panel"
              className={`aur-tab${tab === t.id ? " is-active" : ""}`} onClick={() => setTab(t.id)}>
              <Icon name={t.icon} size={15} />{t.label}
            </button>
          ))}
        </div>
        <div className="aur-rail-panel" id="aur-rail-panel" role="tabpanel" aria-labelledby={`aur-rail-tab-${tab}`}>{content}</div>
      </section>
    </aside>
  );
}
