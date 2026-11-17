// A Customer Activity event, as /api/customer-activity and its live notice send it.
// label: the kind's wording, from the database.
export type ActivityRow = {
  id: string; kind_id: number; label: string;
  spot: number | null; spots: number; lead_id: string; client: string; job_id: string; job_number: string;
  company: string; actor: string; by_rep: boolean; at: string;
};

export function activityLabel(row: ActivityRow): string {
  return row.spot ? `${row.label} (${row.spot} of ${row.spots})` : row.label;
}

// Who did it, and whether it was the rep.
export function activityActor(row: ActivityRow): string {
  return row.actor ? `${row.actor}${row.by_rep ? " (rep)" : ""}` : row.by_rep ? "Rep" : "";
}
