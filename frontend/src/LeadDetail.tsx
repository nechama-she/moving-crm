import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Lead, formatLabel, formatValue } from "./leadUtils";
import ChatMessages from "./ChatMessages";
import TasksPanel from "./TasksPanel";
import { API_BASE } from "./apiConfig";
import { useAuth, authHeaders } from "./AuthContext";

const HIDDEN_FIELDS = new Set(["entry_id", "inbox_url", "estimatedTotal", "estimated_total", "payments"]);

type CompanyOption = {
  id: string;
  name: string;
};

type UserOption = {
  id: string;
  name: string;
};

type CommissionSettingsResponse = {
  default_percent?: number;
  items?: Array<{
    user_id: string;
    percent?: number | null;
    effective_percent?: number;
  }>;
};

type LeadAttachment = {
  id: string;
  file_name: string;
  content_type: string;
  file_size: number;
  created_at: string;
  external_url?: string;
  is_external_link?: boolean;
  external_source?: string;
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
  stops: string[];
  move_date: string;
  booked_move_date: string;
  price: number | null;
  charges: LeadJobChargeItem[];
};

type LeadJobChargeItem = {
  id: string;
  job_id: string;
  name: string;
  description: string;
  sort_order: number;
  subtotal: number;
  discount_amount: number;
  total_cost: number;
};

type LeadJobDraft = {
  company_id: string;
  pickup_zip: string;
  delivery_zip: string;
  stops: string[];
  move_date: string;
  booked_move_date: string;
  price: string;
};

type LeadDetailNavigationState = {
  backTo?: string;
  backLabel?: string;
  backOrigin?: string;
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
  const location = useLocation();
  const { token, user } = useAuth();
  const [lead, setLead] = useState<Lead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"conversations" | "activity">("conversations");
  const [editingUser, setEditingUser] = useState(false);
  const [editName, setEditName] = useState("");
  const [editPhone, setEditPhone] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editMoveSize, setEditMoveSize] = useState("");
  const [savingUser, setSavingUser] = useState(false);
  const [refreshingSmartmoving, setRefreshingSmartmoving] = useState(false);
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [companiesError, setCompaniesError] = useState("");
  const [editCompanyId, setEditCompanyId] = useState("");
  const [savingCompany, setSavingCompany] = useState(false);
  const [savingAssignedTo, setSavingAssignedTo] = useState(false);
  const [companyMenuOpen, setCompanyMenuOpen] = useState(false);
  const companyMenuRef = useRef<HTMLDivElement | null>(null);
  const [assignMenuOpen, setAssignMenuOpen] = useState(false);
  const assignMenuRef = useRef<HTMLDivElement | null>(null);
  const statusMenuRef = useRef<HTMLDivElement | null>(null);
  const statusMenuPopoverRef = useRef<HTMLDivElement | null>(null);
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
  const [savingRepPaymentIndex, setSavingRepPaymentIndex] = useState<number | null>(null);
  const [statusMenuOpen, setStatusMenuOpen] = useState(false);
  const [statusMenuRect, setStatusMenuRect] = useState<{ top: number; left: number; width: number; height: number } | null>(null);
  const [deletingLead, setDeletingLead] = useState(false);
  const [defaultCommissionPercent, setDefaultCommissionPercent] = useState<number>(((1 - 0.035) / 3) * 100);
  const [commissionPercentByUserId, setCommissionPercentByUserId] = useState<Map<string, number>>(new Map());
  const [leadJobs, setLeadJobs] = useState<LeadJobItem[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState("");
  const [jobDrafts, setJobDrafts] = useState<Record<string, LeadJobDraft>>({});
  const [newJobDraft, setNewJobDraft] = useState<LeadJobDraft>({
    company_id: "",
    pickup_zip: "",
    delivery_zip: "",
    stops: [],
    move_date: "",
    booked_move_date: "",
    price: "",
  });
  const [addingJob, setAddingJob] = useState(false);
  const [savingJobId, setSavingJobId] = useState("");
  const [deletingJobId, setDeletingJobId] = useState("");
  const [activeJobTabId, setActiveJobTabId] = useState("");
  const consumedRouteJobRef = useRef("");
  const routeJobId = useMemo(() => {
    const params = new URLSearchParams(location.search);
    return (params.get("job_id") || "").trim();
  }, [location.search]);
  const navigationState = (location.state as LeadDetailNavigationState | null) || null;
  const backTo = navigationState?.backTo || (user?.role === "dispatch" ? "/dispatch" : "/");
  const backLabel = navigationState?.backLabel || (user?.role === "dispatch" ? "← Back to Dispatch" : "← Back to Leads");

  async function loadLead() {
    const res = await fetch(`${API_BASE}/api/leads/${leadId}`, { headers: authHeaders(token) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    setLead(data);
    setEditCompanyId(String(data?.company_id || ""));
  }

  useEffect(() => {
    loadLead()
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [leadId, token]);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/users/sales-rep-commission-settings`, { headers: authHeaders(token) })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: CommissionSettingsResponse) => {
        const fallbackDefault = typeof data.default_percent === "number"
          ? data.default_percent
          : ((1 - 0.035) / 3) * 100;
        const nextMap = new Map<string, number>();
        for (const item of data.items || []) {
          if (!item || !item.user_id) continue;
          const effective = typeof item.effective_percent === "number" ? item.effective_percent : fallbackDefault;
          nextMap.set(item.user_id, effective);
        }
        if (!cancelled) {
          setDefaultCommissionPercent(fallbackDefault);
          setCommissionPercentByUserId(nextMap);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDefaultCommissionPercent(((1 - 0.035) / 3) * 100);
          setCommissionPercentByUserId(new Map());
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

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

  useEffect(() => {
    if (user?.role !== "admin") return;
    fetch(`${API_BASE}/api/users`, { headers: authHeaders(token) })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: unknown) => {
        const rows = Array.isArray(data) ? data : [];
        setUsers(
          rows
            .map((row) => {
              const item = row as Record<string, unknown>;
              return {
                id: String(item.id || ""),
                name: String(item.name || ""),
              };
            })
            .filter((item) => item.id)
            .sort((a, b) => a.name.localeCompare(b.name))
        );
      })
      .catch(() => setUsers([]));
  }, [token, user?.role]);

  async function loadAttachments(jobId?: string) {
    const targetJobId = jobId ?? activeJobTabId;
    if (!targetJobId || targetJobId === "__new__") {
      setAttachments([]);
      setAttachmentsLoading(false);
      return;
    }
    setAttachmentsLoading(true);
    setAttachmentsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs/${targetJobId}/attachments`, { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { items?: Array<Record<string, unknown>> };
      const rows = Array.isArray(data.items) ? data.items : [];
      setAttachments(rows.map((row) => ({
        id: String(row.id || ""),
        file_name: String(row.file_name || ""),
        content_type: String(row.content_type || "application/octet-stream"),
        file_size: Number(row.file_size || 0),
        created_at: String(row.created_at || ""),
        external_url: String(row.external_url || ""),
        is_external_link: Boolean(row.is_external_link),
        external_source: String(row.external_source || ""),
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
      stops: [...item.stops],
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
      const parseStops = (raw: unknown): string[] => {
        const source = Array.isArray(raw) ? raw : [];
        return source
          .map((entry) => {
            if (typeof entry === "string") return entry.trim();
            if (entry && typeof entry === "object") return String((entry as Record<string, unknown>).address || "").trim();
            return "";
          })
          .filter((value) => value);
      };
      const parsed: LeadJobItem[] = rows.map((item) => ({
        id: String(item.id || ""),
        lead_id: String(item.lead_id || ""),
        company_id: String(item.company_id || ""),
        company_name: String(item.company_name || ""),
        job_order: Number(item.job_order || 0),
        pickup_zip: String(item.pickup_zip || ""),
        delivery_zip: String(item.delivery_zip || ""),
        stops: parseStops(item.stops),
        move_date: String(item.move_date || ""),
        booked_move_date: String(item.booked_move_date || ""),
        price: item.price == null ? null : Number(item.price),
        charges: Array.isArray(item.charges)
          ? item.charges.map((charge) => {
              const row = charge as Record<string, unknown>;
              return {
                id: String(row.id || ""),
                job_id: String(row.job_id || ""),
                name: String(row.name || ""),
                description: String(row.description || ""),
                sort_order: Number(row.sort_order || 0),
                subtotal: Number(row.subtotal || 0),
                discount_amount: Number(row.discount_amount || 0),
                total_cost: Number(row.total_cost || 0),
              };
            })
          : [],
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
    if (!activeJobTabId || activeJobTabId === "__new__") {
      setAttachments([]);
      return;
    }
    void loadAttachments(activeJobTabId);
  }, [activeJobTabId]);

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
    if (
      routeJobId &&
      consumedRouteJobRef.current !== routeJobId &&
      leadJobs.some((job) => job.id === routeJobId)
    ) {
      consumedRouteJobRef.current = routeJobId;
      setActiveJobTabId(routeJobId);
      return;
    }
    if (!activeJobTabId || !leadJobs.some((job) => job.id === activeJobTabId)) {
      setActiveJobTabId(leadJobs[0].id);
    }
  }, [leadJobs, activeJobTabId, routeJobId]);

  async function saveJob(jobId: string) {
    if (user?.role === "dispatch") {
      setJobsError("Dispatch users are read-only");
      return;
    }
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
          stops: draft.stops,
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
    if (user?.role === "dispatch") {
      setJobsError("Dispatch users are read-only");
      return;
    }
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
          stops: newJobDraft.stops,
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
        stops: [],
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
    if (user?.role === "dispatch") {
      setJobsError("Dispatch users are read-only");
      return;
    }
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
    if (user?.role === "dispatch") {
      setAttachmentsError("Dispatch users are read-only");
      return;
    }
    if (files.length === 0) return;
    if (!activeJobTabId || activeJobTabId === "__new__") {
      setAttachmentsError("Please select a job tab before uploading files.");
      return;
    }
    setUploadingCount(files.length);
    setAttachmentsError("");
    try {
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs/${activeJobTabId}/attachments`, {
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
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs/${activeJobTabId}/attachments/${attachmentId}/download`, {
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
    if (user?.role === "dispatch") {
      setAttachmentsError("Dispatch users are read-only");
      return;
    }
    setAttachmentsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs/${activeJobTabId}/attachments/${attachmentId}`, {
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
    if (user?.role === "dispatch") {
      setAttachmentsError("Dispatch users are read-only");
      return;
    }
    const nextName = fileName.trim();
    if (!nextName) return;
    setAttachmentsError("");
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs/${activeJobTabId}/attachments/${attachmentId}`, {
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
      const res = await fetch(`${API_BASE}/api/leads/${leadId}/jobs/${activeJobTabId}/attachments/${attachmentId}/download`, {
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
      .slice(0, 6);
  }, [attachments]);

  useEffect(() => {
    function onDocMouseDown(event: MouseEvent) {
      const target = event.target as Node;
      if (companyMenuRef.current && !companyMenuRef.current.contains(target)) {
        setCompanyMenuOpen(false);
      }
      if (assignMenuRef.current && !assignMenuRef.current.contains(target)) {
        setAssignMenuOpen(false);
      }
      if (
        statusMenuRef.current
        && !statusMenuRef.current.contains(target)
        && !statusMenuPopoverRef.current?.contains(target)
      ) {
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
  const canEditLead = !isDispatchUser;
  const canEditJobs = !isDispatchUser;

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

  const estimatedTotalData = (() => {
    const raw = lead.estimatedTotal ?? lead.estimated_total;
    if (!raw || typeof raw !== "object") return null;
    const row = raw as Record<string, unknown>;
    const subtotal = Number(row.subtotal ?? 0);
    const taxableAmount = Number(row.taxableAmount ?? row.taxable_amount ?? 0);
    const tax = Number(row.tax ?? 0);
    const finalTotal = Number(row.finalTotal ?? row.final_total ?? 0);
    const values = [subtotal, taxableAmount, tax, finalTotal];
    if (values.some((value) => !Number.isFinite(value))) return null;
    return { subtotal, taxableAmount, tax, finalTotal };
  })();

  const estimatedDiscountAmount = estimatedTotalData
    ? Math.max(0, estimatedTotalData.subtotal - estimatedTotalData.finalTotal)
    : 0;
  const showEstimatedDiscount = Boolean(estimatedTotalData && estimatedDiscountAmount > 0);
  const estimatedDiscountPercent = showEstimatedDiscount && estimatedTotalData && estimatedTotalData.subtotal > 0
    ? (estimatedDiscountAmount / estimatedTotalData.subtotal) * 100
    : 0;

  const paymentsData = (() => {
    const raw = lead.payments;
    if (!Array.isArray(raw)) return [];
    return raw
      .map((row) => {
        if (!row || typeof row !== "object") return null;
        const item = row as Record<string, unknown>;
        const amount = Number(item.amount ?? 0);
        if (!Number.isFinite(amount)) return null;
        return {
          amount,
          takenByUser: String(item.takenByUser ?? "").trim(),
          repPaid: Boolean(item.repPaid ?? false),
          repPaidAt: String(item.repPaidAt ?? "").trim(),
        };
      })
      .filter((row): row is { amount: number; takenByUser: string; repPaid: boolean; repPaidAt: string } => row !== null);
  })();
  const paymentsTotal = paymentsData.reduce((sum, payment) => sum + payment.amount, 0);
  const canManageRepPayments = user?.role === "admin" || user?.role === "sales_rep";

  function formatMoney(value: number): string {
    return `$${value.toFixed(2)}`;
  }

  function repPaidCommissionAmount(paymentAmount: number): number {
    const assignedTo = String(lead?.assigned_to || "").trim();
    const commissionPercent = assignedTo
      ? (commissionPercentByUserId.get(assignedTo) ?? defaultCommissionPercent)
      : defaultCommissionPercent;
    return paymentAmount * (commissionPercent / 100);
  }

  function repPaidCommissionRatePercent(): number {
    const assignedTo = String(lead?.assigned_to || "").trim();
    if (!assignedTo) return defaultCommissionPercent;
    return commissionPercentByUserId.get(assignedTo) ?? defaultCommissionPercent;
  }

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

  async function deleteLead() {
    if (!leadId) return;
    if (!window.confirm("Delete this lead and all related records? This cannot be undone.")) return;
    setDeletingLead(true);
    try {
      const res = await fetch(`${API_BASE}/api/leads/${leadId}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(String((err as { detail?: unknown }).detail || `HTTP ${res.status}`));
      }
      navigate(backTo);
    } catch (e) {
      alert(`Failed to delete lead: ${e instanceof Error ? e.message : "error"}`);
    } finally {
      setDeletingLead(false);
    }
  }

  async function setRepPaymentPaid(paymentIndex: number, nextPaid: boolean) {
    if (!leadId || !canManageRepPayments) return;
    if (paymentIndex < 0 || paymentIndex >= paymentsData.length) return;

    setSavingRepPaymentIndex(paymentIndex);
    try {
      const nextPayments = paymentsData.map((payment, index) => {
        if (index !== paymentIndex) {
          return {
            amount: payment.amount,
            takenByUser: payment.takenByUser,
            repPaid: payment.repPaid,
            repPaidAt: payment.repPaidAt,
          };
        }
        return {
          amount: payment.amount,
          takenByUser: payment.takenByUser,
          repPaid: nextPaid,
          repPaidAt: nextPaid ? (payment.repPaidAt || new Date().toISOString()) : "",
        };
      });

      const res = await fetch(`${API_BASE}/api/leads/${leadId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({ payments: nextPayments }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = await res.json();
      setLead(updated);
    } catch (e) {
      alert(`Failed to update rep payment: ${e instanceof Error ? e.message : "error"}`);
    } finally {
      setSavingRepPaymentIndex(null);
    }
  }

  return (
    <div style={{ width: "100%", height: "calc(100vh - 52px)", overflowY: "auto", overflowX: "hidden", boxSizing: "border-box", padding: "24px clamp(16px, 3vw, 28px) 40px", background: "#f6f8fb", fontFamily: "inherit" }}>
      <div style={{ width: "100%", maxWidth: 1120, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <button
          onClick={() => navigate(backTo)}
          style={{
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
          {backLabel}
        </button>
        {user?.role === "admin" ? (
          <button
            type="button"
            onClick={() => void deleteLead()}
            disabled={deletingLead}
            style={{
              padding: "6px 12px",
              border: "1px solid #fca5a5",
              borderRadius: 6,
              background: "#fff1f2",
              color: "#b91c1c",
              fontSize: 12,
              fontWeight: 700,
              cursor: deletingLead ? "default" : "pointer",
            }}
          >
            {deletingLead ? "Deleting..." : "Delete Lead"}
          </button>
        ) : null}
      </div>

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
                          {attachment.is_external_link ? "Open Link" : "Preview"}
                        </button>
                        <button
                          type="button"
                          onClick={() => void downloadAttachment(attachment.id, attachment.file_name)}
                          style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "4px 8px", fontSize: 12, fontWeight: 600 }}
                        >
                          {attachment.is_external_link ? "Open" : "Download"}
                        </button>
                        {canEditJobs ? (
                          <>
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
                          </>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {/* Client highlights card */}
      {(() => {
        const name = String(lead.full_name || "").trim();
        const phone = String(lead.phone_number || "").trim();
        const email = String(lead.email || "").trim();
        const moveSize = String(lead.move_size || "").trim();
        const volumeRaw = lead.volume;
        const weightRaw = lead.weight;
        const volume = typeof volumeRaw === "number" ? volumeRaw : Number(volumeRaw);
        const weight = typeof weightRaw === "number" ? weightRaw : Number(weightRaw);
        const hasVolume = Number.isFinite(volume);
        const hasWeight = Number.isFinite(weight);
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
          setEditMoveSize(moveSize);
          setEditingUser(true);
        }

        async function saveUser() {
          if (!canEditLead) return;
          setSavingUser(true);
          try {
            const res = await fetch(`${API_BASE}/api/leads/${leadId}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json", ...authHeaders(token) },
              body: JSON.stringify({
                full_name: editName,
                phone_number: editPhone,
                email: editEmail,
                move_size: editMoveSize,
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
          if (!canEditLead) return;
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
          if (!canEditLead) return;
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

        async function saveAssignedTo(nextAssignedTo: string) {
          if (!canEditLead) return;
          const currentAssignedTo = String(lead?.assigned_to || "");
          if (nextAssignedTo === currentAssignedTo) {
            setAssignMenuOpen(false);
            return;
          }
          setSavingAssignedTo(true);
          try {
            const res = await fetch(`${API_BASE}/api/leads/${leadId}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json", ...authHeaders(token) },
              body: JSON.stringify({ assigned_to: nextAssignedTo }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const updated = await res.json();
            setLead(updated);
            setAssignMenuOpen(false);
          } catch (e) {
            alert(`Failed to save assignee: ${e instanceof Error ? e.message : "error"}`);
          } finally {
            setSavingAssignedTo(false);
          }
        }

        async function refreshFromSmartmoving() {
          if (!canEditLead) return;
          setRefreshingSmartmoving(true);
          try {
            const res = await fetch(`${API_BASE}/api/leads/${leadId}/refresh-smartmoving`, {
              method: "POST",
              headers: authHeaders(token),
            });
            if (!res.ok) {
              let detail = `HTTP ${res.status}`;
              try {
                const err = await res.json();
                detail = String(err?.detail || detail);
              } catch {
                // Keep default status detail.
              }
              throw new Error(detail);
            }
            const updated = await res.json();
            setLead(updated);
            setEditCompanyId(String(updated?.company_id || ""));
            await loadLeadJobs();
          } catch (e) {
            alert(`Failed to refresh from SmartMoving: ${e instanceof Error ? e.message : "error"}`);
          } finally {
            setRefreshingSmartmoving(false);
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
        const assignedToName = String(lead.assigned_to_name || "").trim() || "Unassigned";

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
                          onClick={() => canEditLead && setStatusMenuOpen((v) => !v)}
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
                            cursor: canEditLead ? "pointer" : "default",
                            boxShadow: "0 1px 2px rgba(15,23,42,.08)",
                            ...statusStyle,
                          }}
                        >
                          {statusLabel}
                          {canEditLead ? <span style={{ fontSize: 9, lineHeight: 1, opacity: 0.9 }}>▾</span> : null}
                        </button>
                      </div>
                      {canEditLead && statusMenuOpen && statusMenuRect ? createPortal(
                        <div
                          ref={statusMenuPopoverRef}
                          role="menu"
                          onMouseDown={(e) => e.stopPropagation()}
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
                      <div ref={assignMenuRef} style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
                        <button
                          type="button"
                          onClick={() => user?.role === "admin" && setAssignMenuOpen((v) => !v)}
                          disabled={user?.role !== "admin" || savingAssignedTo}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            maxWidth: 280,
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
                            cursor: user?.role === "admin" ? "pointer" : "default",
                            boxShadow: "0 1px 2px rgba(15,23,42,.08)",
                          }}
                          title={assignedToName}
                        >
                          <span style={{ color: "#64748b" }}>Assign To</span>
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#1e293b" }}>
                            {savingAssignedTo ? "Updating..." : assignedToName}
                          </span>
                          <span style={{ fontSize: 9, lineHeight: 1, opacity: 0.9 }}>▾</span>
                        </button>
                        {user?.role === "admin" && assignMenuOpen ? (
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
                              Change assignee
                            </div>
                            <button
                              type="button"
                              onClick={() => void saveAssignedTo("")}
                              disabled={savingAssignedTo}
                              style={{
                                width: "100%",
                                textAlign: "left",
                                border: "none",
                                background: !lead.assigned_to ? "#f8fafc" : "#fff",
                                color: !lead.assigned_to ? "#0f172a" : "#1e293b",
                                padding: "10px 12px",
                                fontSize: 13,
                                cursor: "pointer",
                              }}
                            >
                              Unassigned{!lead.assigned_to ? " (current)" : ""}
                            </button>
                            {users.map((option) => {
                              const isCurrent = option.id === String(lead.assigned_to || "");
                              return (
                                <button
                                  key={option.id}
                                  type="button"
                                  onClick={() => void saveAssignedTo(option.id)}
                                  disabled={savingAssignedTo}
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
                                  {option.name}{isCurrent ? " (current)" : ""}
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
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    type="button"
                    onClick={() => void refreshFromSmartmoving()}
                    disabled={refreshingSmartmoving || !String(lead.smartmoving_id || "").trim()}
                    title="Refresh from SmartMoving"
                    style={{ padding: "5px 10px", border: "1px solid #cbd5e1", borderRadius: 4, background: "#fff", fontSize: 12, color: "#334155", cursor: refreshingSmartmoving ? "default" : "pointer" }}
                  >
                    {refreshingSmartmoving ? "Refreshing..." : "Refresh SmartMoving"}
                  </button>
                  <button
                    type="button"
                    onClick={startEditUser}
                    disabled={!canEditLead}
                    title="Edit"
                    style={{ padding: "5px 10px", border: "1px solid #dddbda", borderRadius: 4, background: "#fff", fontSize: 12, color: "#0176d3", cursor: canEditLead ? "pointer" : "default", opacity: canEditLead ? 1 : 0.6 }}
                  >
                    ✎ Edit
                  </button>
                </div>
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
                <span style={{ fontSize: 18 }}>📦</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={tileLabel}>Move Size</div>
                  {editingUser ? (
                    <input
                      value={editMoveSize}
                      onChange={(e) => setEditMoveSize(e.target.value)}
                      placeholder="Move size"
                      style={{ width: "100%", fontSize: 14, padding: "3px 6px", border: "1px solid #dddbda", borderRadius: 4 }}
                    />
                  ) : moveSize ? (
                    <span style={{ fontSize: 14, color: "#334155", fontWeight: 600 }}>{moveSize}</span>
                  ) : (
                    <span style={{ fontSize: 14, color: "#706e6b" }}>—</span>
                  )}
                </div>
              </div>
              <div style={tile}>
                <span style={{ fontSize: 18 }}>⚖️</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={tileLabel}>Volume / Weight</div>
                  {(hasVolume || hasWeight) ? (
                    <span style={{ fontSize: 14, color: "#334155", fontWeight: 600 }}>
                      {hasVolume ? volume.toFixed(2) : "—"} / {hasWeight ? weight.toFixed(2) : "—"}
                    </span>
                  ) : (
                    <span style={{ fontSize: 14, color: "#706e6b" }}>—</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      <div style={sectionStyle}>
        <div style={sectionHeader}>Jobs</div>
        <div style={{ padding: 12, display: "grid", gap: 12 }}>
          {estimatedTotalData ? (
            <div style={{ border: "1px solid #d8dde6", borderRadius: 8, background: "#f8fafc", overflow: "hidden" }}>
              <div style={{ padding: "8px 10px", borderBottom: "1px solid #e2e8f0", fontSize: 12, fontWeight: 700, color: "#0f172a", letterSpacing: "0.02em" }}>
                Lead Estimated Total
              </div>
              <div style={{ padding: 10, display: "grid", gap: 6 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 12, color: "#334155" }}>
                  <span>Subtotal</span>
                  <strong>{formatMoney(estimatedTotalData.subtotal)}</strong>
                </div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 12, color: "#334155" }}>
                  <span>Taxable Amount</span>
                  <strong>{formatMoney(estimatedTotalData.taxableAmount)}</strong>
                </div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 12, color: "#334155" }}>
                  <span>Tax</span>
                  <strong>{formatMoney(estimatedTotalData.tax)}</strong>
                </div>
                {showEstimatedDiscount ? (
                  <>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 12, color: "#0f766e" }}>
                      <span>Discount %</span>
                      <strong>{`${estimatedDiscountPercent.toFixed(2)}%`}</strong>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 12, color: "#0f766e" }}>
                      <span>Discount Amount</span>
                      <strong>{formatMoney(estimatedDiscountAmount)}</strong>
                    </div>
                  </>
                ) : null}
                <div style={{ borderTop: "1px solid #dbe4ef", marginTop: 2, paddingTop: 8, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 12, color: "#0f172a" }}>
                  <span style={{ fontWeight: 700 }}>Final Total</span>
                  <strong>{formatMoney(estimatedTotalData.finalTotal)}</strong>
                </div>
              </div>
            </div>
          ) : null}
          {paymentsData.length > 0 ? (
            <div style={{ border: "1px solid #d8dde6", borderRadius: 8, background: "#f8fafc", overflow: "hidden" }}>
              <div style={{ padding: "8px 10px", borderBottom: "1px solid #e2e8f0", fontSize: 12, fontWeight: 700, color: "#0f172a", letterSpacing: "0.02em" }}>
                Payments
              </div>
              <div style={{ padding: 10, display: "grid", gap: 6 }}>
                {paymentsData.map((payment, index) => (
                  <div key={`${payment.takenByUser}-${index}`} style={{ display: "grid", gap: 4, borderBottom: index < paymentsData.length - 1 ? "1px solid #e2e8f0" : "none", paddingBottom: 6, marginBottom: 2 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 12, color: "#334155" }}>
                      <span>{payment.takenByUser || `Payment ${index + 1}`}</span>
                      <strong>{formatMoney(payment.amount)}</strong>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 11 }}>
                      <span style={{ color: "#475569" }}>Rep paid ({repPaidCommissionRatePercent().toFixed(6)}%): <strong>{formatMoney(repPaidCommissionAmount(payment.amount))}</strong></span>
                      {canManageRepPayments ? (
                        <label style={{ display: "inline-flex", alignItems: "center", gap: 6, color: payment.repPaid ? "#15803d" : "#92400e", fontWeight: 700 }}>
                          <input
                            type="checkbox"
                            checked={payment.repPaid}
                            disabled={savingRepPaymentIndex === index}
                            onChange={(e) => {
                              void setRepPaymentPaid(index, e.target.checked);
                            }}
                          />
                          {payment.repPaid ? "Paid to rep" : "Unpaid to rep"}
                        </label>
                      ) : (
                        <span style={{ color: payment.repPaid ? "#15803d" : "#92400e", fontWeight: 700 }}>
                          {payment.repPaid ? "Paid to rep" : "Unpaid to rep"}
                        </span>
                      )}
                    </div>
                    {payment.repPaid && payment.repPaidAt ? (
                      <div style={{ fontSize: 10, color: "#64748b" }}>Paid at: {new Date(payment.repPaidAt).toLocaleString()}</div>
                    ) : null}
                  </div>
                ))}
                <div style={{ borderTop: "1px solid #dbe4ef", marginTop: 2, paddingTop: 8, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 12, color: "#0f172a" }}>
                  <span style={{ fontWeight: 700 }}>Total Payments</span>
                  <strong>{formatMoney(paymentsTotal)}</strong>
                </div>
                {estimatedTotalData && estimatedTotalData.finalTotal > 0 ? (() => {
                  const remaining = estimatedTotalData.finalTotal - paymentsTotal;
                  const remainingPercent = (remaining / estimatedTotalData.finalTotal) * 100;
                  const isPaid = remaining <= 0;
                  return (
                    <div style={{ borderTop: "1px solid #dbe4ef", marginTop: 2, paddingTop: 8, display: "grid", gap: 4 }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 12, color: isPaid ? "#15803d" : "#b91c1c", fontWeight: 700 }}>
                        <span>Remaining Balance</span>
                        <span>{isPaid ? formatMoney(0) : formatMoney(remaining)}</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, fontSize: 11, color: isPaid ? "#15803d" : "#b91c1c" }}>
                        <span>{isPaid ? "Paid in full" : `${Math.max(0, remainingPercent).toFixed(1)}% remaining`}</span>
                        <span>{isPaid ? "✓" : `${(100 - Math.max(0, remainingPercent)).toFixed(1)}% paid`}</span>
                      </div>
                    </div>
                  );
                })() : null}
              </div>
            </div>
          ) : null}
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
                {canEditJobs ? (
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
                ) : null}
              </div>

              {activeJobTabId !== "__new__" && leadJobs.some((j) => j.id === activeJobTabId) ? (() => {
                const job = leadJobs.find((j) => j.id === activeJobTabId)!;
                const draft = jobDrafts[job.id] || draftFromJob(job);
                const primary = job.job_order === 1;
                const busy = savingJobId === job.id || deletingJobId === job.id;
                const chargesSubtotal = job.charges.reduce((sum, charge) => sum + charge.subtotal, 0);
                const chargesDiscount = job.charges.reduce((sum, charge) => sum + charge.discount_amount, 0);
                const chargesTotal = job.charges.reduce((sum, charge) => sum + charge.total_cost, 0);
                return (
                  <div style={{ border: "1px solid #e2e8f0", borderRadius: 8, padding: 10, background: primary ? "#f8fbff" : "#fff" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <button
                          type="button"
                          onClick={() => navigate(`/dispatch?job_id=${encodeURIComponent(job.id)}`)}
                          style={{ border: "1px solid #cbd5e1", background: "#fff", color: "#334155", borderRadius: 4, padding: "2px 6px", fontSize: 12, cursor: "pointer" }}
                          title="Open in calender"
                          aria-label="Open in calender"
                        >
                          📅
                        </button>
                        {primary ? <span style={{ fontSize: 11, color: "#1d4ed8", fontWeight: 700 }}>Primary</span> : null}
                      </div>
                    </div>

                    <div style={{ display: "grid", gap: 8, gridTemplateColumns: "minmax(220px, 1fr) 170px 170px" }}>
                      <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                        Company
                        <select
                          value={draft.company_id}
                          onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, company_id: e.target.value } }))}
                          disabled={!canEditJobs}
                          style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12, background: "#fff" }}
                        >
                          {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
                        </select>
                      </label>
                      <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                        Move Date
                        <input type="date" value={draft.move_date} onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, move_date: e.target.value } }))} disabled={!canEditJobs} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
                      </label>
                      <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                        Booked Date
                        <input type="date" value={draft.booked_move_date} onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, booked_move_date: e.target.value } }))} disabled={!canEditJobs} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12 }} />
                      </label>
                      <div style={{ gridColumn: "1 / -1", border: "1px solid #d8e6f4", borderRadius: 12, background: "linear-gradient(180deg, #f7fbff 0%, #ffffff 100%)", boxShadow: "0 2px 8px rgba(15,23,42,.05)", overflow: "hidden" }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "10px 12px", borderBottom: "1px solid #e4eef8", background: "#edf5fd" }}>
                          <strong style={{ fontSize: 12, color: "#0f172a", letterSpacing: "0.03em" }}>ROUTE</strong>
                          <span style={{ fontSize: 11, color: "#0369a1", fontWeight: 700 }}>{draft.stops.length} middle stop{draft.stops.length === 1 ? "" : "s"}</span>
                        </div>

                        <div style={{ display: "grid", gap: 10, padding: 12 }}>
                          <label style={{ display: "grid", gap: 4, fontSize: 12, fontWeight: 700, color: "#1e3a8a" }}>
                            Pickup
                            <input
                              value={draft.pickup_zip}
                              onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, pickup_zip: e.target.value } }))}
                              disabled={!canEditJobs}
                              placeholder="Pickup address"
                              style={{ border: "1px solid #bfdbfe", borderRadius: 8, padding: "8px 10px", fontSize: 13, background: "#fff" }}
                            />
                          </label>

                          <div style={{ display: "grid", gap: 8 }}>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                              <div style={{ fontSize: 12, color: "#334155", fontWeight: 700 }}>Stops</div>
                              {canEditJobs ? (
                                <button
                                  type="button"
                                  onClick={() => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, stops: [...draft.stops, ""] } }))}
                                  style={{ border: "1px solid #2563eb", background: "#fff", color: "#1d4ed8", borderRadius: 8, padding: "5px 10px", fontSize: 11, fontWeight: 700 }}
                                >Add Stop</button>
                              ) : null}
                            </div>

                            {draft.stops.length === 0 ? (
                              <div style={{ border: "1px dashed #cbd5e1", borderRadius: 8, padding: "9px 10px", fontSize: 12, color: "#64748b", background: "#f8fafc" }}>No middle stops</div>
                            ) : null}

                            {draft.stops.map((address, index) => (
                              <div
                                key={`stop-${index}`}
                                draggable={canEditJobs}
                                onDragStart={(e) => {
                                  e.dataTransfer.setData("text/plain", String(index));
                                  e.dataTransfer.effectAllowed = "move";
                                }}
                                onDragOver={(e) => e.preventDefault()}
                                onDrop={(e) => {
                                  e.preventDefault();
                                  const from = Number(e.dataTransfer.getData("text/plain"));
                                  if (!Number.isInteger(from) || from < 0 || from >= draft.stops.length || from === index) return;
                                  const next = [...draft.stops];
                                  const [moved] = next.splice(from, 1);
                                  next.splice(index, 0, moved);
                                  setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, stops: next } }));
                                }}
                                style={{ display: "grid", gridTemplateColumns: "28px 1fr auto", gap: 8, alignItems: "center", border: "1px solid #dbe4ef", borderRadius: 8, background: "#fff", padding: 8 }}
                              >
                                <span title="Drag" style={{ width: 24, height: 24, borderRadius: 6, border: "1px solid #cbd5e1", color: "#64748b", fontSize: 12, fontWeight: 800, display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: canEditJobs ? "grab" : "default", userSelect: "none" }}>⋮⋮</span>
                                <input
                                  value={address}
                                  onChange={(e) => {
                                    const next = [...draft.stops];
                                    next[index] = e.target.value;
                                    setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, stops: next } }));
                                  }}
                                  disabled={!canEditJobs}
                                  placeholder="Stop address"
                                  style={{ border: "1px solid #cbd5e1", borderRadius: 8, padding: "8px 10px", fontSize: 13, background: "#fff" }}
                                />
                                {canEditJobs ? (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      const next = draft.stops.filter((_, i) => i !== index);
                                      setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, stops: next } }));
                                    }}
                                    style={{ border: "1px solid #fecaca", background: "#fff", color: "#b91c1c", borderRadius: 8, padding: "5px 10px", fontSize: 11, fontWeight: 700 }}
                                  >Remove</button>
                                ) : null}
                              </div>
                            ))}
                          </div>

                          <label style={{ display: "grid", gap: 4, fontSize: 12, fontWeight: 700, color: "#166534" }}>
                            Delivery
                            <input
                              value={draft.delivery_zip}
                              onChange={(e) => setJobDrafts((prev) => ({ ...prev, [job.id]: { ...draft, delivery_zip: e.target.value } }))}
                              disabled={!canEditJobs}
                              placeholder="Delivery address"
                              style={{ border: "1px solid #bbf7d0", borderRadius: 8, padding: "8px 10px", fontSize: 13, background: "#fff" }}
                            />
                          </label>
                        </div>
                      </div>
                    </div>

                    {canEditJobs ? (
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
                    ) : null}

                    <div style={{ marginTop: 12, border: "1px solid #d8dde6", borderRadius: 8, background: "#f8fafc" }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "8px 10px", borderBottom: "1px solid #e2e8f0" }}>
                        <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                          <span style={{ fontSize: 14 }}>📎</span>
                          <strong style={{ fontSize: 12, color: "#0f172a", letterSpacing: "0.02em" }}>{`Job ${job.job_order} Files`}</strong>
                          <span style={{ fontSize: 10, color: "#334155", fontWeight: 700, border: "1px solid #cbd5e1", borderRadius: 999, padding: "2px 7px", background: "#fff" }}>
                            {attachments.length} total
                          </span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          {canEditJobs ? (
                            <label style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8, border: "1px solid #d8dde6", borderRadius: 6, padding: "5px 9px", fontSize: 11, fontWeight: 700, cursor: uploadingCount > 0 ? "default" : "pointer", opacity: uploadingCount > 0 ? 0.7 : 1, background: "#fff", whiteSpace: "nowrap" }}>
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
                          ) : null}
                          <button
                            type="button"
                            onClick={() => setFilesModalOpen(true)}
                            style={{ border: "1px solid #0176d3", background: "#fff", color: "#0176d3", borderRadius: 6, padding: "5px 9px", fontSize: 11, fontWeight: 700 }}
                          >
                            More
                          </button>
                        </div>
                      </div>

                      <div style={{ padding: 10, display: "grid", gap: 6 }}>
                        {attachmentsError ? <div style={{ color: "#ba0517", fontSize: 12 }}>{attachmentsError}</div> : null}
                        {attachmentsLoading ? <div style={{ color: "#64748b", fontSize: 12 }}>Loading files...</div> : null}
                        {!attachmentsLoading && quickAttachments.length === 0 ? <div style={{ color: "#706e6b", fontSize: 12 }}>No files for this job yet.</div> : null}
                        {!attachmentsLoading && quickAttachments.length > 0 ? (
                          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 7 }}>
                            {quickAttachments.map((attachment) => (
                              <button
                                key={attachment.id}
                                type="button"
                                onClick={() => void openPreview(attachment.id, attachment.file_name, attachment.content_type)}
                                style={{ border: "1px solid #dbe4ef", background: "#fff", borderRadius: 8, padding: "8px", fontSize: 11, color: "#334155", textAlign: "left", cursor: "pointer", display: "grid", gap: 4 }}
                                title={attachment.file_name}
                              >
                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                                  <span style={{ fontSize: 10, fontWeight: 800, color: "#0f172a", border: "1px solid #cbd5e1", borderRadius: 999, padding: "1px 6px", background: "#f8fafc", flexShrink: 0 }}>
                                    {fileIcon(attachment.file_name)}
                                  </span>
                                  <span style={{ fontSize: 10, color: "#64748b" }}>{Math.max(1, Math.round((attachment.file_size || 0) / 1024))} KB</span>
                                </div>
                                <div style={{ fontSize: 12, color: "#0f172a", fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  {attachment.file_name}
                                </div>
                                <div style={{ fontSize: 10, color: "#64748b" }}>
                                  {attachment.created_at ? new Date(attachment.created_at).toLocaleDateString() : ""}
                                </div>
                              </button>
                            ))}
                            {attachments.length > quickAttachments.length ? (
                              <button
                                type="button"
                                onClick={() => setFilesModalOpen(true)}
                                style={{ border: "1px dashed #94a3b8", background: "#f8fafc", borderRadius: 8, padding: "8px", fontSize: 11, color: "#334155", textAlign: "center", fontWeight: 700, cursor: "pointer" }}
                              >
                                View all {attachments.length} files
                              </button>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    </div>

                    <div style={{ marginTop: 12, border: "1px solid #d8dde6", borderRadius: 8, background: "#f8fafc" }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "8px 10px", borderBottom: "1px solid #e2e8f0" }}>
                        <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                          <span style={{ fontSize: 14 }}>$</span>
                          <strong style={{ fontSize: 12, color: "#0f172a", letterSpacing: "0.02em" }}>Charges</strong>
                        </div>
                      </div>

                      <div style={{ padding: 10, display: "grid", gap: 6 }}>
                        {job.charges.length > 0 ? (
                          <div style={{ border: "1px solid #e2e8f0", background: "#fff", borderRadius: 6, padding: 8, display: "grid", gap: 4 }}>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 12, color: "#334155" }}>
                              <span>Subtotal</span>
                              <strong>${chargesSubtotal.toFixed(2)}</strong>
                            </div>
                            {chargesDiscount > 0 ? (
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 12, color: "#0f766e" }}>
                                <span>Discount</span>
                                <strong>- ${chargesDiscount.toFixed(2)}</strong>
                              </div>
                            ) : null}
                            <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: 6, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 12, color: "#0f172a" }}>
                              <span style={{ fontWeight: 700 }}>Total</span>
                              <strong>${chargesTotal.toFixed(2)}</strong>
                            </div>
                          </div>
                        ) : null}
                        {job.charges.length === 0 ? <div style={{ color: "#706e6b", fontSize: 12 }}>No charges for this job yet.</div> : null}
                        {job.charges.length > 0 ? (
                          <div style={{ display: "grid", gap: 6 }}>
                            {job.charges.map((charge) => (
                              <div key={charge.id} style={{ border: "1px solid #e2e8f0", background: "#fff", borderRadius: 6, padding: 8, display: "grid", gap: 4 }}>
                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                                  <strong style={{ fontSize: 12, color: "#0f172a" }}>{charge.name}</strong>
                                  <span style={{ fontSize: 12, color: "#0f172a", fontWeight: 700 }}>${charge.total_cost.toFixed(2)}</span>
                                </div>
                                {charge.description ? <div style={{ fontSize: 11, color: "#475569" }}>{charge.description}</div> : null}
                                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: "#64748b" }}>
                                  <span>{`Subtotal: $${charge.subtotal.toFixed(2)}`}</span>
                                  <span>{`Discount: $${charge.discount_amount.toFixed(2)}`}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              })() : null}
            </div>
          ) : null}

          {activeJobTabId === "__new__" && canEditJobs ? (
          <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: 10, display: "grid", gap: 8 }}>
            <strong style={{ fontSize: 12, color: "#334155" }}>Add Job</strong>
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "grid", gap: 8, gridTemplateColumns: "minmax(220px, 1fr) 170px 170px" }}>
              <label style={{ display: "grid", gap: 4, fontSize: 11, color: "#475569" }}>
                Company
                <select value={newJobDraft.company_id} onChange={(e) => setNewJobDraft((prev) => ({ ...prev, company_id: e.target.value }))} style={{ border: "1px solid #cbd5e1", borderRadius: 4, padding: "6px 8px", fontSize: 12, background: "#fff" }}>
                  {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
                </select>
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
              <div style={{ gridColumn: "1 / -1", border: "1px solid #d8e6f4", borderRadius: 12, background: "linear-gradient(180deg, #f7fbff 0%, #ffffff 100%)", boxShadow: "0 2px 8px rgba(15,23,42,.05)", overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "10px 12px", borderBottom: "1px solid #e4eef8", background: "#edf5fd" }}>
                  <strong style={{ fontSize: 12, color: "#0f172a", letterSpacing: "0.03em" }}>ROUTE</strong>
                  <span style={{ fontSize: 11, color: "#0369a1", fontWeight: 700 }}>{newJobDraft.stops.length} middle stop{newJobDraft.stops.length === 1 ? "" : "s"}</span>
                </div>

                <div style={{ display: "grid", gap: 10, padding: 12 }}>
                  <label style={{ display: "grid", gap: 4, fontSize: 12, fontWeight: 700, color: "#1e3a8a" }}>
                    Pickup
                    <input
                      type="text"
                      value={newJobDraft.pickup_zip}
                      onChange={(e) => setNewJobDraft((prev) => ({ ...prev, pickup_zip: e.target.value }))}
                      placeholder="Pickup address"
                      style={{ border: "1px solid #bfdbfe", borderRadius: 8, padding: "8px 10px", fontSize: 13, background: "#fff" }}
                    />
                  </label>

                  <div style={{ display: "grid", gap: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                      <div style={{ fontSize: 12, color: "#334155", fontWeight: 700 }}>Stops</div>
                      <button
                        type="button"
                        onClick={() => setNewJobDraft((prev) => ({ ...prev, stops: [...prev.stops, ""] }))}
                        style={{ border: "1px solid #2563eb", background: "#fff", color: "#1d4ed8", borderRadius: 8, padding: "5px 10px", fontSize: 11, fontWeight: 700 }}
                      >Add Stop</button>
                    </div>

                    {newJobDraft.stops.length === 0 ? (
                      <div style={{ border: "1px dashed #cbd5e1", borderRadius: 8, padding: "9px 10px", fontSize: 12, color: "#64748b", background: "#f8fafc" }}>No middle stops</div>
                    ) : null}

                    {newJobDraft.stops.map((address, index) => (
                      <div
                        key={`new-stop-${index}`}
                        draggable
                        onDragStart={(e) => {
                          e.dataTransfer.setData("text/plain", String(index));
                          e.dataTransfer.effectAllowed = "move";
                        }}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={(e) => {
                          e.preventDefault();
                          const from = Number(e.dataTransfer.getData("text/plain"));
                          if (!Number.isInteger(from) || from < 0 || from >= newJobDraft.stops.length || from === index) return;
                          const next = [...newJobDraft.stops];
                          const [moved] = next.splice(from, 1);
                          next.splice(index, 0, moved);
                          setNewJobDraft((prev) => ({ ...prev, stops: next }));
                        }}
                        style={{ display: "grid", gridTemplateColumns: "28px 1fr auto", gap: 8, alignItems: "center", border: "1px solid #dbe4ef", borderRadius: 8, background: "#fff", padding: 8 }}
                      >
                        <span title="Drag" style={{ width: 24, height: 24, borderRadius: 6, border: "1px solid #cbd5e1", color: "#64748b", fontSize: 12, fontWeight: 800, display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: "grab", userSelect: "none" }}>⋮⋮</span>
                        <input
                          value={address}
                          onChange={(e) => {
                            const next = [...newJobDraft.stops];
                            next[index] = e.target.value;
                            setNewJobDraft((prev) => ({ ...prev, stops: next }));
                          }}
                          placeholder="Stop address"
                          style={{ border: "1px solid #cbd5e1", borderRadius: 8, padding: "8px 10px", fontSize: 13, background: "#fff" }}
                        />
                        <button
                          type="button"
                          onClick={() => {
                            setNewJobDraft((prev) => ({ ...prev, stops: prev.stops.filter((_, i) => i !== index) }));
                          }}
                          style={{ border: "1px solid #fecaca", background: "#fff", color: "#b91c1c", borderRadius: 8, padding: "5px 10px", fontSize: 11, fontWeight: 700 }}
                        >Remove</button>
                      </div>
                    ))}
                  </div>

                  <label style={{ display: "grid", gap: 4, fontSize: 12, fontWeight: 700, color: "#166534" }}>
                    Delivery
                    <input
                      type="text"
                      value={newJobDraft.delivery_zip}
                      onChange={(e) => setNewJobDraft((prev) => ({ ...prev, delivery_zip: e.target.value }))}
                      placeholder="Delivery address"
                      style={{ border: "1px solid #bbf7d0", borderRadius: 8, padding: "8px 10px", fontSize: 13, background: "#fff" }}
                    />
                  </label>
                </div>
              </div>
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

      {!isDispatchUser && (user?.role === "admin" || user?.role === "sales_rep") &&
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
