"""Store SmartMoving follow-ups as CRM tasks, preserving the remote identity."""

UPSERT_TASK = """
INSERT INTO tasks (id, lead_id, title, due_date, due_at, scheduled_start,
                   status, task_type, notes, completed_at, completion_reason,
                   smartmoving_followup_id, smartmoving_followup_type,
                   smartmoving_assigned_to_id, created_at, updated_at)
SELECT CAST(CAST(md5(l.id || ':' || :note_id) AS uuid) AS text), l.id,
       LEFT(COALESCE(:title, ''), 500),
       CAST(CAST(:due_date_time_iso AS timestamptz) AT TIME ZONE COALESCE(c.timezone, 'America/New_York') AS date)::text,
       CAST(:due_date_time_iso AS timestamptz), CAST(:due_date_time_iso AS timestamptz),
       CASE WHEN :completed THEN 'done' ELSE 'open' END, 'other', COALESCE(:notes, ''),
       CASE WHEN :completed THEN CAST(:completed_at AS timestamptz) ELSE NULL END,
       CASE WHEN :completed THEN 'SmartMoving' ELSE NULL END,
       :note_id, :followup_type, :assigned_to_id, COALESCE(CAST(:created_at AS timestamptz), now()), now()
FROM leads l LEFT JOIN companies c ON c.id = l.company_id
WHERE l.smartmoving_id = :smartmoving_id
  AND l.priority IS NOT NULL AND l.priority <> 0
ON CONFLICT (lead_id, smartmoving_followup_id) DO UPDATE SET
    title = EXCLUDED.title, due_date = EXCLUDED.due_date, due_at = EXCLUDED.due_at,
    scheduled_start = EXCLUDED.scheduled_start, status = EXCLUDED.status,
    notes = EXCLUDED.notes,
    completed_at = CASE WHEN EXCLUDED.status = 'done' THEN COALESCE(EXCLUDED.completed_at, tasks.completed_at) ELSE NULL END,
    completion_reason = EXCLUDED.completion_reason,
    smartmoving_followup_type = EXCLUDED.smartmoving_followup_type,
    smartmoving_assigned_to_id = EXCLUDED.smartmoving_assigned_to_id, updated_at = now()
"""
