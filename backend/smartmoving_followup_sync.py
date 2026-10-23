"""Import current SmartMoving follow-ups on an explicit lead refresh."""
from sqlalchemy import text

from libs.smartmoving.client import get_followups
from libs.smartmoving.followup_tasks import UPSERT_TASK


def sync(db, lead):
    if lead.priority is None or lead.priority == 0:
        return 0
    if not lead.smartmoving_id:
        return 0
    response = get_followups(lead.smartmoving_id)
    if response.get('error'):
        raise ValueError(f"SmartMoving follow-up refresh failed: {response['error']}")
    rows = response.get('data')
    if not isinstance(rows, list):
        raise ValueError('SmartMoving follow-up refresh returned an invalid list')
    params = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('id') or not isinstance(row.get('completed'), bool):
            raise ValueError('SmartMoving follow-up refresh returned an invalid task')
        params.append({
            'smartmoving_id': lead.smartmoving_id,
            'note_id': str(row['id']),
            'followup_type': row.get('type'),
            'title': row.get('title') or 'Follow-up',
            'assigned_to_id': row.get('assignedToId'),
            'due_date_time_iso': row.get('dueDateTime'),
            'notes': row.get('notes') or '',
            'completed': row['completed'],
            'completed_at': row.get('completedAt'),
            'created_at': None,
        })
    # The shared upsert also excludes zero/unset priorities at write time.
    # A nested transaction keeps a malformed remote row from partially importing.
    with db.begin_nested():
        for values in params:
            db.execute(text(UPSERT_TASK), values)
    db.commit()
    return len(params)
