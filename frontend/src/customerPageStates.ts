// A customer's latest step on their customer page: the work queue's Customer Page and Customer Chat cards, and the
// notice for each new row. One row per lead, as /api/unanswered-messages/customer-page and its live events send it.
export type CustomerPageRow = {
  lead_id: string; job_id: string; state: "opened" | "verified" | "chat"; at: string; client: string; phone: string;
  job_number: string; company: string; rep: string; smartmoving_id?: string; quote_number?: string;
};

export const CUSTOMER_PAGE_EVENT = "customer_page_state_changed";

export function customerPageStateLabel(row: CustomerPageRow): string {
  return row.state === "opened" ? "Opened, not verified" : row.state === "verified" ? "Verified" : "Started the chat";
}

// The work queue card a row is on.
export function customerPageQueueTab(row: CustomerPageRow): "customer-page" | "customer-chat" {
  return row.state === "chat" ? "customer-chat" : "customer-page";
}
