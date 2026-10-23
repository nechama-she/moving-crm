"""One-time import of legacy follow-ups; subsequent syncs write tasks directly."""
from sqlalchemy import text
from libs.smartmoving.followup_tasks import UPSERT_TASK


def install(connection):
    for name, kind in [('smartmoving_followup_id', 'VARCHAR(36)'),
                       ('smartmoving_followup_type', 'INTEGER'),
                       ('smartmoving_assigned_to_id', 'VARCHAR(36)')]:
        connection.execute(text(f'ALTER TABLE tasks ADD COLUMN IF NOT EXISTS {name} {kind}'))
    connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_smartmoving_followup ON tasks(lead_id, smartmoving_followup_id)'))
    marker = connection.execute(text("""
        INSERT INTO app_settings(key, value) VALUES ('migration:smartmoving-followup-tasks-v1', 'done')
        ON CONFLICT (key) DO NOTHING RETURNING key
    """)).scalar()
    if not marker:
        return
    rows = connection.execute(text('SELECT * FROM followups')).mappings().all()
    for row in rows:
        connection.execute(text(UPSERT_TASK), dict(
            smartmoving_id=str(row['smartmoving_id']), note_id=str(row['note_id']),
            title=row['title'], due_date_time_iso=row['due_date_time'], notes=row['notes'],
            completed=bool(row['completed']), completed_at=row['completed_at_utc'],
            created_at=row['created_at'], followup_type=row['type'],
            assigned_to_id=row['assigned_to_id']))
