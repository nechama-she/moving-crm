"""Queue customer files for a separate worker; never transfer media in the API."""
import json
import logging
import os
from uuid import uuid4

import boto3
from botocore.config import Config
from fastapi import HTTPException

from models import LeadAttachment, PublicMoveUpload

logger = logging.getLogger(__name__)


def sync_status(access_id, db):
    rows = db.query(PublicMoveUpload, LeadAttachment.file_name).join(
        LeadAttachment, LeadAttachment.id == PublicMoveUpload.attachment_id,
    ).filter(PublicMoveUpload.access_id == access_id).all()
    files = [
        {'id': row.attachment_id, 'name': name,
         'status': 'synced' if row.synced_at else row.sync_status,
         'error': row.sync_error or ''}
        for row, name in rows
    ]
    return {
        'files': files,
        'pending': sum(f['status'] != 'synced' for f in files),
        'active': sum(f['status'] in ('queued', 'syncing') for f in files),
        'synced': sum(f['status'] == 'synced' for f in files),
        'failed': sum(f['status'] == 'failed' for f in files),
    }


def queue_files(access_id, db, actor_id=None, attachment_id=None):
    queue_url = os.getenv('PUBLIC_MOVE_SYNC_QUEUE_URL', '').strip()
    if not queue_url:
        raise HTTPException(503, 'Customer file sync worker is not configured')
    query = db.query(PublicMoveUpload).filter(
        PublicMoveUpload.access_id == access_id,
        PublicMoveUpload.synced_at.is_(None),
        PublicMoveUpload.sync_status.in_(['pending', 'failed']),
    )
    if attachment_id:
        query = query.filter(PublicMoveUpload.attachment_id == attachment_id)
    rows = query.order_by(PublicMoveUpload.attachment_id).with_for_update().all()
    if not rows:
        db.commit()
        return sync_status(access_id, db)
    # A short queue call replaces all LiveSwitch/S3 transfers in the HTTP request.
    sqs = boto3.client('sqs', config=Config(connect_timeout=2, read_timeout=3, retries={'total_max_attempts': 1}))
    token = str(uuid4())
    for row in rows:
        row.sync_token = token
        row.sync_status = 'queued'
        row.sync_error = None
    try:
        # One small queue message even for hundreds of files. The worker fans it
        # out into one-file jobs, outside the HTTP request's time limit.
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps({
            'access_id': access_id, 'attachment_ids': [row.attachment_id for row in rows],
            'sync_token': token, 'actor_id': actor_id,
        }))
    except Exception:
        logger.exception('Could not queue customer files for access %s', access_id)
        for row in rows:
            row.sync_status = 'failed'
            row.sync_error = 'Could not queue this file. Please retry.'
    # Workers lock each row before reading, so cannot race this transaction.
    db.commit()
    return sync_status(access_id, db)