export interface Lead {
  id: string;
  leadgen_id: string;
  [key: string]: unknown;
}

export const LABEL_MAP: Record<string, string> = {
  leadgen_id: "Lead Id",
  "when_is_the_move?": "Move Date",
  "are_you_moving_within_the_state_or_out_of_state?": "Move Type",
  created_time: "SmartMoving Created Time",
  created_at: "CRM Record Created Time",
  inbox_url: "Inbox",
  phone_number: "Phone Number",
  full_name: "Full Name",
  company_name: "Company",
  pickup_zip: "Pickup",
  delivery_zip: "Delivery",
  move_size: "Move Size",
  page_id: "Page Id",
  form_id: "Form Id",
  adgroup_id: "Adgroup Id",
  ad_id: "Ad Id",
};

export function formatLabel(key: string): string {
  if (LABEL_MAP[key]) return LABEL_MAP[key];
  return key
    .replace(/_/g, " ")
    .replace(/\?/g, "")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

export function formatValue(key: string, value: unknown): string {
  if (value == null || value === "") return "";
  const str = String(value);
  if (key === "created_time" || key === "created_at") {
    const d = new Date(str);
    if (!isNaN(d.getTime())) {
      return d.toLocaleString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  }
  if (key === "are_you_moving_within_the_state_or_out_of_state?") {
    const lower = str.trim().toLowerCase().replace(/[_-]/g, " ");
    if (["local", "intrastate", "in state", "within state", "within the state"].includes(lower)) return "Local";
    if (["long distance", "interstate", "out of state"].includes(lower)) return "Long Distance";
    return str;
  }
  return str;
}

export function displayPhone(value: string): string {
  const digits = String(value || "").replace(/\D/g, "");
  const local = digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
  return local.length === 10 ? `(${local.slice(0, 3)}) ${local.slice(3, 6)}-${local.slice(6)}` : value;
}

// Lead priority meanings, shared by the lead page and the follow-up filters.
export const PRIORITY_LABELS: Record<string, string> = {
  "0": "New lead - not yet contacted",
  "1": "Estimate sent - likely to book",
  "2": "Estimate sent - unlikely to book",
  "3": "Contacted - estimate not yet sent",
  "4": "Online estimate - no calls",
  "5": "Home for sale - awaiting contract",
  "6": "Unqualified lead",
};
