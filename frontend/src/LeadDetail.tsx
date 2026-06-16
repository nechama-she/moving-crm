import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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

type LeadAttachment = {
  id: string;
  file_name: string;
  content_type: string;
  file_size: number;
  created_at: string;
  uploaded_by_name?: string;
};

type LeadJobItem = {
  id: string;
  lead_id: string;
  company_id: string;
  company_name: string;
  job_order: number;
  pickup_zip: string;
  delivery_zip: string;
  move_date: string;
  booked_move_date: string;
  price: number | null;
};

type LeadJobDraft = {
  company_id: string;
  pickup_zip: string;
  delivery_zip: string;
  move_date: string;
  booked_move_date: string;
  price: string;
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
const LEAD_STATUS_OPTIONS = [
  "new",
  "contacted",
  "quoted",
  "booked",
  "scheduled",
  "completed",
  "lost",
  "cancelled",
];

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
  const [companyMenuOpen, setCompanyMenuOpen] = useState(false);
  const companyMenuRef = useRef<HTMLDivElement | null>(null);
  const statusMenuRef = useRef<HTMLDivElement | null>(null);
  const statusButtonRef = useRef<HTMLButtonElement | null>(null);
  const [attachments, setAttachments] = useState<LeadAttachment[]>([]);
  const [attachmentsLoading, setAttachmentsLoading] = useState(true);
  const [attachmentsError, setAttachmentsError] = useState("");
  const [uploadingCount, setUploadingCount] = useState(0);
  const [attachmentsQuery, setAttachmentsQuery] = useState("");
  const [attachmentsSort, setAttachmentsSort] = useState<"newest" | "name" | "size">("newest");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [filesModalOpen, setFilesModalOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewType, setPreviewType] = useState<"image" | "pdf" | "text" | "none">("none");
  const [previewText, setPreviewText] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [renamingId, setRenamingId] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [savingStatus, setSavingStatus] = useState(false);
  const [statusMenuOpen, setStatusMenuOpen] = useState(false);
  const [statusMenuRect, setStatusMenuRect] = useState<{ top: number; left: number; width: number; height: number } | null>(null);
  const [leadJobs, setLeadJobs] = useState<LeadJobItem[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState("");
  const [jobDrafts, setJobDrafts] = useState<Record<string, LeadJobDraft>>({});
  const [newJobDraft, setNewJobDraft] = useState<LeadJobDraft>({
    company_id: "",
    pickup_zip: "",
    delivery_zip: "",
    move_date: "",
    booked_move_date: "",
    price: "",
  });
  const [addingJob, setAddingJob] = useState(false);
  const [savingJobId, setSavingJobId] = useState("");
  const [deletingJobId, setDeletingJobId] = useState("");
  const [activeJobTabId, setActiveJobTabId] = useState("");

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

  async function loadAttachments() {
    setAttachmentsLoading(true);
    setAttachmentsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/attachments`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { items?: Array<Record<string, unknown>> };
      const rows = Array.isArray(data.items) ? data.items : [];
      setAttachments(rows.map((row) => ({
        id: String(row.id || ""),
        file_name: String(row.file_name || ""),
        content_type: String(row.content_type || "application/octet-stream"),
        file_size: Number(row.file_size || 0),
        created_at: String(row.created_at || ""),
        uploaded_by_name: String(row.uploaded_by_name || ""),
      })));
    } catch (err: unknown) {
      setAttachmentsError(err instanceof Error ? err.message : "Failed to load attachments");
      setAttachments([]);
    } finally {
      setAttachmentsLoading(false);
    }
  }

  function draftFromJob(item: LeadJobItem): LeadJobDraft {
    return {
      company_id: item.company_id || "",
      pickup_zip: item.pickup_zip || "",
      delivery_zip: item.delivery_zip || "",
      move_date: item.move_date || "",
      booked_move_date: item.booked_move_date || "",
      price: item.price == null ? "" : String(item.price),
    };
  }

  async function loadLeadJobs() {
    setJobsLoading(true);
    setJobsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { items?: Array<Record<string, unknown>> };
      const rows = Array.isArray(data.items) ? data.items : [];
      const parsed: LeadJobItem[] = rows.map((item) => ({
        id: String(item.id || ""),
        lead_id: String(item.lead_id || ""),
        company_id: String(item.company_id || ""),
        company_name: String(item.company_name || ""),
        job_order: Number(item.job_order || 0),
        pickup_zip: String(item.pickup_zip || ""),
        delivery_zip: String(item.delivery_zip || ""),
        move_date: String(item.move_date || ""),
        booked_move_date: String(item.booked_move_date || ""),
        price: item.price == null ? null : Number(item.price),
      }));
      setLeadJobs(parsed);
      setJobDrafts(Object.fromEntries(parsed.map((item) => [item.id, draftFromJob(item)])));
      setNewJobDraft((prev) => ({ ...prev, company_id: prev.company_id || String(lead?.company_id || "") }));
    } catch (err: unknown) {
      setJobsError(err instanceof Error ? err.message : "Failed to load jobs");
      setLeadJobs([]);
      setJobDrafts({});
    } finally {
      setJobsLoading(false);
    }
  }

  useEffect(() => {
    void loadAttachments();
  }, [leadId, token]);

  useEffect(() => {
    void loadLeadJobs();
  }, [leadId, token]);

  useEffect(() => {
    setNewJobDraft((prev) => ({ ...prev, company_id: prev.company_id || String(lead?.company_id || "") }));
  }, [lead?.company_id]);

  useEffect(() => {
    if (leadJobs.length === 0) {
      setActiveJobTabId("");
      return;
    }
    if (activeJobTabId === "__new__") return;
    if (!activeJobTabId || !leadJobs.some((job) => job.id === activeJobTabId)) {
      setActiveJobTabId(leadJobs[0].id);
    }
  }, [leadJobs, activeJobTabId]);

  async function saveJob(jobId: string) {
    const draft = jobDrafts[jobId];
    if (!draft) return;
    setSavingJobId(jobId);
    setJobsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs/${jobId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          company_id: draft.company_id,
          pickup_zip: draft.pickup_zip,
          delivery_zip: draft.delivery_zip,
          move_date: draft.move_date,
          booked_move_date: draft.booked_move_date,
          price: draft.price.trim() === "" ? null : Number(draft.price),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await loadLeadJobs();
    } catch (err: unknown) {
      setJobsError(err instanceof Error ? err.message : "Failed to save job");
    } finally {
      setSavingJobId("");
    }
  }

  async function addJob() {
    setAddingJob(true);
    setJobsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          company_id: newJobDraft.company_id || String(lead?.company_id || ""),
          pickup_zip: newJobDraft.pickup_zip,
          delivery_zip: newJobDraft.delivery_zip,
          move_date: newJobDraft.move_date,
          booked_move_date: newJobDraft.booked_move_date,
          price: newJobDraft.price.trim() === "" ? null : Number(newJobDraft.price),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setNewJobDraft({
        company_id: String(lead?.company_id || ""),
        pickup_zip: "",
        delivery_zip: "",
        move_date: "",
        booked_move_date: "",
        price: "",
      });
      await loadLeadJobs();
    } catch (err: unknown) {
      setJobsError(err instanceof Error ? err.message : "Failed to add job");
    } finally {
      setAddingJob(false);
    }
  }

  async function deleteJob(jobId: string) {
    setDeletingJobId(jobId);
    setJobsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs/${jobId}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await loadLeadJobs();
    } catch (err: unknown) {
      setJobsError(err instanceof Error ? err.message : "Failed to delete job");
    } finally {
      setDeletingJobId("");
    }
  }

  async function uploadAttachments(files: File[]) {
    if (files.length === 0) return;
    setUploadingCount(files.length);
    setAttachmentsError("");
    try {
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(`${API_BASE}/api/leads/${leadId}/attachments`, {
          method: "POST",
          headers: authHeaders(token),
          body: form,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
          throw new Error(String((err as { detail?: unknown }).detail || `HTTP ${res.status}`));
        }
        setUploadingCount((v) => Math.max(0, v - 1));
      }
      await loadAttachments();
    } catch (err: unknown) {
      setAttachmentsError(err instanceof Error ? err.message : "Failed to upload attachment");
    } finally {
      setUploadingCount(0);
    }
  }

  async function downloadAttachment(attachmentId: string, fileName: string) {
    setAttachmentsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/attachments/${attachmentId}/download`, {
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = fileName || "attachment";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (err: unknown) {
      setAttachmentsError(err instanceof Error ? err.message : "Failed to download attachment");
    }
  }

  async function deleteAttachment(attachmentId: string) {
    setAttachmentsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/attachments/${attachmentId}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await loadAttachments();
    } catch (err: unknown) {
      setAttachmentsError(err instanceof Error ? err.message : "Failed to delete attachment");
    }
  }

  async function renameAttachment(attachmentId: string, fileName: string) {
    const nextName = fileName.trim();
    if (!nextName) return;
    setAttachmentsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/attachments/${attachmentId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ file_name: nextName }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await loadAttachments();
      setRenamingId("");
      setRenameValue("");
    } catch (err: unknown) {
      setAttachmentsError(err instanceof Error ? err.message : "Failed to rename attachment");
    }
  }

  async function openPreview(attachmentId: string, fileName: string, contentType: string) {
    setAttachmentsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/attachments/${attachmentId}/download`, {
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);

      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(objectUrl);
      setPreviewTitle(fileName || "Preview");

      const lowerName = (fileName || "").toLowerCase();
      const type = (contentType || blob.type || "").toLowerCase();
      const isImage = type.startsWith("image/") || /\.(png|jpg|jpeg|gif|webp|bmp|svg)$/.test(lowerName);
      const isPdf = type.includes("pdf") || lowerName.endsWith(".pdf");
      const isText = type.startsWith("text/") || /\.(txt|md|csv|json|log|xml)$/.test(lowerName);

      if (isImage) {
        setPreviewType("image");
        setPreviewText("");
      } else if (isPdf) {
        setPreviewType("pdf");
        setPreviewText("");
      } else if (isText) {
        setPreviewType("text");
        setPreviewText(await blob.text());
      } else {
        setPreviewType("none");
        setPreviewText("Preview not available for this file type.");
      }
      setPreviewOpen(true);
    } catch (err: unknown) {
      setAttachmentsError(err instanceof Error ? err.message : "Failed to preview attachment");
    }
  }

  function closePreview() {
    setPreviewOpen(false);
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl("");
    }
    setPreviewType("none");
    setPreviewText("");
    setPreviewTitle("");
  }

  function fileIcon(name: string) {
    const lower = name.toLowerCase();
    if (/(\.png|\.jpg|\.jpeg|\.gif|\.webp|\.bmp|\.svg)$/.test(lower)) return "IMG";
    if (lower.endsWith(".pdf")) return "PDF";
    if (/(\.doc|\.docx)$/.test(lower)) return "DOC";
    if (/(\.xls|\.xlsx|\.csv)$/.test(lower)) return "XLS";
    if (/(\.zip|\.rar|\.7z)$/.test(lower)) return "ZIP";
    return "FILE";
  }

  const filteredAttachments = useMemo(() => {
    const q = attachmentsQuery.trim().toLowerCase();
    let rows = attachments.filter((a) => {
      if (!q) return true;
      return a.file_name.toLowerCase().includes(q) || (a.uploaded_by_name || "").toLowerCase().includes(q);
    });
    rows = [...rows];
    if (attachmentsSort === "name") rows.sort((a, b) => a.file_name.localeCompare(b.file_name));
    if (attachmentsSort === "size") rows.sort((a, b) => (b.file_size || 0) - (a.file_size || 0));
    if (attachmentsSort === "newest") rows.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    return rows;
  }, [attachments, attachmentsQuery, attachmentsSort]);

  const quickAttachments = useMemo(() => {
    return [...attachments]
      .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
      .slice(0, 4);
  }, [attachments]);

  useEffect(() => {
    function onDocMouseDown(event: MouseEvent) {
      const target = event.target as Node;
      if (companyMenuRef.current && !companyMenuRef.current.contains(target)) {
        setCompanyMenuOpen(false);
      }
      if (statusMenuRef.current && !statusMenuRef.current.contains(target)) {
        setStatusMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  useEffect(() => {
    if (!statusMenuOpen) return;

    function updateStatusMenuRect() {
      const node = statusButtonRef.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      setStatusMenuRect({ top: rect.bottom + 8, left: rect.left, width: rect.width, height: rect.height });
    }

    updateStatusMenuRect();
    window.addEventListener("resize", updateStatusMenuRect);
    window.addEventListener("scroll", updateStatusMenuRect, true);
    return () => {
      window.removeEventListener("resize", updateStatusMenuRect);
      window.removeEventListener("scroll", updateStatusMenuRect, true);
    };
  }, [statusMenuOpen]);

  if (loading) return <p style={{ padding: 24 }}>Loading…</p>;
  if (error)
    return <p style={{ padding: 24, color: "#ba0517" }}>Error: {error}</p>;
  if (!lead) return <p style={{ padding: 24 }}>Lead not found.</p>;
  const canEditCompany = user?.role === "admin";
  const isDispatchUser = user?.role === "dispatch";

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
    <div style={{ width: "100%", height: "calc(100vh - 52px)", overflowY: "auto", overflowX: "hidden", boxSizing: "border-box", padding: "24px clamp(16px, 3vw, 28px) 40px", background: "#f6f8fb" }}>
      <div style={{ width: "100%", maxWidth: 1120, margin: "0 auto" }}>
      <button
        onClick={() => navigate(user?.role === "dispatch" ? "/dispatch" : "/")}
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
        {user?.role === "dispatch" ? "← Back to Dispatch" : "← Back to Leads"}
      </button>

      {previewOpen ? (
        <div
          role="presentation"
          onClick={closePreview}
          style={{ position: "fixed", inset: 0, background: "rgba(15, 23, 42, 0.55)", zIndex: 95, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
        >
          <div
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
            style={{ width: "min(900px, 100%)", maxHeight: "90vh", overflow: "auto", background: "#fff", borderRadius: 8, border: "1px solid #cbd5e1" }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid #e2e8f0" }}>
              <strong style={{ fontSize: 13, color: "#0f172a" }}>{previewTitle}</strong>
              <button type="button" onClick={closePreview} style={{ border: "1px solid #cbd5e1", background: "#fff", color: "#334155", borderRadius: 4, padding: "4px 8px", fontSize: 12 }}>Close</button>
            </div>
            <div style={{ padding: 12 }}>
              {previewType === "image" ? <img src={previewUrl} alt={previewTitle} style={{ maxWidth: "100%", height: "auto", borderRadius: 6 }} /> : null}
              {previewType === "pdf" ? <iframe src={previewUrl} title={previewTitle} style={{ width: "100%", height: 650, border: "none" }} /> : null}
              {previewType === "text" ? <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 12, color: "#334155", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 6, padding: 10 }}>{previewText}</pre> : null}
              {previewType === "none" ? <p style={{ margin: 0, fontSize: 12, color: "#64748b" }}>{previewText}</p> : null}
            </div>
          </div>
        </div>
      ) : null}

      {filesModalOpen ? (
        <div
          role="presentation"
          onClick={() => setFilesModalOpen(false)}
          style={{ position: "fixed", inset: 0, zIndex: 85 }}
        >
          <div
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
            style={{
              position: "fixed",
              top: 0,
              right: 0,
              bottom: 0,
              width: "min(480px, 100vw)",
              background: "#fff",
              borderLeft: "1px solid #cbd5e1",
              boxShadow: "-8px 0 32px rgba(15,23,42,.14)",
              display: "flex",
              flexDirection: "column",
              zIndex: 86,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 14px", borderBottom: "1px solid #e2e8f0", flexShrink: 0 }}>
              <strong style={{ fontSize: 13, color: "#0f172a" }}>All Files</strong>
              <button type="button" onClick={() => setFilesModalOpen(false)} style={{ border: "1px solid #cbd5e1", background: "#fff", color: "#334155", borderRadius: 4, padding: "4px 8px", fontSize: 12 }}>Close</button>
            </div>
            <div style={{ padding: 12, overflowY: "auto", flex: 1 }}>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) auto", gap: 8, marginBottom: 12 }}>
                <input
                  value={attachmentsQuery}
                  onChange={(e) => setAttachmentsQuery(e.target.value)}
                  placeholder="Search files..."
                  style={{ border: "1px solid #d8dde6", borderRadius: 6, padding: "8px 10px", width: "100%", minWidth: 0, fontSize: 12, boxSizing: "border-box" }}
                />
                <select
                  value={attachmentsSort}
                  onChange={(e) => setAttachmentsSort(e.target.value as "newest" | "name" | "size")}
                  style={{ border: "1px solid #d8dde6", borderRadius: 6, padding: "8px 10px", fontSize: 12, background: "#fff", minWidth: 110 }}
                >
                  <option value="newest">Newest</option>
                  <option value="name">Name</option>
                  <option value="size">Size</option>
                </select>
              </div>

              {attachmentsLoading ? <p style={{ margin: 0, fontSize: 12, color: "#706e6b" }}>Loading files...</p> : null}
              {!attachmentsLoading && filteredAttachments.length === 0 ? <p style={{ margin: 0, fontSize: 12, color: "#706e6b" }}>No files found.</p> : null}
              {!attachmentsLoading && filteredAttachments.length > 0 ? (
                <div style={{ display: "grid", gap: 8 }}>
                  {filteredAttachments.map((attachment) => (
                    <div key={attachment.id} style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, border: "1px solid #e5e7eb", borderRadius: 8, padding: "10px 12px", background: "#fff", flexWrap: "wrap" }}>
                      <div style={{ minWidth: 0, display: "flex", alignItems: "flex-start", gap: 10, flex: "1 1 320px" }}>
                        <div style={{ minWidth: 42, height: 28, borderRadius: 6, background: "#eef2ff", color: "#1e3a8a", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 700, flexShrink: 0 }}>
                          {fileIcon(attachment.file_name)}
                        </div>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          {renamingId === attachment.id ? (
                            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                              <input
                                value={renameValue}
                                onChange={(e) => setRenameValue(e.target.value)}
                                style={{ border: "1px solid #cbd5e1", borderRadius: 6, padding: "6px 8px", fontSize: 12, width: "min(100%, 280px)", minWidth: 0 }}
                              />
                              <button type="button" onClick={() => void renameAttachment(attachment.id, renameValue)} style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "3px 8px", fontSize: 11 }}>Save</button>
                              <button type="button" onClick={() => { setRenamingId(""); setRenameValue(""); }} style={{ border: "1px solid #dddbda", background: "#fff", color: "#475569", borderRadius: 4, padding: "3px 8px", fontSize: 11 }}>Cancel</button>
                            </div>
                          ) : (
                            <div style={{ fontSize: 13, fontWeight: 600, color: "#0f172a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{attachment.file_name}</div>
                          )}
                          <div style={{ fontSize: 11, color: "#64748b" }}>
                            {Math.max(1, Math.round((attachment.file_size || 0) / 1024))} KB
                            {attachment.created_at ? ` • ${new Date(attachment.created_at).toLocaleString()}` : ""}
                            {attachment.uploaded_by_name ? ` • ${attachment.uploaded_by_name}` : ""}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, flexWrap: "wrap", justifyContent: "flex-end", marginLeft: "auto" }}>
                        <button
                          type="button"
                          onClick={() => void openPreview(attachment.id, attachment.file_name, attachment.content_type)}
                          style={{ border: "1px solid #cbd5e1", background: "#fff", color: "#334155", borderRadius: 4, padding: "4px 8px", fontSize: 12 }}
                        >
                          Preview
                        </button>
                        <button
                          type="button"
                          onClick={() => void downloadAttachment(attachment.id, attachment.file_name)}
                          style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "4px 8px", fontSize: 12, fontWeight: 600 }}
                        >
                          Download
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setRenamingId(attachment.id);
                            setRenameValue(attachment.file_name);
                          }}
                          style={{ border: "1px solid #dddbda", background: "#fff", color: "#334155", borderRadius: 4, padding: "4px 8px", fontSize: 12 }}
                        >
                          Rename
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            if (window.confirm("Delete this file?")) {
                              void deleteAttachment(attachment.id);
                            }
                          }}
                          style={{ border: "1px solid #dddbda", background: "#fff", color: "#ba0517", borderRadius: 4, padding: "4px 8px", fontSize: 12 }}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {!isDispatchUser ? (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 20 }}>
          <div style={{ width: "100%", maxWidth: 360 }}>
            <FollowupPanel leadId={leadId!} />
          </div>
        </div>
      ) : null}

      {/* Client highlights card */}
      {(() => {
        const name = String(lead.full_name || "").trim();
        const phone = String(lead.phone_number || "").trim();
        const email = String(lead.email || "").trim();
        const statusValue = String(lead.status || "new").trim().toLowerCase();
        const statusLabel = statusValue
          ? statusValue.charAt(0).toUpperCase() + statusValue.slice(1)
          : "New";
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

        async function saveCompany(nextCompanyId: string) {
          if (!nextCompanyId) return;
          if (nextCompanyId === String(lead?.company_id || "")) {
            setCompanyMenuOpen(false);
            return;
          }
          setSavingCompany(true);
          try {
            const res = await fetch(`${API_BASE}/api/leads/${leadId}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json", ...authHeaders(token) },
              body: JSON.stringify({
                company_id: nextCompanyId,
              }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const updated = await res.json();
            setLead(updated);
            setEditCompanyId(String(updated.company_id || ""));
            setCompanyMenuOpen(false);
          } catch (e) {
            alert(`Failed to save company: ${e instanceof Error ? e.message : "error"}`);
          } finally {
            setSavingCompany(false);
          }
        }

        async function saveStatus(nextStatus: string) {
          if (!LEAD_STATUS_OPTIONS.includes(nextStatus)) return;
          if (nextStatus === statusValue) return;
          setSavingStatus(true);
          try {
            const res = await fetch(`${API_BASE}/api/leads/${leadId}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json", ...authHeaders(token) },
              body: JSON.stringify({ status: nextStatus }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const updated = await res.json();
            setLead(updated);
            setStatusMenuOpen(false);
          } catch (e) {
            alert(`Failed to save status: ${e instanceof Error ? e.message : "error"}`);
          } finally {
            setSavingStatus(false);
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
        const statusStyles: Record<string, React.CSSProperties> = {
          new: { background: "#eef2ff", color: "#3730a3", border: "1px solid #c7d2fe" },
          contacted: { background: "#fff7ed", color: "#c2410c", border: "1px solid #fed7aa" },
          quoted: { background: "#f5f3ff", color: "#7c3aed", border: "1px solid #ddd6fe" },
          booked: { background: "#ecfeff", color: "#0e7490", border: "1px solid #a5f3fc" },
          scheduled: { background: "#eff6ff", color: "#2563eb", border: "1px solid #bfdbfe" },
          completed: { background: "#ecfdf5", color: "#047857", border: "1px solid #a7f3d0" },
          lost: { background: "#fef2f2", color: "#b91c1c", border: "1px solid #fecaca" },
          cancelled: { background: "#f8fafc", color: "#475569", border: "1px solid #cbd5e1" },
        };
        const statusStyle = statusStyles[statusValue] || { background: "#f1f5f9", color: "#334155", border: "1px solid #cbd5e1" };
        const selectedCompanyName = companies.find((c) => c.id === editCompanyId)?.name || String(lead.company_name || "-");

        return (
          <div style={{ ...sectionStyle, padding: 18, overflow: "visible", position: "relative" }}>
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
                  <div style={{ display: "grid", gap: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <div style={{ fontSize: 18, fontWeight: 700, color: "#032d60" }}>
                        {name || "—"}
                      </div>
                      <div ref={statusMenuRef} style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
                        <button
                          ref={statusButtonRef}
                          type="button"
                          aria-haspopup="menu"
                          aria-expanded={statusMenuOpen}
                          onClick={() => setStatusMenuOpen((v) => !v)}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            padding: "4px 11px",
                            borderRadius: 999,
                            border: "none",
                            fontSize: 11,
                            fontWeight: 700,
                            letterSpacing: "0.04em",
                            textTransform: "uppercase",
                            whiteSpace: "nowrap",
                            cursor: "pointer",
                            boxShadow: "0 1px 2px rgba(15,23,42,.08)",
                            ...statusStyle,
                          }}
                        >
                          {statusLabel}
                          <span style={{ fontSize: 9, lineHeight: 1, opacity: 0.9 }}>▾</span>
                        </button>
                      </div>
                      {statusMenuOpen && statusMenuRect ? createPortal(
                        <div
                          role="menu"
                          style={{
                            position: "fixed",
                            top: statusMenuRect.top,
                            left: statusMenuRect.left,
                            minWidth: Math.max(statusMenuRect.width, 220),
                            background: "#fff",
                            border: "1px solid #d8dde6",
                            borderRadius: 12,
                            boxShadow: "0 20px 50px rgba(15,23,42,.22)",
                            overflow: "hidden",
                            zIndex: 99999,
                          }}
                        >
                          <div style={{ padding: "8px 10px", fontSize: 11, fontWeight: 700, color: "#64748b", borderBottom: "1px solid #eef2f7", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                            Change status
                          </div>
                          {LEAD_STATUS_OPTIONS.map((option) => {
                            const optionLabel = option.charAt(0).toUpperCase() + option.slice(1);
                            const active = option === statusValue;
                            const optionColor = String((statusStyles[option] || {}).color || "#64748b");
                            return (
                              <button
                                key={option}
                                type="button"
                                role="menuitemradio"
                                aria-checked={active}
                                disabled={savingStatus}
                                onClick={() => {
                                  void saveStatus(option);
                                }}
                                style={{
                                  width: "100%",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "space-between",
                                  gap: 10,
                                  border: "none",
                                  background: active ? "#f8fafc" : "#fff",
                                  padding: "10px 12px",
                                  textAlign: "left",
                                  cursor: savingStatus ? "default" : "pointer",
                                  color: "#0f172a",
                                }}
                              >
                                <span style={{ display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                                  <span style={{ width: 8, height: 8, borderRadius: 999, flexShrink: 0, background: optionColor }} />
                                  <span style={{ fontSize: 13, fontWeight: 600 }}>{optionLabel}</span>
                                </span>
                                {active ? <span style={{ fontSize: 12, color: "#0176d3", fontWeight: 700 }}>Current</span> : null}
                              </button>
                            );
                          })}
                          {savingStatus ? <div style={{ padding: "8px 12px", fontSize: 12, color: "#64748b", borderTop: "1px solid #eef2f7" }}>Saving...</div> : null}
                        </div>,
                        document.body
                      ) : null}
                      <div ref={companyMenuRef} style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
                      <button
                        type="button"
                        onClick={() => canEditCompany && setCompanyMenuOpen((v) => !v)}
                        disabled={!canEditCompany || savingCompany}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                          maxWidth: 240,
                          padding: "4px 11px",
                          borderRadius: 999,
                          border: "1px solid #cbd5e1",
                          background: "#f8fafc",
                          color: "#334155",
                          fontSize: 11,
                          fontWeight: 700,
                          letterSpacing: "0.04em",
                          textTransform: "uppercase",
                          whiteSpace: "nowrap",
                          cursor: canEditCompany ? "pointer" : "default",
                          boxShadow: "0 1px 2px rgba(15,23,42,.08)",
                        }}
                        title={savingCompany ? "Updating company" : selectedCompanyName}
                      >
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {savingCompany ? "Updating..." : selectedCompanyName}
                        </span>
                        <span style={{ fontSize: 9, lineHeight: 1, opacity: 0.9 }}>▾</span>
                      </button>

                      {canEditCompany && companyMenuOpen ? (
                        <div
                          style={{
                            position: "absolute",
                            top: "calc(100% + 4px)",
                            left: 0,
                            right: 0,
                            minWidth: 260,
                            maxHeight: 220,
                            overflowY: "auto",
                            background: "#fff",
                            border: "1px solid #cbd5e1",
                            borderRadius: 12,
                            boxShadow: "0 20px 50px rgba(15,23,42,.22)",
                            zIndex: 20,
                          }}
                        >
                          <div style={{ padding: "8px 10px", fontSize: 11, fontWeight: 700, color: "#64748b", borderBottom: "1px solid #eef2f7", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                            Change company
                          </div>
                          {companies.map((company) => {
                            const isCurrent = company.id === String(lead.company_id || "");
                            return (
                              <button
                                key={company.id}
                                type="button"
                                onClick={() => {
                                  setEditCompanyId(company.id);
                                  void saveCompany(company.id);
                                }}
                                disabled={savingCompany}
                                style={{
                                  width: "100%",
                                  textAlign: "left",
                                  border: "none",
                                  background: isCurrent ? "#f8fafc" : "#fff",
                                  color: isCurrent ? "#0f172a" : "#1e293b",
                                  padding: "10px 12px",
                                  fontSize: 13,
                                  cursor: "pointer",
                                }}
                              >
                                {company.name}{isCurrent ? " (current)" : ""}
                              </button>
                            );
                          })}
                        </div>
                      ) : null}
                      </div>
                    </div>
                    {companiesError ? <div style={{ color: "#ba0517", fontSize: 12 }}>{companiesError}</div> : null}
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
                <span style={{ fontSize: 18 }}>📎</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={tileLabel}>Files</div>
                  <div style={{ display: "grid", gap: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <label style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8, border: "1px solid #d8dde6", borderRadius: 6, padding: "6px 10px", fontSize: 12, fontWeight: 600, cursor: uploadingCount > 0 ? "default" : "pointer", opacity: uploadingCount > 0 ? 0.7 : 1, background: "#fff", whiteSpace: "nowrap", width: "fit-content" }}>
                        <input
                          type="file"
                          multiple
                          disabled={uploadingCount > 0}
                          style={{ display: "none" }}
                          onChange={(e) => {
                            const files = Array.from(e.target.files || []);
                            void uploadAttachments(files);
                            e.currentTarget.value = "";
                          }}
                        />
                        {uploadingCount > 0 ? `Uploading ${uploadingCount}...` : "Upload"}
                      </label>
                      <button
                        type="button"
                        onClick={() => setFilesModalOpen(true)}
                        style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "5px 10px", fontSize: 12, fontWeight: 600, width: "fit-content" }}
                      >
                        More
                      </button>
                    </div>
                    {attachmentsError ? <div style={{ color: "#ba0517", fontSize: 12 }}>{attachmentsError}</div> : null}
                    {!attachmentsLoading && quickAttachments.length === 0 ? <div style={{ color: "#706e6b", fontSize: 12 }}>No files yet.</div> : null}
                    {!attachmentsLoading && quickAttachments.length > 0 ? (
                      <div style={{ display: "grid", gap: 4 }}>
                        {quickAttachments.slice(0, 2).map((attachment) => (
                          <button
                            key={attachment.id}
                            type="button"
                            onClick={() => void openPreview(attachment.id, attachment.file_name, attachment.content_type)}
                            style={{ border: "1px solid #e2e8f0", background: "#fff", borderRadius: 6, padding: "4px 6px", fontSize: 11, color: "#334155", textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", cursor: "pointer" }}
                          >
                            {attachment.file_name}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      <div style={sectionStyle}>
        <div style={sectionHeader}>Jobs</div>
        <div style={{ padding: 12, display: "grid", gap: 12 }}>
          {jobsError ? <p style={{ margin: 0, color: "#ba0517", fontSize: 12 }}>{jobsError}</p> : null}
          {jobsLoading ? <p style={{ margin: 0, color: "#64748b", fontSize: 12 }}>Loading jobs...</p> : null}

          {!jobsLoading ? (
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 2 }}>
                {leadJobs.map((job) => {
                  const active = activeJobTabId === job.id;
                  return (
                    <button
                      key={job.id}
                      type="button"
                      onClick={() => setActiveJobTabId(job.id)}
                      style={{
                        border: active ? "1px solid #0176d3" : "1px solid #cbd5e1",
                        borderBottom: active ? "2px solid #0176d3" : "1px solid #cbd5e1",
                        background: active ? "#eaf5fe" : "#fff",
                        color: active ? "#014486" : "#334155",
                        borderRadius: 4,
                        padding: "5px 10px",
                        fontSize: 12,
                        fontWeight: 700,
                        cursor: "pointer",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {`Job ${job.job_order}`}
                    </button>
                  );
                })}
                <button
                  type="button"
                  onClick={() => setActiveJobTabId("__new__")}
                  style={{
                    border: activeJobTabId === "__new__" ? "1px solid #0176d3" : "1px solid #cbd5e1",
                    borderBottom: activeJobTabId === "__new__" ? "2px solid #0176d3" : "1px solid #cbd5e1",
                    background: activeJobTabId === "__new__" ? "#eaf5fe" : "#fff",
                    color: activeJobTabId === "__new__" ? "#014486" : "#334155",
                    borderRadius: 4,
                    width: 34,
                    fontSize: 16,
                    fontWeight: 700,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}
                  aria-label="Add job"
                  title="Add job"
                >
                  +
                </button>
              </div>

              {activeJobTabId !== "__new__" && leadJobs.some((j) => j.id === activeJobTabId) ? (() => {
                const job = leadJobs.find((j) => j.id === activeJobTabId)!;
                const draft = jobDrafts[job.id] || draftFromJob(job);
                const primary = job.job_order === 1;
                const busy = savingJobId === job.id || deletingJobId === job.id;
                return (
                  <div style={{ border: "1px solid #e2e8f0", borderRadius: 8, padding: 10, background: primary ? "#f8fbff" : "#fff" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
                      <strong style={{ fontSize: 13, color: "#0f172a" }}>Job {job.job_order}</strong>
                      {primary ? <span style={{ fontSize: 11, color: "#1d4ed8", fontWeight: 700 }}>Primary</span> : null}
                    </div>

                    <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
                      <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                        Company
                        <select
                          value={draft.company_id}
                          onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, company_id: e.target.value } }))}
                          style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12, background: "#fff" }}
                        >
                          {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
                        </select>
                      </label>
                      <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                        Pickup Zip
                        <input value={draft.pickup_zip} onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, pickup_zip: e.target.value } }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
                      </label>
                      <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                        Delivery Zip
                        <input value={draft.delivery_zip} onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, delivery_zip: e.target.value } }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
                      </label>
                      <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                        Move Date
                        <input type="date" value={draft.move_date} onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, move_date: e.target.value } }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
                      </label>
                      <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                        Booked Date
                        <input type="date" value={draft.booked_move_date} onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, booked_move_date: e.target.value } }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
                      </label>
                    </div>

                    <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                      <button type="button" onClick={() => void saveJob(job.id)} disabled={busy} style={{ border: "1px solid #0176d3", background: "#0176d3", color: "#fff", borderRadius: 4, padding: "5px 10px", fontSize: 12, fontWeight: 600 }}>
                        {savingJobId === job.id ? "Saving..." : "Save Job"}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (!primary && window.confirm("Delete this job?")) void deleteJob(job.id);
                        }}
                        disabled={busy || primary}
                        style={{ border: "1px solid #dddbda", background: "#fff", color: primary ? "#94a3b8" : "#ba0517", borderRadius: 4, padding: "5px 10px", fontSize: 12 }}
                      >
                        {deletingJobId === job.id ? "Deleting..." : "Delete"}
                      </button>
                    </div>
                  </div>
                );
              })() : null}
            </div>
          ) : null}

          {activeJobTabId === "__new__" ? (
          <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: 10, display: "grid", gap: 8 }}>
            <strong style={{ fontSize: 12, color: "#334155" }}>Add Job</strong>
            <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
              <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                Company
                <select value={newJobDraft.company_id} onChange={(e) => setNewJobDraft((prev) => ({ ...prev, company_id: e.target.value }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12, background: "#fff" }}>
                  {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
                </select>
              </label>
              <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                Pickup Zip
                <input value={newJobDraft.pickup_zip} onChange={(e) => setNewJobDraft((prev) => ({ ...prev, pickup_zip: e.target.value }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
              </label>
              <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                Delivery Zip
                <input value={newJobDraft.delivery_zip} onChange={(e) => setNewJobDraft((prev) => ({ ...prev, delivery_zip: e.target.value }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
              </label>
              <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                Move Date
                <input type="date" value={newJobDraft.move_date} onChange={(e) => setNewJobDraft((prev) => ({ ...prev, move_date: e.target.value }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
              </label>
              <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                Booked Date
                <input type="date" value={newJobDraft.booked_move_date} onChange={(e) => setNewJobDraft((prev) => ({ ...prev, booked_move_date: e.target.value }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
              </label>
            </div>
            <div>
              <button type="button" onClick={() => void addJob()} disabled={addingJob} style={{ border: "1px solid #0176d3", background: "#0176d3", color: "#fff", borderRadius: 4, padding: "6px 12px", fontSize: 12, fontWeight: 600 }}>
                {addingJob ? "Adding..." : "Add Job"}
              </button>
            </div>
          </div>
          ) : null}
        </div>
      </div>

      {(user?.role === "admin" || user?.role === "rep") &&
        (otherFields.length > 0 || META_FIELDS.some((k) => allKeys.includes(k))) &&
        renderSection("Other Info", [...META_FIELDS, ...otherFields])}

      {!isDispatchUser ? (
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
            ) : activeTab === "activity" ? (
              <TasksPanel leadId={leadId!} token={token} />
            ) : null}
          </div>
        </div>
      ) : null}
      </div>
    </div>
  );
}
