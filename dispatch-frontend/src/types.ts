export interface Job {
  id: string;
  company_id: string;
  company_name: string;
  client_name: string;
  move_date: string;       // YYYY-MM-DD
  start_time: string;      // HH:MM or ""
  end_time: string;        // HH:MM or ""
  origin_address: string;
  destination_address: string;
  status: "scheduled" | "in_progress" | "completed" | "cancelled";
  notes: string;
  created_at: string;
}

export interface Company {
  id: string;
  name: string;
  timezone: string;
}

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
  company_ids: string[];
}
