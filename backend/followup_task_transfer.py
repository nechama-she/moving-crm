"""One-time copy of Eli Jones's imported SmartMoving follow-up tasks from dev to prod.

Dev already imported them from SmartMoving (2026-10-28). This never calls SmartMoving:
- dev deploy: freezes the open tasks into a private S3 snapshot (the settings-transfer bucket);
- prod deploy: reads that snapshot once and upserts the tasks, matching leads by SmartMoving id
  because CRM lead ids differ between environments.
"""
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger("followup_task_transfer")

RELEASE = 'eli-jones-followups-2026-10-28'
SNAPSHOT_KEY = 'releases/' + RELEASE + '.json'
DEV_IMPORT_MARKER = 'migration:smartmoving-open-followups:eli-jones:2026-10-28'
DEV_REPORT_PREFIX = 'report:smartmoving-followups-open:eli-jones:2026-10-28:lead:'
PROD_MARKER = 'migration:followup-transfer:' + RELEASE
REP_NAME = 'Eli Jones'

# Open tasks the dev import created: the reported leads, still open, assigned to the rep in SmartMoving.
EXPORT_TASKS = """
SELECT l.smartmoving_id, t.smartmoving_followup_id, t.smartmoving_followup_type, t.title,
       t.due_at, t.notes, t.smartmoving_assigned_to_id
FROM tasks t JOIN leads l ON l.id = t.lead_id
WHERE l.id IN (SELECT substr(key, :prefix_length + 1) FROM app_settings WHERE key LIKE :prefix_like AND value <> '[]')
  AND t.smartmoving_followup_id IS NOT NULL
  AND t.status <> 'done'
  AND lower(t.smartmoving_assigned_to_id) = :rep_sm_id
ORDER BY l.smartmoving_id, t.smartmoving_followup_id
"""


def checksum(tasks):
    return hashlib.sha256(json.dumps(tasks, sort_keys=True).encode('utf-8')).hexdigest()


def export_tasks(connection):
    if connection.execute(text('SELECT value FROM app_settings WHERE key = :key'), {'key': DEV_IMPORT_MARKER}).scalar() != 'complete':
        raise RuntimeError('The dev follow-up import has not completed; nothing to publish')
    rep_sm_id = connection.execute(text('SELECT lower(trim(smartmoving_rep_id)) FROM users WHERE name ILIKE :name'),
                                   {'name': REP_NAME}).scalar()
    if not rep_sm_id:
        raise RuntimeError(f'No SmartMoving id for {REP_NAME}')
    rows = connection.execute(text(EXPORT_TASKS), {
        'prefix_length': len(DEV_REPORT_PREFIX), 'prefix_like': DEV_REPORT_PREFIX + '%', 'rep_sm_id': rep_sm_id,
    }).mappings()
    return [{
        'smartmoving_id': row['smartmoving_id'],
        'followup_id': row['smartmoving_followup_id'],
        'followup_type': row['smartmoving_followup_type'],
        'title': row['title'],
        'due_at': row['due_at'].isoformat() if row['due_at'] else None,
        'notes': row['notes'] or '',
        'assigned_to_id': row['smartmoving_assigned_to_id'],
    } for row in rows]


def decode_snapshot(body):
    snapshot = json.loads(body)
    if snapshot.get('release') != RELEASE or checksum(snapshot['tasks']) != snapshot.get('sha256'):
        raise ValueError('Follow-up snapshot does not match this release or its checksum')
    return snapshot


def apply_tasks(connection, tasks, upsert_sql):
    """Upsert into prod once. Returns (applied, missing SmartMoving ids)."""
    if connection.execute(text('SELECT 1 FROM app_settings WHERE key = :key'), {'key': PROD_MARKER}).scalar():
        return 0, []
    smartmoving_ids = sorted({task['smartmoving_id'] for task in tasks})
    found = {value for (value,) in connection.execute(
        text('SELECT smartmoving_id FROM leads WHERE smartmoving_id = ANY(:ids)'), {'ids': smartmoving_ids})}
    applied = 0
    for task in tasks:
        if task['smartmoving_id'] not in found:
            continue
        # Same statement and task id scheme as the SmartMoving refresh, so a later refresh updates these rows.
        connection.execute(text(upsert_sql), {
            'smartmoving_id': task['smartmoving_id'], 'note_id': task['followup_id'],
            'followup_type': task['followup_type'], 'title': task['title'],
            'assigned_to_id': task['assigned_to_id'], 'due_date_time_iso': task['due_at'],
            'notes': task['notes'], 'completed': False, 'completed_at': None, 'created_at': None,
        })
        applied += 1
    connection.execute(text('INSERT INTO app_settings (key, value) VALUES (:key, :value)'), {
        'key': PROD_MARKER, 'value': json.dumps({'applied': applied, 'missing_leads': len(smartmoving_ids) - len(found)}),
    })
    return applied, [value for value in smartmoving_ids if value not in found]


def run(environment, engine, s3):
    bucket = 'moving-crm-settings-dev-' + os.environ['SETTINGS_SOURCE_ACCOUNT_ID']
    if environment == 'dev':
        from botocore.exceptions import ClientError
        with engine.connect() as connection:
            tasks = export_tasks(connection)
        body = json.dumps({'release': RELEASE, 'tasks': tasks, 'sha256': checksum(tasks)}).encode('utf-8')
        try:
            s3.put_object(Bucket=bucket, Key=SNAPSHOT_KEY, Body=body, ContentType='application/json',
                          ServerSideEncryption='AES256', IfNoneMatch='*')
            logger.info('Published follow-up snapshot %s: %s open tasks', RELEASE, len(tasks))
        except ClientError as error:
            if error.response['Error']['Code'] != 'PreconditionFailed':
                raise
            # Frozen on first publish, even if dev tasks change afterwards.
            logger.info('Follow-up snapshot %s already published', RELEASE)
    elif environment == 'prod':
        snapshot = decode_snapshot(s3.get_object(Bucket=bucket, Key=SNAPSHOT_KEY)['Body'].read())
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from libs.smartmoving.followup_tasks import UPSERT_TASK
        with engine.begin() as connection:
            applied, missing = apply_tasks(connection, snapshot['tasks'], UPSERT_TASK)
        logger.info('Follow-up transfer %s: %s tasks applied, %s leads not found in prod%s', RELEASE, applied,
                    len(missing), (': ' + ', '.join(missing)) if missing else '')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    env = os.environ.get('ENVIRONMENT', '')
    if env not in ('dev', 'prod'):
        logger.info('No follow-up transfer for %s', env or 'this environment')
        sys.exit(0)
    try:
        import boto3
        from database import engine
        run(env, engine, boto3.client('s3'))
    except Exception:
        # Never block a deployment; the marker is only written on success, so the next deploy retries.
        logger.exception('Follow-up transfer failed; it will retry on the next deploy')
