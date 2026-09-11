import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import "./LiveSwitchPanel.css";

type Conversation = { id: string; hostJoinUrl: string; participantJoinUrl: string; conversationUrl: string; embeddedConversationUrl: string };
type Item = { id: string; file: File; name: string; type: string; preview?: string; crm: boolean; live: boolean; progress: number; status: string; error?: string };
const types: Record<string, string> = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", pdf: "application/pdf", mp4: "video/mp4", mov: "video/quicktime" };
function Icon({ kind }: { kind: "copy" | "open" | "video" }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">{kind === "copy" ? <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/></> : kind === "open" ? <><path d="M14 3h7v7M21 3L10 14M10 5H4v15h15v-6"/></> : <><rect x="3" y="6" width="12" height="12" rx="2"/><path d="m15 10 6-4v12l-6-4"/></>}</svg>;
}
export default function LiveSwitchPanel({ leadId, onClose, onUploaded }: { leadId: string; onClose: () => void; onUploaded: () => void }) {
  const { token } = useAuth();
  const [conversation, setConversation] = useState<Conversation>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [notice, setNotice] = useState("");
  const previews = useRef<string[]>([]);
  const panel = useRef<HTMLDivElement>(null);
  const running = useRef(false);
  const base = `${API_BASE}/api/liveswitch/leads/${encodeURIComponent(leadId)}`;
  const request = useCallback(async (url: string, body?: unknown) => {
    const response = await fetch(url, { method: "POST", headers: { ...authHeaders(token), "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed. Please try again.");
    return data;
  }, [token]);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setConversation(await request(`${base}/conversation`)); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not start LiveSwitch"); }
    finally { setLoading(false); }
  }, [base, request]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const urls = previews.current;
    return () => { urls.forEach(URL.revokeObjectURL); previous?.focus(); };
  }, []);
  function update(id: string, changes: Partial<Item>) { setItems(current => current.map(item => item.id === id ? { ...item, ...changes } : item)); }
  function choose(files: FileList | null) {
    if (!files) return;
    const names = new Set(items.map(item => item.name));
    const added: Item[] = Array.from(files).map(file => {
      const ext = file.name.split(".").pop()?.toLowerCase() || "";
      const type = types[ext] || "";
      let name = file.name; let n = 1;
      while (names.has(name)) name = `${file.name.replace(/\.[^.]+$/, "")} (${n++}).${ext}`;
      names.add(name);
      const preview = type.startsWith("image/") ? URL.createObjectURL(file) : undefined;
      if (preview) previews.current.push(preview);
      const error = !type ? "Unsupported file type" : file.size === 0 ? "File is empty" : file.size > 15 * 1024 * 1024 ? "File exceeds 15 MB" : undefined;
      return { id: crypto.randomUUID(), file, name, type, preview, crm: false, live: false, progress: 0, status: error ? "Cannot upload" : "Ready", error };
    });
    setItems(current => [...current, ...added]);
  }
  function put(item: Item, url: string) {
    return new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest(); xhr.open("PUT", url); xhr.timeout = 300000;
      xhr.setRequestHeader("Content-Type", item.type);
      xhr.upload.onprogress = event => { if (event.lengthComputable) update(item.id, { progress: Math.round(event.loaded / event.total * 90) }); };
      xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error("Upload failed. Please retry."));
      xhr.onerror = xhr.ontimeout = () => reject(new Error("Upload interrupted. Please retry."));
      xhr.send(item.file);
    });
  }
  async function upload() {
    if (running.current) return;
    running.current = true; setBusy(true); setNotice("");
    const pending = items.filter(item => !(item.crm && item.live) && item.status !== "Cannot upload");
    try {
      for (const kind of ["images", "videos", "documents"]) {
        const group = pending.filter(item => (item.type.startsWith("image/") ? "images" : item.type.startsWith("video/") ? "videos" : "documents") === kind);
        for (let offset = 0; offset < group.length; offset += 20) {
          const batch = group.slice(offset, offset + 20);
          const needUrls = batch.filter(item => !item.live);
          let results: Array<{ fileName: string; presignedUrl?: string; errorMessage?: string }> = [];
          if (needUrls.length) {
            try {
              const data = await request(`${base}/upload-urls/${kind}`, needUrls.map(item => ({ fileName: item.name, contentType: item.type })));
              results = data.results || [];
            } catch (err) {
              needUrls.forEach(item => update(item.id, { status: "Retry", error: err instanceof Error ? err.message : "Could not prepare upload" }));
            }
          }
          for (const item of batch) {
            update(item.id, { status: "Uploading", error: undefined });
            let live = item.live; let crm = item.crm;
            try {
              if (!crm) {
                const body = new FormData(); body.append("file", item.file, item.name);
                const response = await fetch(`${API_BASE}/api/leads/${encodeURIComponent(leadId)}/attachments`, { method: "POST", headers: authHeaders(token), body });
                if (!response.ok) throw new Error("Could not save file. Please retry.");
                crm = true; update(item.id, { crm });
              }
              if (!live) {
                const result = results.find(result => result.fileName === item.name);
                if (!result?.presignedUrl || result.errorMessage) throw new Error(result?.errorMessage || "Could not finish upload. Please retry.");
                await put(item, result.presignedUrl); live = true;
              }
              update(item.id, { live, crm, progress: 100, status: "Uploaded", error: undefined });
            } catch (err) { update(item.id, { live, crm, status: "Retry", error: err instanceof Error ? err.message : "Upload failed" }); }
          }
        }
      }
    } finally { running.current = false; setBusy(false); onUploaded(); }
  }
  const completed = items.filter(item => item.crm && item.live).length;
  return createPortal(<div className="ls-backdrop" onClick={() => { if (!busy) onClose(); }}>
    <div className="ls-panel" role="dialog" aria-modal="true" aria-labelledby="ls-title" tabIndex={-1} ref={panel} onClick={e => e.stopPropagation()} onKeyDown={e => {
      if (e.key === "Escape" && !busy) onClose();
      if (e.key === "Tab") {
        const nodes = panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), iframe');
        if (!nodes?.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }}>
      <header><span className="ls-logo"><Icon kind="video"/></span><div><h2 id="ls-title">LiveSwitch</h2><p>Connect and share files with your customer</p></div><button aria-label="Close LiveSwitch" disabled={busy} onClick={onClose}>&times;</button></header>
      <main>{loading ? <p role="status">Preparing your conversation </p> : error ? <div role="alert" className="ls-error">{error}<button onClick={() => void load()}>Try again</button></div> : conversation ? <>
        <section className="ls-card"><h3>Conversation links</h3><p>Copy a link or open it in a new tab.</p>{([['Host', conversation.hostJoinUrl], ['Participant', conversation.participantJoinUrl]] as const).map(([label, url]) => <div className="ls-link" key={label}><div><strong>{label} link</strong><span title={url}>{url || "Link unavailable"}</span></div><button disabled={!url} aria-label={`Copy ${label.toLowerCase()} link`} title="Copy link" onClick={() => void navigator.clipboard.writeText(url).then(() => setNotice(`${label} link copied`)).catch(() => setNotice("Could not copy. Select and copy the link manually."))}><Icon kind="copy"/></button>{url && <a href={url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${label.toLowerCase()} link in a new tab`} title="Open in new tab"><Icon kind="open"/></a>}</div>)}</section>
        <section className="ls-card"><h3>Add Photos, Documents, or Videos</h3><p>Add files right from your device.</p><label className="ls-picker">+ Choose files<input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.pdf,.mp4,.mov" disabled={busy} onChange={e => { choose(e.target.files); e.target.value = ""; }}/></label><small>JPEG, PNG, WebP, PDF, MP4 or MOV   Up to 15 MB per file</small>
        {items.length > 0 && <p role="status">{completed} of {items.length} files uploaded{completed > 0 ? ". LiveSwitch may take a moment to process them." : ""}</p>}
        <div className="ls-files">{items.map(item => <article key={item.id}>{item.preview ? <img src={item.preview} alt=""/> : <span className="ls-file-icon">{item.type.startsWith("video/") ? "Video" : "PDF"}</span>}<div className="ls-file-content"><strong title={item.name}>{item.name}</strong><small>{(item.file.size / 1024 / 1024).toFixed(1)} MB   {item.status}</small><progress value={item.progress} max={100} aria-label={`${item.name} upload progress`}/>{item.error && <span className="ls-error" role="status">{item.error}</span>}</div>{!busy && !item.crm && !item.live && <button aria-label={`Remove ${item.name}`} onClick={() => setItems(current => current.filter(row => row.id !== item.id))}>&times;</button>}{item.crm && item.live && <span className="ls-success" aria-label="Uploaded">&#10003;</span>}</article>)}</div>
        <div className="ls-actions"><button className="ls-primary" disabled={busy || !items.some(item => !(item.crm && item.live) && item.status !== "Cannot upload")} onClick={() => void upload()}>{busy ? "Uploading " : items.some(item => item.status === "Retry") ? "Upload / Retry failed" : "Upload files"}</button><button disabled={busy || !items.length} onClick={() => setItems(current => current.filter(item => item.crm || item.live))}>Clear selection</button></div></section>
        <section className="ls-card"><button className="ls-expand" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "\u25be" : "\u25b8"} Conversation viewer</button>{expanded && (conversation.embeddedConversationUrl ? <><a href={conversation.conversationUrl} target="_blank" rel="noopener noreferrer">Open conversation in a new tab</a><iframe title="LiveSwitch conversation" src={conversation.embeddedConversationUrl} allow="camera; microphone; fullscreen; display-capture"/></> : <p>Conversation viewer unavailable.</p>)}</section>
      </> : null}<p className="ls-notice" role="status">{notice}</p></main>
    </div>
  </div>, document.body);
}
