import { useEffect, useState } from "react";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";

type Rep = {
  id: string;
  name: string;
  email: string;
  role: string;
  phone?: string;
};

type AdminUnavailabilityWindow = {
  id: string;
  admin_user_id: string;
  start_at: string;
  end_at: string;
  reason?: string;
  available_rep_ids?: string[];
  available_reps?: Array<{
    id: string;
    name: string;
    email: string;
    phone?: string;
  }>;
};

type RepSlot = {
  id?: string;
  start: string;
  end: string;
};

type RepAvailabilityWindow = {
  id: string;
  rep_user_id: string;
  start_at: string;
  end_at: string;
  reason?: string;
};

function toMs(value: string | undefined): number {
  if (!value) return 0;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? 0 : d.getTime();
}

function prettyDate(value: string | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function toLocalInputValue(value: string | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function PeriodAssignPage() {
  const { token } = useAuth();
  const [nowMs, setNowMs] = useState<number>(Date.now());
  const [reps, setReps] = useState<Rep[]>([]);
  const [admins, setAdmins] = useState<Rep[]>([]);
  const [loadingReps, setLoadingReps] = useState(true);
  const [loadingWindows, setLoadingWindows] = useState(false);
  const [savingWindow, setSavingWindow] = useState(false);
  const [windowError, setWindowError] = useState("");
  const [windowInfo, setWindowInfo] = useState("");
  const [adminId, setAdminId] = useState("");
  const [unavailableStart, setUnavailableStart] = useState("");
  const [unavailableEnd, setUnavailableEnd] = useState("");
  const [unavailableReason, setUnavailableReason] = useState("");
  const [selectedRepIds, setSelectedRepIds] = useState<string[]>([]);
  const [repSlotsByRep, setRepSlotsByRep] = useState<Record<string, RepSlot[]>>({});
  const [windows, setWindows] = useState<AdminUnavailabilityWindow[]>([]);
  const [repWindows, setRepWindows] = useState<RepAvailabilityWindow[]>([]);
  const [editingWindowId, setEditingWindowId] = useState("");
  const [editStart, setEditStart] = useState("");
  const [editEnd, setEditEnd] = useState("");
  const [editReason, setEditReason] = useState("");
  const [editSelectedRepIds, setEditSelectedRepIds] = useState<string[]>([]);
  const [editRepSlotsByRep, setEditRepSlotsByRep] = useState<Record<string, RepSlot[]>>({});

  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);

  function defaultSlot(start: string, end: string): RepSlot {
    return { start: start || "", end: end || "" };
  }

  useEffect(() => {
    setLoadingReps(true);
    fetch(`${API_BASE}/api/users`, { headers: authHeaders(token) })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((rows: Rep[]) => {
        const salesReps = (rows || []).filter((u) => u.role === "sales_rep");
        const adminUsers = (rows || []).filter((u) => u.role === "admin");
        setReps(salesReps);
        setAdmins(adminUsers);
        if (!adminId && adminUsers.length) {
          setAdminId(adminUsers[0].id);
        }
      })
      .catch((err: unknown) => setWindowError(err instanceof Error ? err.message : "Failed to load users"))
      .finally(() => setLoadingReps(false));
  }, [token, adminId]);

  useEffect(() => {
    if (!adminId) return;
    loadAllWindows(adminId);
  }, [adminId]);

  async function loadAdminWindows(targetAdminId: string) {
    setLoadingWindows(true);
    setWindowError("");
    try {
      const params = new URLSearchParams({ admin_id: targetAdminId });
      const res = await fetch(`${API_BASE}/api/users/admin-unavailability?${params.toString()}`, {
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as AdminUnavailabilityWindow[];
      setWindows(data || []);
    } catch (err: unknown) {
      setWindowError(err instanceof Error ? err.message : "Failed to load admin unavailable windows");
    } finally {
      setLoadingWindows(false);
    }
  }

  async function loadRepWindows() {
    const res = await fetch(`${API_BASE}/api/users/rep-availability`, {
      headers: authHeaders(token),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as RepAvailabilityWindow[];
    setRepWindows(data || []);
  }

  async function loadAllWindows(targetAdminId: string) {
    await Promise.all([loadAdminWindows(targetAdminId), loadRepWindows()]);
  }

  function toggleSelectedRep(repId: string) {
    setSelectedRepIds((prev) => {
      if (prev.includes(repId)) {
        return prev.filter((id) => id !== repId);
      }
      return [...prev, repId];
    });
    setRepSlotsByRep((prev) => {
      if (prev[repId]) return prev;
      return {
        ...prev,
        [repId]: [defaultSlot(unavailableStart, unavailableEnd)],
      };
    });
  }

  function addRepSlot(repId: string) {
    setRepSlotsByRep((prev) => {
      const existing = prev[repId] || [defaultSlot(unavailableStart, unavailableEnd)];
      return {
        ...prev,
        [repId]: [...existing, defaultSlot(unavailableStart, unavailableEnd)],
      };
    });
  }

  function removeRepSlot(repId: string, slotIndex: number) {
    setRepSlotsByRep((prev) => {
      const existing = prev[repId] || [];
      if (existing.length <= 1) {
        const nextState = { ...prev };
        delete nextState[repId];
        setSelectedRepIds((ids) => ids.filter((id) => id !== repId));
        return nextState;
      }
      const next = existing.filter((_, idx) => idx !== slotIndex);
      return { ...prev, [repId]: next };
    });
  }

  function updateRepSlot(repId: string, slotIndex: number, patch: Partial<RepSlot>) {
    setRepSlotsByRep((prev) => {
      const existing = prev[repId] || [defaultSlot(unavailableStart, unavailableEnd)];
      const next = existing.map((slot, idx) => (idx === slotIndex ? { ...slot, ...patch } : slot));
      return { ...prev, [repId]: next };
    });
  }

  function addEditRepSlot(repId: string) {
    setEditRepSlotsByRep((prev) => {
      const existing = prev[repId] || [defaultSlot(editStart, editEnd)];
      return {
        ...prev,
        [repId]: [...existing, defaultSlot(editStart, editEnd)],
      };
    });
  }

  function removeEditRepSlot(repId: string, slotIndex: number) {
    setEditRepSlotsByRep((prev) => {
      const existing = prev[repId] || [];
      if (existing.length <= 1) {
        const nextState = { ...prev };
        delete nextState[repId];
        setEditSelectedRepIds((ids) => ids.filter((id) => id !== repId));
        return nextState;
      }
      const next = existing.filter((_, idx) => idx !== slotIndex);
      return { ...prev, [repId]: next };
    });
  }

  function updateEditRepSlot(repId: string, slotIndex: number, patch: Partial<RepSlot>) {
    setEditRepSlotsByRep((prev) => {
      const existing = prev[repId] || [defaultSlot(editStart, editEnd)];
      const next = existing.map((slot, idx) => (idx === slotIndex ? { ...slot, ...patch } : slot));
      return { ...prev, [repId]: next };
    });
  }

  function toggleEditSelectedRep(repId: string) {
    setEditSelectedRepIds((prev) => {
      if (prev.includes(repId)) return prev.filter((id) => id !== repId);
      return [...prev, repId];
    });
    setEditRepSlotsByRep((prev) => {
      if (prev[repId]) return prev;
      return {
        ...prev,
        [repId]: [defaultSlot(editStart, editEnd)],
      };
    });
  }

  function overlaps(aStart: string, aEnd: string, bStart: string, bEnd: string): boolean {
    const a1 = toMs(aStart);
    const a2 = toMs(aEnd);
    const b1 = toMs(bStart);
    const b2 = toMs(bEnd);
    if (!a1 || !a2 || !b1 || !b2) return false;
    return a1 < b2 && b1 < a2;
  }

  function isActiveNow(start: string | undefined, end: string | undefined): boolean {
    const s = toMs(start);
    const e = toMs(end);
    if (!s || !e) return false;
    return s <= nowMs && nowMs < e;
  }

  function getRepWindowsForAdminWindow(window: AdminUnavailabilityWindow, repId: string): RepAvailabilityWindow[] {
    const token = `[admin_window:${window.id}]`;
    const tokenMatches = repWindows.filter((rw) => rw.rep_user_id === repId && (rw.reason || "").includes(token));
    if (tokenMatches.length > 0) {
      return tokenMatches.sort((a, b) => toMs(a.start_at) - toMs(b.start_at));
    }
    const legacyMatches = repWindows.filter(
      (rw) =>
        rw.rep_user_id === repId &&
        overlaps(rw.start_at, rw.end_at, window.start_at, window.end_at) &&
        (rw.reason || "").toLowerCase().includes("linked to admin unavailability"),
    );
    return legacyMatches.sort((a, b) => toMs(a.start_at) - toMs(b.start_at));
  }

  function startEditWindow(window: AdminUnavailabilityWindow) {
    const selected = window.available_rep_ids || [];
    const nextSlotsByRep: Record<string, RepSlot[]> = {};
    selected.forEach((repId) => {
      const linked = getRepWindowsForAdminWindow(window, repId);
      nextSlotsByRep[repId] = linked.length
        ? linked.map((slot) => ({ id: slot.id, start: toLocalInputValue(slot.start_at), end: toLocalInputValue(slot.end_at) }))
        : [defaultSlot(toLocalInputValue(window.start_at), toLocalInputValue(window.end_at))];
    });
    setEditingWindowId(window.id);
    setEditStart(toLocalInputValue(window.start_at));
    setEditEnd(toLocalInputValue(window.end_at));
    setEditReason(window.reason || "");
    setEditSelectedRepIds(selected);
    setEditRepSlotsByRep(nextSlotsByRep);
    setWindowError("");
    setWindowInfo("");
  }

  async function saveWindowUpdate(window: AdminUnavailabilityWindow) {
    setWindowError("");
    setWindowInfo("");

    const startMs = toMs(editStart);
    const endMs = toMs(editEnd);
    if (!startMs || !endMs || endMs <= startMs) {
      setWindowError("End must be after start.");
      return;
    }

    setSavingWindow(true);
    try {
      const adminRes = await fetch(`${API_BASE}/api/users/admin-unavailability/${window.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          start_at: new Date(editStart).toISOString(),
          end_at: new Date(editEnd).toISOString(),
          reason: editReason,
          rep_user_ids: editSelectedRepIds,
        }),
      });
      if (!adminRes.ok) {
        const err = await adminRes.json().catch(() => ({ detail: "Failed to update window" }));
        throw new Error(err.detail || "Failed to update window");
      }

      const windowToken = `[admin_window:${window.id}]`;
      const syncTasks = reps.map(async (rep) => {
        const repId = rep.id;
        const existing = getRepWindowsForAdminWindow(window, repId);

        for (const slot of existing) {
          const delRes = await fetch(`${API_BASE}/api/users/rep-availability/${slot.id}`, {
            method: "DELETE",
            headers: authHeaders(token),
          });
          if (!delRes.ok) throw new Error("Failed to sync rep slots");
        }

        if (!editSelectedRepIds.includes(repId)) return;

        const sourceSlots = editRepSlotsByRep[repId] || [defaultSlot(editStart, editEnd)];
        const validSlots = sourceSlots.filter((slot) => {
          const s = toMs(slot.start);
          const e = toMs(slot.end);
          return Boolean(s && e && e > s);
        });

        for (const slot of validSlots) {
          const createRes = await fetch(`${API_BASE}/api/users/rep-availability`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders(token) },
            body: JSON.stringify({
              rep_user_id: repId,
              start_at: new Date(slot.start).toISOString(),
              end_at: new Date(slot.end).toISOString(),
              reason: `${windowToken} Linked to admin unavailability (${new Date(editStart).toLocaleString()} - ${new Date(editEnd).toLocaleString()})`,
            }),
          });
          if (!createRes.ok) throw new Error("Failed to sync rep slots");
        }
      });

      await Promise.all(syncTasks);
      setEditingWindowId("");
      setWindowInfo("Admin slot and rep slots updated.");
      await loadAllWindows(adminId);
    } catch (err: unknown) {
      setWindowError(err instanceof Error ? err.message : "Failed to update window");
    } finally {
      setSavingWindow(false);
    }
  }

  async function createAdminWindow() {
    setWindowError("");
    setWindowInfo("");
    if (!adminId) {
      setWindowError("Select an admin.");
      return;
    }
    if (!unavailableStart || !unavailableEnd) {
      setWindowError("Select start and end date/time.");
      return;
    }
    const startMs = toMs(unavailableStart);
    const endMs = toMs(unavailableEnd);
    if (!startMs || !endMs || endMs <= startMs) {
      setWindowError("End must be after start.");
      return;
    }

    setSavingWindow(true);
    try {
      const res = await fetch(`${API_BASE}/api/users/admin-unavailability`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify({
          admin_user_id: adminId,
          start_at: new Date(unavailableStart).toISOString(),
          end_at: new Date(unavailableEnd).toISOString(),
          reason: unavailableReason,
          rep_user_ids: selectedRepIds,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to save" }));
        throw new Error(err.detail || "Failed to save");
      }
      const createdWindow = (await res.json()) as AdminUnavailabilityWindow;
      const windowToken = `[admin_window:${createdWindow.id}]`;

      // Persist per-rep availability windows tied to this rule setup.
      const repTasks = selectedRepIds.map(async (repId) => {
        const sourceSlots = repSlotsByRep[repId] || [defaultSlot(unavailableStart, unavailableEnd)];
        const validSlots = sourceSlots.filter((slot) => {
          const s = toMs(slot.start);
          const e = toMs(slot.end);
          return Boolean(s && e && e > s);
        });

        for (const slot of validSlots) {
          const createRes = await fetch(`${API_BASE}/api/users/rep-availability`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders(token) },
            body: JSON.stringify({
              rep_user_id: repId,
              start_at: new Date(slot.start).toISOString(),
              end_at: new Date(slot.end).toISOString(),
              reason: `${windowToken} Linked to admin unavailability (${new Date(unavailableStart).toLocaleString()} - ${new Date(unavailableEnd).toLocaleString()})`,
            }),
          });
          if (!createRes.ok) throw new Error("Failed to save rep availability slot");
        }
      });
      await Promise.all(repTasks);

      setUnavailableStart("");
      setUnavailableEnd("");
      setUnavailableReason("");
      setSelectedRepIds([]);
      setRepSlotsByRep({});
      setWindowInfo("Admin unavailable window saved.");
      await loadAllWindows(adminId);
    } catch (err: unknown) {
      setWindowError(err instanceof Error ? err.message : "Failed to save admin unavailable window");
    } finally {
      setSavingWindow(false);
    }
  }

  async function deleteAdminWindow(windowId: string) {
    setWindowError("");
    setWindowInfo("");
    try {
      const res = await fetch(`${API_BASE}/api/users/admin-unavailability/${windowId}`, {
        method: "DELETE",
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setWindowInfo("Unavailable window removed.");
      await loadAllWindows(adminId);
    } catch (err: unknown) {
      setWindowError(err instanceof Error ? err.message : "Failed to delete window");
    }
  }

  return (
    <div style={{ padding: "20px 24px", fontFamily: "inherit", overflow: "auto", height: "calc(100vh - 52px)", boxSizing: "border-box" }}>
      <h1 style={{ fontSize: 20, color: "#032d60", fontWeight: 700, marginBottom: 4 }}>Assignment Availability Rules</h1>
      <p style={{ marginTop: 4, marginBottom: 16, color: "#706e6b" }}>
        Configure when admins are unavailable and which reps are available to receive auto-assignment during that time.
      </p>

      <div style={{ marginBottom: 14, border: "1px solid #dddbda", borderRadius: 4, padding: 14, background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.06)" }}>
        <h2 style={{ margin: "0 0 10px", fontSize: 13, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#3e3e3c" }}>
          Admin Unavailability + Available Reps
        </h2>

        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", marginBottom: 10 }}>
          <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
            Admin
            <select
              value={adminId}
              onChange={(e) => setAdminId(e.target.value)}
              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
              disabled={loadingReps}
            >
              <option value="">Select admin...</option>
              {admins.map((admin) => (
                <option key={admin.id} value={admin.id}>
                  {admin.name} ({admin.email})
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
            Unavailable From
            <input
              type="datetime-local"
              value={unavailableStart}
              onChange={(e) => setUnavailableStart(e.target.value)}
              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
            />
          </label>

          <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c" }}>
            Unavailable Until
            <input
              type="datetime-local"
              value={unavailableEnd}
              onChange={(e) => setUnavailableEnd(e.target.value)}
              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
            />
          </label>
        </div>

        <label style={{ display: "grid", gap: 5, fontSize: 13, fontWeight: 600, color: "#3e3e3c", marginBottom: 10 }}>
          Reason (optional)
          <input
            type="text"
            value={unavailableReason}
            onChange={(e) => setUnavailableReason(e.target.value)}
            placeholder="Vacation, sick day, after-hours, etc."
            style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "8px 10px", background: "#fff", fontSize: 13 }}
          />
        </label>

        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#3e3e3c", marginBottom: 6 }}>
            Reps Available In This Window
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {reps.map((rep) => {
              const checked = selectedRepIds.includes(rep.id);
              const slots = repSlotsByRep[rep.id] || [defaultSlot(unavailableStart, unavailableEnd)];
              return (
                <div key={rep.id} style={{ border: checked ? "1px solid #0176d3" : "1px solid #d9d9d9", borderRadius: 8, padding: 10, background: checked ? "#f0f8ff" : "#fff" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, color: "#3e3e3c", marginBottom: checked ? 8 : 0 }}>
                    <input type="checkbox" checked={checked} onChange={() => toggleSelectedRep(rep.id)} />
                    {rep.name}
                  </label>
                  {checked ? (
                    <div style={{ display: "grid", gap: 8 }}>
                      {slots.map((slot, slotIndex) => (
                        <div key={`${rep.id}-slot-${slotIndex}`} style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", alignItems: "end" }}>
                          <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                            Availability Start
                            <input
                              type="datetime-local"
                              value={slot.start}
                              onChange={(e) => updateRepSlot(rep.id, slotIndex, { start: e.target.value })}
                              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                            />
                          </label>
                          <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                            Availability End
                            <input
                              type="datetime-local"
                              value={slot.end}
                              onChange={(e) => updateRepSlot(rep.id, slotIndex, { end: e.target.value })}
                              style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                            />
                          </label>
                          <div>
                            <button
                              type="button"
                              onClick={() => removeRepSlot(rep.id, slotIndex)}
                              style={{ border: "1px solid #f9b9b5", background: "#fff", color: "#ba0517", borderRadius: 4, padding: "6px 10px", fontSize: 12 }}
                            >
                              {slots.length <= 1 ? "Remove Rep" : "Remove Slot"}
                            </button>
                          </div>
                        </div>
                      ))}
                      <div>
                        <button
                          type="button"
                          onClick={() => addRepSlot(rep.id)}
                          style={{ border: "1px solid #91c8f6", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "6px 10px", fontSize: 12, fontWeight: 600 }}
                        >
                          + Add Slot
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <button
            type="button"
            onClick={createAdminWindow}
            disabled={savingWindow || !adminId}
            style={{ border: "none", background: savingWindow ? "#5a9fd4" : "#0176d3", color: "#fff", borderRadius: 4, padding: "8px 14px", fontWeight: 600 }}
          >
            {savingWindow ? "Saving..." : "Mark Admin Unavailable"}
          </button>
          <button
            type="button"
            onClick={() => loadAllWindows(adminId)}
            disabled={!adminId || loadingWindows}
            style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "8px 14px", color: "#3e3e3c" }}
          >
            Refresh
          </button>
        </div>

        {windowError ? <p style={{ marginBottom: 8, color: "#ba0517", fontSize: 13 }}>{windowError}</p> : null}
        {windowInfo ? <p style={{ marginBottom: 8, color: "#2e844a", fontSize: 13 }}>{windowInfo}</p> : null}

        <div style={{ display: "grid", gap: 12 }}>
          {!loadingWindows && windows.length === 0 ? (
            <div style={{ border: "1px solid #dddbda", borderRadius: 4, padding: 12, background: "#fff" }}>
              No unavailable windows set.
            </div>
          ) : null}

          {windows.map((w) => {
            const isEditing = editingWindowId === w.id;
            const selectedIds = isEditing ? editSelectedRepIds : (w.available_rep_ids || []);
            return (
              <div key={w.id} style={{ border: "1px solid #dddbda", borderRadius: 8, background: "#fff", padding: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                  <strong style={{ color: "#032d60" }}>Admin Slot</strong>
                  <div style={{ display: "flex", gap: 8 }}>
                    {!isEditing ? (
                      <button
                        type="button"
                        onClick={() => startEditWindow(w)}
                        style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "5px 10px", fontSize: 12 }}
                      >
                        Edit
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => saveWindowUpdate(w)}
                          disabled={savingWindow}
                          style={{ border: "none", background: "#0176d3", color: "#fff", borderRadius: 4, padding: "5px 10px", fontSize: 12 }}
                        >
                          {savingWindow ? "Saving..." : "Update"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingWindowId("")}
                          style={{ border: "1px solid #dddbda", background: "#fff", borderRadius: 4, padding: "5px 10px", fontSize: 12 }}
                        >
                          Cancel
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      onClick={() => deleteAdminWindow(w.id)}
                      style={{ border: "1px solid #f9b9b5", background: "#fff", color: "#ba0517", borderRadius: 4, padding: "5px 10px", fontSize: 12 }}
                    >
                      Delete
                    </button>
                  </div>
                </div>

                {!isEditing ? (
                  <div style={{ display: "grid", gap: 6, marginBottom: 10, fontSize: 13 }}>
                    <div><strong>From:</strong> {prettyDate(w.start_at)}</div>
                    <div><strong>Until:</strong> {prettyDate(w.end_at)}</div>
                    <div><strong>Reason:</strong> {w.reason || ""}</div>
                  </div>
                ) : (
                  <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", marginBottom: 10 }}>
                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                      Unavailable From
                      <input
                        type="datetime-local"
                        value={editStart}
                        onChange={(e) => setEditStart(e.target.value)}
                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                      />
                    </label>
                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                      Unavailable Until
                      <input
                        type="datetime-local"
                        value={editEnd}
                        onChange={(e) => setEditEnd(e.target.value)}
                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                      />
                    </label>
                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                      Reason
                      <input
                        type="text"
                        value={editReason}
                        onChange={(e) => setEditReason(e.target.value)}
                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                      />
                    </label>
                  </div>
                )}

                <div style={{ borderTop: "1px solid #eef0f2", paddingTop: 10 }}>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 700 }}>
                    Available Reps And Their Slots
                  </div>
                  <div style={{ display: "grid", gap: 8 }}>
                    {reps.map((rep) => {
                      const selected = selectedIds.includes(rep.id);
                      const linked = getRepWindowsForAdminWindow(w, rep.id);
                      const slots = isEditing
                        ? (editRepSlotsByRep[rep.id] || [defaultSlot(editStart, editEnd)])
                        : linked.map((slot) => ({ start: toLocalInputValue(slot.start_at), end: toLocalInputValue(slot.end_at) }));
                      const adminWindowActiveNow = isActiveNow(isEditing ? editStart : toLocalInputValue(w.start_at), isEditing ? editEnd : toLocalInputValue(w.end_at));
                      const repSlotActiveNow = slots.some((slot) => isActiveNow(slot.start, slot.end));
                      const repAvailableNow = Boolean(selected && adminWindowActiveNow && repSlotActiveNow);
                      return (
                        <div key={`${w.id}-${rep.id}`} style={{ border: selected ? "1px solid #91c8f6" : "1px solid #e5e7eb", borderRadius: 6, padding: 8, background: selected ? "#f8fbff" : "#fff" }}>
                          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, color: "#334155" }}>
                            <input
                              type="checkbox"
                              checked={selected}
                              disabled={!isEditing}
                              onChange={() => toggleEditSelectedRep(rep.id)}
                            />
                            {rep.name}
                            <span
                              style={{
                                marginLeft: "auto",
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 6,
                                fontSize: 11,
                                fontWeight: 700,
                                color: repAvailableNow ? "#166534" : "#475569",
                              }}
                            >
                              <span
                                style={{
                                  width: 8,
                                  height: 8,
                                  borderRadius: 999,
                                  background: repAvailableNow ? "#22c55e" : "#94a3b8",
                                  display: "inline-block",
                                }}
                              />
                              {repAvailableNow ? "Available now" : "Not available"}
                            </span>
                          </label>
                          {selected ? (
                            isEditing ? (
                              <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                                {slots.map((slot, slotIndex) => (
                                  <div key={`${w.id}-${rep.id}-edit-slot-${slotIndex}`} style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", alignItems: "end" }}>
                                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                                      Start
                                      <input
                                        type="datetime-local"
                                        value={slot.start}
                                        onChange={(e) => updateEditRepSlot(rep.id, slotIndex, { start: e.target.value })}
                                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                                      />
                                    </label>
                                    <label style={{ display: "grid", gap: 4, fontSize: 12, color: "#475569" }}>
                                      End
                                      <input
                                        type="datetime-local"
                                        value={slot.end}
                                        onChange={(e) => updateEditRepSlot(rep.id, slotIndex, { end: e.target.value })}
                                        style={{ border: "1px solid #dddbda", borderRadius: 4, padding: "7px 10px", fontSize: 13 }}
                                      />
                                    </label>
                                    <div>
                                      <button
                                        type="button"
                                        onClick={() => removeEditRepSlot(rep.id, slotIndex)}
                                        style={{ border: "1px solid #f9b9b5", background: "#fff", color: "#ba0517", borderRadius: 4, padding: "6px 10px", fontSize: 12 }}
                                      >
                                        {slots.length <= 1 ? "Remove Rep" : "Remove Slot"}
                                      </button>
                                    </div>
                                  </div>
                                ))}
                                <div>
                                  <button
                                    type="button"
                                    onClick={() => addEditRepSlot(rep.id)}
                                    style={{ border: "1px solid #91c8f6", background: "#fff", color: "#0176d3", borderRadius: 4, padding: "6px 10px", fontSize: 12, fontWeight: 600 }}
                                  >
                                    + Add Slot
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div style={{ marginTop: 6, fontSize: 12, color: "#475569", display: "grid", gap: 4 }}>
                                {slots.length > 0
                                  ? slots.map((slot, idx) => (
                                    <div key={`${w.id}-${rep.id}-view-slot-${idx}`}>
                                      {slot.start && slot.end ? `${prettyDate(slot.start)} - ${prettyDate(slot.end)}` : "No specific rep slot"}
                                    </div>
                                  ))
                                  : "No specific rep slot"}
                              </div>
                            )
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
