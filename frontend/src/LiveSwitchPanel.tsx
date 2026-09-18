import { useCallback, useEffect, useRef, useState } from "react";
import CustomerPageControls from "./CustomerPageControls";
import { createPortal } from "react-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import "./LiveSwitchPanel.css";

type Conversation = {
  id: string;
  hostJoinUrl: string;
  participantJoinUrl: string;
  conversationUrl: string;
  embeddedConversationUrl: string;
  last_spark_id?: string;
  last_spark_status?: string;
  last_spark_share_url?: string;
  spark_extracted_cuft?: number;
  spark_extracted_weight?: number;
};
type SparkInventoryRow = {
  id: string;
  name: string;
  cuft: number | null;
  amount: number | null;
  sort_order: number;
};
type Item = { id: string; file: File; name: string; type: string; preview?: string; crm: boolean; live: boolean; progress: number; status: string; error?: string };
const types: Record<string, string> = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", pdf: "application/pdf", mp4: "video/mp4", mov: "video/quicktime" };
function uploadErrorMessage(body: string, status: number, statusText: string): string {
  const httpError = `HTTP ${status}${statusText ? ` ${statusText}` : ""}`;
  try {
    const data = JSON.parse(body);
    const detail = data?.detail || data?.errorMessage || data?.message;
    if (typeof detail === "string" && detail.trim()) return `${detail} (${httpError})`;
    if (Array.isArray(detail)) {
      const messages = detail.map(row => row?.msg).filter(message => typeof message === "string");
      if (messages.length) return `${messages.join("; ")} (${httpError})`;
    }
  } catch { /* The upload service may return XML rather than JSON. */ }
  if (body.trim().startsWith("<")) {
    const xml = new DOMParser().parseFromString(body, "application/xml");
    const message = xml.querySelector("Error > Message")?.textContent;
    if (message) return `${message} (${httpError})`;
  } else if (body.trim() && !body.trim().startsWith("{")) {
    return `${body.trim()} (${httpError})`;
  }
  return httpError;
}
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
  const [panelWidth, setPanelWidth] = useState(() => Math.min(640, window.innerWidth));
  const [resizing, setResizing] = useState(false);
  const resizeStart = useRef<{ pointerId: number; x: number; width: number } | null>(null);
  const [notice, setNotice] = useState("");
  const [sparkRunning, setSparkRunning] = useState(false);
  const [sparkNotice, setSparkNotice] = useState("");
  const [sparkError, setSparkError] = useState("");
  const [sparkData, setSparkData] = useState<{ id: string; status: string; shareUrl?: string; cuft?: number; weight?: number } | null>(null);
  const [inventoryExpanded, setInventoryExpanded] = useState(false);
  const [inventoryLoading, setInventoryLoading] = useState(false);
  const [inventoryLoaded, setInventoryLoaded] = useState(false);
  const [inventoryError, setInventoryError] = useState("");
  const [inventoryRows, setInventoryRows] = useState<SparkInventoryRow[]>([]);
  const [smsSending, setSmsSending] = useState(false);
  const [smsNotice, setSmsNotice] = useState("");
  const [smsError, setSmsError] = useState("");
  const smsRunning = useRef(false);
  const previews = useRef<string[]>([]);
  const panel = useRef<HTMLDivElement>(null);
  const running = useRef(false);
  const base = `${API_BASE}/api/liveswitch/leads/${encodeURIComponent(leadId)}`;
  const request = useCallback(async (url: string, body?: unknown) => {
    const response = await fetch(url, { method: "POST", headers: { ...authHeaders(token), "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!response.ok) throw new Error(uploadErrorMessage(await response.text(), response.status, response.statusText));
    return response.json();
  }, [token]);

  const loadSparkInventory = useCallback(async (force = false) => {
    if (inventoryLoading) return;
    if (!force && inventoryLoaded) return;
    setInventoryLoading(true);
    setInventoryError("");
    try {
      const res = await fetch(`${base}/spark-inventory`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(uploadErrorMessage(await res.text(), res.status, res.statusText));
      const json = await res.json();
      const rows = Array.isArray(json?.rows) ? json.rows : [];
      setInventoryRows(rows.map((row: any, index: number) => ({
        id: String(row?.id || `${index}`),
        name: String(row?.name || ""),
        cuft: typeof row?.cuft === "number" ? row.cuft : null,
        amount: typeof row?.amount === "number" ? row.amount : null,
        sort_order: Number(row?.sort_order || 0),
      })));
      setInventoryLoaded(true);
    } catch (err) {
      setInventoryError(err instanceof Error ? err.message : "Could not load inventory.");
    } finally {
      setInventoryLoading(false);
    }
  }, [base, token, inventoryLoading, inventoryLoaded]);

  const loadSparkStatus = useCallback(async () => {
    try {
      const res = await fetch(`${base}/spark-status`, { headers: authHeaders(token) });
      if (!res.ok) return;
      const json = await res.json();
      if (json && json.spark) {
        const status = String(json.spark.status || "");
        const cuftVal = json.cuft || json.spark.cuft;
        const weightVal = json.weight || json.spark.weight;
        setSparkData({
          ...json.spark,
          cuft: cuftVal,
          weight: weightVal,
        });
        if ((inventoryExpanded || inventoryLoaded) && status === "completed") {
          void loadSparkInventory(true);
        }
        if (cuftVal) {
          onUploaded(); // Updates volume, weight, and pricing on lead details
        }
      }
    } catch { /* ignore */ }
  }, [base, token, onUploaded, inventoryExpanded, inventoryLoaded, loadSparkInventory]);

  useEffect(() => {
    // Do not call spark status on panel open.
    // Poll only while a known report is still pending.
    const isPending = sparkData && (sparkData.status === "queued" || sparkData.status === "running");
    if (!isPending) return;

    const interval = setInterval(() => {
      void loadSparkStatus();
    }, 60000);
    return () => clearInterval(interval);
  }, [loadSparkStatus, sparkData]);

  async function runSpark() {
    if (sparkRunning) return;
    setSparkRunning(true);
    setSparkNotice("");
    setSparkError("");
    try {
      const res = await request(`${base}/run-spark`);
      setSparkNotice("Inventory report initiated! LiveSwitch is processing the files.");
      if (res && res.id) {
        setSparkData({ id: res.id, status: res.status || "queued" });
      }
      setInventoryLoaded(false);
      setInventoryError("");
      setInventoryRows([]);
      setTimeout(() => void loadSparkStatus(), 3000);
    } catch (err) {
      setSparkError(err instanceof Error ? err.message : "Could not run inventory report.");
    } finally {
      setSparkRunning(false);
    }
  }
  async function sendParticipantSms() {
    if (smsRunning.current) return;
    smsRunning.current = true;
    setSmsSending(true); setSmsNotice(""); setSmsError("");
    try {
      await request(`${base}/participant-sms`);
      setSmsNotice("Participant link sent by SMS.");
    } catch (err) {
      setSmsError(err instanceof Error ? err.message : "Could not send SMS.");
    } finally {
      smsRunning.current = false;
      setSmsSending(false);
    }
  }
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const nextConversation = await request(`${base}/conversation`);
      await fetch(`${API_BASE}/api/leads/${encodeURIComponent(leadId)}/customer-page/generate`, {
        method: "POST",
        headers: authHeaders(token),
      }).then(async response => {
        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(result.detail || "Could not generate customer page");
        }
      });
      setConversation(nextConversation);
      setSparkData(current => {
        if (current) return current;
        const reportId = String(nextConversation?.last_spark_id || "").trim();
        if (!reportId) return null;
        return {
          id: reportId,
          status: String(nextConversation?.last_spark_status || "queued"),
          shareUrl: String(nextConversation?.last_spark_share_url || ""),
          cuft: Number(nextConversation?.spark_extracted_cuft || 0) || undefined,
          weight: Number(nextConversation?.spark_extracted_weight || 0) || undefined,
        };
      });
    }
    catch (err) { setError(err instanceof Error ? err.message : "Could not start LiveSwitch"); }
    finally { setLoading(false); }
  }, [base, leadId, request, token]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const clampWidth = () => setPanelWidth(width => Math.min(window.innerWidth, Math.max(360, width)));
    window.addEventListener("resize", clampWidth);
    return () => window.removeEventListener("resize", clampWidth);
  }, []);
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
      const type = types[ext] || file.type || "application/octet-stream";
      let name = file.name; let n = 1;
      while (names.has(name)) name = `${file.name.replace(/\.[^.]+$/, "")} (${n++}).${ext}`;
      names.add(name);
      const preview = type.startsWith("image/") ? URL.createObjectURL(file) : undefined;
      if (preview) previews.current.push(preview);
      const error = file.size === 0 ? "File is empty" : undefined;
      return { id: crypto.randomUUID(), file, name, type, preview, crm: false, live: false, progress: 0, status: error ? "Cannot upload" : "Ready", error };
    });
    setItems(current => [...current, ...added]);
  }
  function put(item: Item, url: string, fields?: Record<string, string>) {
    return new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest(); xhr.open(fields ? "POST" : "PUT", url); xhr.timeout = 0;
      if (!fields) xhr.setRequestHeader("Content-Type", item.type);
      xhr.upload.onprogress = event => { if (event.lengthComputable) update(item.id, { progress: Math.round(event.loaded / event.total * 90) }); };
      xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(uploadErrorMessage(xhr.responseText, xhr.status, xhr.statusText)));
      xhr.onerror = () => reject(new Error("Network error. The browser could not complete the upload or read the server response."));
      xhr.ontimeout = () => reject(new Error("Upload timed out after 5 minutes. Please retry."));
      if (fields) { const form = new FormData(); Object.entries(fields).forEach(([key, value]) => form.append(key, value)); form.append("file", item.file); xhr.send(form); } else xhr.send(item.file);
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
          let preparationError = "";
          if (needUrls.length) {
            try {
              const data = await request(`${base}/upload-urls/${kind}`, needUrls.map(item => ({ fileName: item.name, contentType: item.type })));
              results = data.results || [];
            } catch (err) {
              preparationError = err instanceof Error ? err.message : "Could not prepare upload";
            }
          }
          for (const item of batch) {
            update(item.id, { status: "Uploading", error: undefined });
            let live = item.live; let crm = item.crm;
            try {
              if (!crm) {
                const metadata = { request_id: item.id, name: item.name, size: item.file.size, content_type: item.type };
                const prepared = await request(`${base}/prepare-upload`, metadata);
                if (!prepared.completed) {
                  await put(item, prepared.upload.url, prepared.upload.fields);
                  await request(`${base}/finish-upload`, metadata);
                }
                crm = true; update(item.id, { crm });
              }
              if (!live) {
                if (preparationError) throw new Error(preparationError);
                const result = results.find(result => result.fileName === item.name);
                if (!result?.presignedUrl || result.errorMessage) throw new Error(result?.errorMessage || "LiveSwitch did not return an upload URL for this file.");
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
    <div className="ls-panel" style={{ width: `min(${panelWidth}px, 100vw)`, position: "relative", userSelect: resizing ? "none" : undefined }} role="dialog" aria-modal="true" aria-labelledby="ls-title" tabIndex={-1} ref={panel} onClick={e => e.stopPropagation()} onKeyDown={e => {
      if (e.key === "Escape" && !busy) onClose();
      if (e.key === "Tab") {
        const nodes = panel.current?.querySelectorAll<HTMLElement>('[role="separator"], button:not(:disabled), a[href], input:not(:disabled), summary, iframe');
        if (!nodes?.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }}>
      <div role="separator" aria-label="Resize LiveSwitch panel" aria-orientation="vertical" aria-valuenow={Math.round(panelWidth)} aria-valuetext={`${Math.round(panelWidth)} pixels wide`} tabIndex={0}
        title="Drag left to widen or right to narrow"
        style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 24, zIndex: 2, cursor: "col-resize", touchAction: "none", display: "flex", alignItems: "center", justifyContent: "flex-start" }}
        onPointerDown={e => {
          if (e.button !== 0 || !e.isPrimary) return;
          e.preventDefault();
          e.currentTarget.focus();
          e.currentTarget.setPointerCapture(e.pointerId);
          resizeStart.current = { pointerId: e.pointerId, x: e.clientX, width: panel.current?.getBoundingClientRect().width || panelWidth };
          setResizing(true);
        }}
        onPointerMove={e => {
          const start = resizeStart.current;
          if (!start || start.pointerId !== e.pointerId) return;
          setPanelWidth(Math.min(window.innerWidth, Math.max(360, start.width + start.x - e.clientX)));
        }}
        onPointerUp={e => {
          if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
          resizeStart.current = null;
          setResizing(false);
        }}
        onPointerCancel={() => { resizeStart.current = null; setResizing(false); }}
        onLostPointerCapture={() => { resizeStart.current = null; setResizing(false); }}
        onKeyDown={e => {
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
          e.preventDefault();
          setPanelWidth(width => Math.min(window.innerWidth, Math.max(360, width + (e.key === "ArrowLeft" ? 32 : -32))));
        }}
      ><span aria-hidden="true" style={{ width: 4, height: 48, marginLeft: 2, borderRadius: 4, background: resizing ? "#0176d3" : "#8fb4d8" }}/></div>
      <header><span className="ls-logo"><Icon kind="video"/></span><div><h2 id="ls-title">LiveSwitch</h2><p>Connect and share files with your customer</p></div><button className="slds-button" aria-label="Close LiveSwitch" disabled={busy} onClick={onClose}>&times;</button></header>
      <main>{loading ? <p role="status">Preparing your conversation </p> : error ? <div role="alert" className="ls-error">{error}<button className="slds-button" onClick={() => void load()}>Try again</button></div> : conversation ? <>
        <section className="ls-card"><h3>Conversation links</h3><p>Copy a link or open it in a new tab.</p>{([['Host', conversation.hostJoinUrl], ['Participant', conversation.participantJoinUrl]] as const).map(([label, url]) => <div className="ls-link" key={label}><div><strong>{label} link</strong><span title={url}>{url || "Link unavailable"}</span></div><button className="slds-button" disabled={!url} aria-label={`Copy ${label.toLowerCase()} link`} title="Copy link" onClick={() => void navigator.clipboard.writeText(url).then(() => setNotice(`${label} link copied`)).catch(() => setNotice("Could not copy. Select and copy the link manually."))}><Icon kind="copy"/></button>{url && <a href={url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${label.toLowerCase()} link in a new tab`} title="Open in new tab"><Icon kind="open"/></a>}{label === "Participant" && <button className="slds-button" type="button" disabled={!url || smsSending} style={{ flexShrink: 0 }} title={smsSending ? "Sending SMS" : "Send SMS"} aria-label={smsSending ? "Sending participant link by SMS" : "Send participant link by SMS"} aria-busy={smsSending} onClick={() => void sendParticipantSms()}><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M4 3h16v13H9l-5 5V3Z M8 7h8M8 11h6"/></svg></button>}</div>)}<CustomerPageControls leadId={leadId} section="links"/>{smsNotice && <p role="status">{smsNotice}</p>}{smsError && <div className="ls-error" role="alert">{smsError}</div>}</section>
        <section className="ls-card"><h3>Add Photos, Documents, or Videos</h3><p>Add files right from your device.</p><label className="ls-picker">+ Choose files<input type="file" multiple disabled={busy} onChange={e => { choose(e.target.files); e.target.value = ""; }}/></label><small>All file types</small>
        {items.length > 0 && <p role="status">{completed} of {items.length} files uploaded{completed > 0 ? ". LiveSwitch may take a moment to process them." : ""}</p>}
        <CustomerPageControls leadId={leadId} section="files"/><div className="ls-files">{items.map(item => <article key={item.id}>{item.preview ? <img src={item.preview} alt=""/> : <span className="ls-file-icon">{item.type.startsWith("video/") ? "Video" : "File"}</span>}<div className="ls-file-content"><strong title={item.name}>{item.name}</strong><small>{(item.file.size / 1024 / 1024).toFixed(1)} MB   {item.status}</small><progress value={item.progress} max={100} aria-label={`${item.name} upload progress`}/>{item.error && <details className="ls-error" style={{ overflowWrap: "anywhere" }}><summary style={{ cursor: "pointer" }}>{item.status === "Cannot upload" ? "Cannot upload" : item.crm ? "LiveSwitch upload failed" : "CRM save failed"} — View error</summary><div style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{item.error}</div></details>}</div>{!busy && !item.crm && !item.live && <button className="slds-button" aria-label={`Remove ${item.name}`} onClick={() => setItems(current => current.filter(row => row.id !== item.id))}>&times;</button>}{item.crm && item.live && <span className="ls-success" aria-label="Uploaded">&#10003;</span>}</article>)}</div>
        <div className="ls-actions">
          <button className="slds-button ls-primary" disabled={busy || !items.some(item => !(item.crm && item.live) && item.status !== "Cannot upload")} onClick={() => void upload()}>{busy ? "Uploading " : items.some(item => item.status === "Retry") ? "Upload / Retry failed" : "Upload files"}</button>
          <button className="slds-button" disabled={busy || !items.length} onClick={() => setItems(current => current.filter(item => item.crm || item.live))}>Clear selection</button>
          <button
            type="button"
            className="slds-button ls-primary"
            style={{ marginLeft: "auto", background: "#084e8a" }}
            disabled={busy || sparkRunning}
            onClick={() => void runSpark()}
          >
            {sparkRunning ? "Running Report..." : "Generate Inventory Report"}
          </button>
        </div>
        {sparkNotice && <p role="status" style={{ color: "#2e844a", fontSize: 13, marginTop: 8 }}>{sparkNotice}</p>}
        {sparkError && <div className="ls-error" role="alert" style={{ marginTop: 8 }}>{sparkError}</div>}
        {sparkData && (
          <div style={{ marginTop: 12, padding: 10, background: "#f1f5f9", borderRadius: 6, fontSize: 13, color: "#0f172a" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <span>
                Inventory AI Report: <strong>{sparkData.status === "completed" ? "✓ Completed" : sparkData.status === "running" ? "Analyzing..." : "Queued"}</strong>
                {sparkData.cuft ? ` · ${sparkData.cuft} cu ft` : ""}
              </span>
              {sparkData.shareUrl && (
                <a
                  href={sparkData.shareUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "#0176d3", fontWeight: 700, textDecoration: "underline" }}
                >
                  View Report ↗
                </a>
              )}
            </div>
            <div style={{ marginTop: 10 }}>
              <button
                type="button"
                className="slds-button"
                onClick={() => {
                  setInventoryExpanded(current => {
                    const next = !current;
                    if (next && !inventoryLoaded) {
                      void loadSparkInventory();
                    }
                    return next;
                  });
                }}
              >
                {inventoryExpanded ? "Hide inventory" : "Show inventory"}
              </button>
            </div>
            {inventoryExpanded && (
              <div style={{ marginTop: 10 }}>
                {inventoryLoading && <p role="status" style={{ margin: 0 }}>Loading inventory...</p>}
                {!inventoryLoading && inventoryError && <div className="ls-error" role="alert" style={{ marginTop: 0 }}>{inventoryError}</div>}
                {!inventoryLoading && !inventoryError && inventoryRows.length === 0 && <p style={{ margin: 0 }}>No inventory saved for this job yet.</p>}
                {!inventoryLoading && !inventoryError && inventoryRows.length > 0 && (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 4 }}>
                      <thead>
                        <tr>
                          <th style={{ textAlign: "left", borderBottom: "1px solid #cbd5e1", padding: "6px 4px" }}>Name</th>
                          <th style={{ textAlign: "right", borderBottom: "1px solid #cbd5e1", padding: "6px 4px" }}>CuFt</th>
                          <th style={{ textAlign: "right", borderBottom: "1px solid #cbd5e1", padding: "6px 4px" }}>Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inventoryRows.map(row => (
                          <tr key={row.id}>
                            <td style={{ borderBottom: "1px solid #e2e8f0", padding: "6px 4px" }}>{row.name || "-"}</td>
                            <td style={{ textAlign: "right", borderBottom: "1px solid #e2e8f0", padding: "6px 4px" }}>{row.cuft ?? 0}</td>
                            <td style={{ textAlign: "right", borderBottom: "1px solid #e2e8f0", padding: "6px 4px" }}>{row.amount ?? 0}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        </section>
        <CustomerPageControls leadId={leadId}/><section className="ls-card"><button className="slds-button ls-expand" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "\u25be" : "\u25b8"} Conversation viewer</button>{expanded ? <>{conversation.conversationUrl ? <a href={conversation.conversationUrl} target="_blank" rel="noopener noreferrer">Open conversation in a new tab</a> : null}{conversation.embeddedConversationUrl ? <iframe title="LiveSwitch conversation" src={conversation.embeddedConversationUrl} style={{ pointerEvents: resizing ? "none" : undefined }} allow="camera; microphone; fullscreen; display-capture"/> : !conversation.conversationUrl ? <p>Conversation viewer unavailable.</p> : null}</> : null}</section>
      </> : null}<p className="ls-notice" role="status">{notice}</p></main>
    </div>
  </div>, document.body);
}
