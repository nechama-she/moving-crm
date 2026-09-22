import "./ConnectChatModal.css";
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders } from "./AuthContext";
import MessageAttachments, { type MessageAttachment } from "./MessageAttachments";

type Chat = { client_identifier: string; company_identifier: string; name: string; timestamp: number; preview: string };
type Message = { message_id?: string; timestamp: number; text?: string; role?: string; attachments?: MessageAttachment[] };
export default function ConnectChatModal({ leadId, channel, token, onClose, onConnected }: {
  leadId: string; channel: "messenger" | "instagram"; token: string | null;
  onClose: () => void; onConnected: (client: string, messages: Message[], company: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [search, setSearch] = useState("");
  const [chats, setChats] = useState<Chat[]>([]);
  const [selected, setSelected] = useState<Chat | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const label = channel === "messenger" ? "Messenger" : "Instagram";
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    const controller = new AbortController();
    setChats([]); setSelected(null); setMessages([]); setError(""); setLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        let cursor = "";
        do {
          const params = new URLSearchParams({ lead_id: leadId, channel, search, cursor });
          const response = await fetch(`${API_BASE}/api/communication-associations/unconnected-meta?${params}`, { headers: authHeaders(token), signal: controller.signal });
          const body = await response.json();
          if (!response.ok) throw new Error(body.detail || "Could not search chats");
          if (controller.signal.aborted) return;
          setChats(previous => {
            const map = new Map(previous.map(chat => [chat.client_identifier, chat]));
            for (const chat of body.items as Chat[]) if (!map.has(chat.client_identifier) || map.get(chat.client_identifier)!.timestamp < chat.timestamp) map.set(chat.client_identifier, chat);
            return [...map.values()].sort((a, b) => b.timestamp - a.timestamp);
          });
          cursor = body.next_cursor || "";
        } while (cursor && !controller.signal.aborted);
      } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Search failed"); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [leadId, channel, token, search]);
  useEffect(() => {
    const controller = new AbortController();
    setMessages([]);
    if (!selected) { setPreviewLoading(false); return; }
    setPreviewLoading(true);
    void (async () => {
      try {
        let cursor = "";
        do {
          const params = new URLSearchParams({ lead_id: leadId, channel, client_identifier: selected.client_identifier, cursor });
          const response = await fetch(`${API_BASE}/api/communication-associations/meta-preview?${params}`, { headers: authHeaders(token), signal: controller.signal });
          const body = await response.json();
          if (!response.ok) throw new Error(body.detail || "Could not load chat");
          if (controller.signal.aborted) return;
          setMessages(previous => [...previous, ...(body.messages || [])].sort((a, b) => Number(a.timestamp) - Number(b.timestamp)));
          cursor = body.next_cursor || "";
        } while (cursor && !controller.signal.aborted);
      } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Preview failed"); }
      finally { if (!controller.signal.aborted) setPreviewLoading(false); }
    })();
    return () => controller.abort();
  }, [selected, leadId, channel, token]);
  async function connect() {
    if (!selected || saving) return;
    setSaving(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/communication-associations`, {
        method: "PUT", headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({ channel, lead_id: leadId, client_identifier: selected.client_identifier, company_identifier: selected.company_identifier, only_if_unconnected: true }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Could not connect chat");
      onConnected(selected.client_identifier, messages, selected.company_identifier);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Connection failed"); }
    finally { setSaving(false); }
  }
  return <dialog ref={dialog} className="crm-chat-picker" aria-labelledby="chat-picker-title" onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <div className="crm-chat-picker-shell">
      <header className="crm-chat-picker-header">
        <div><h2 id="chat-picker-title">Connect {label}</h2><p>Choose an unconnected chat for this company.</p></div>
        <button type="button" className="slds-button slds-button_neutral" aria-label="Close chat picker" disabled={saving} onClick={onClose}>Close</button>
      </header>
      {error && <p role="alert" className="crm-chat-picker-error">{error}</p>}
      <div className={`crm-chat-picker-body${selected ? " has-selection" : ""}`}>
        <aside className="crm-chat-picker-sidebar">
          <div className="crm-chat-picker-search"><label htmlFor="chat-picker-search">Search messages, names, or IDs</label><input id="chat-picker-search" className="slds-input" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search this platform" /><small>Newest first</small></div>
          <div className="crm-chat-picker-results">
            {chats.map(chat => <button type="button" className={`crm-chat-picker-result${selected?.client_identifier === chat.client_identifier ? " is-selected" : ""}`} aria-pressed={selected?.client_identifier === chat.client_identifier} key={chat.client_identifier} disabled={saving} onClick={() => setSelected(chat)}><strong>{chat.name}</strong><time>{new Date(chat.timestamp * 1000).toLocaleString()}</time><span>{chat.preview || "Attachment or empty message"}</span></button>)}
            <p role="status" className="crm-chat-picker-status">{loading ? "Searching messages..." : chats.length ? `${chats.length} chats` : "No unconnected chats found."}</p>
          </div>
        </aside>
        <section className="crm-chat-picker-preview" aria-label="Conversation preview">
          {!selected ? <div className="crm-chat-picker-empty"><strong>Preview a conversation</strong><p>Select a chat to review its messages before connecting.</p></div> : <>
            <header className="crm-chat-picker-conversation-header"><button type="button" className="slds-button slds-button_neutral crm-chat-picker-back" disabled={saving} onClick={() => setSelected(null)}>Back to chats</button><strong>{selected.name}</strong><small>{label}</small></header>
            <div className="crm-chat-picker-messages">{messages.map((message, index) => <div key={message.message_id || index} className={`crm-chat-picker-message${message.role === "user" ? "" : " is-outbound"}`}><div>{message.text}</div><MessageAttachments attachments={message.attachments} /><time>{new Date(Number(message.timestamp) * (Number(message.timestamp) < 1e12 ? 1000 : 1)).toLocaleString()}</time></div>)}{previewLoading && <p role="status">Loading conversation...</p>}</div>
          </>}
        </section>
      </div>
      <footer className="crm-chat-picker-footer"><span>{selected ? "Connect this conversation to the current lead." : "Select a conversation to continue."}</span><button type="button" className="slds-button slds-button_brand" disabled={!selected || saving || previewLoading} onClick={() => void connect()}>{saving ? "Connecting..." : `Connect ${label}`}</button></footer>
    </div>
  </dialog>;
}
