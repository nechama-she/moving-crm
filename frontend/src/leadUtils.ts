export interface Lead {
  leadgen_id: string;
  [key: string]: unknown;
}

export const LABEL_MAP: Record<string, string> = {
  leadgen_id: "Lead Id",
  "when_is_the_move?": "Move Date",
  "are_you_moving_within_the_state_or_out_of_state?": "Move Type",
  created_time: "Created Time",
  inbox_url: "Inbox",
  phone_number: "Phone Number",
  full_name: "Full Name",
  pickup_zip: "Pickup Zip",
  delivery_zip: "Delivery Zip",
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
  if (key === "created_time") {
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
    const lower = str.toLowerCase();
    if (lower.includes("within")) return "Local";
    if (lower.includes("out_of") || lower.includes("out of"))
      return "Long Distance";
    return str;
  }
  return str;
}
