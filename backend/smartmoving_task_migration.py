"""Schema setup for new SmartMoving tasks. Never import historical follow-ups."""
from sqlalchemy import text


def install(connection):
    for name, kind in [('smartmoving_followup_id', 'VARCHAR(36)'),
                       ('smartmoving_followup_type', 'INTEGER'),
                       ('smartmoving_assigned_to_id', 'VARCHAR(36)')]:
        connection.execute(text(f'ALTER TABLE tasks ADD COLUMN IF NOT EXISTS {name} {kind}'))
    connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_smartmoving_followup ON tasks(lead_id, smartmoving_followup_id)'))
