"""SQS worker: one customer file per invocation, with durable per-file progress."""
import json
import logging
import os
from datetime import datetime
from urllib.parse import urlparse

import httpx
import boto3
from botocore.config import Config
from fastapi import HTTPException

from database import SessionLocal
from models import LeadAttachment, LeadLiveSwitch, PublicMoveAccess, PublicMoveUpload, User

logger = logging.getLogger(__name__)


def locked_upload(db, message):
    return db.query(PublicMoveUpload).filter_by(
        attachment_id=message['attachment_id'], access_id=message['access_id'],
    ).populate_existing().with_for_update().first()


def current_job(row, message):
    return row and not row.synced_at and row.sync_token == message['sync_token'] and row.sync_status in ('queued', 'syncing')


def process_file(message, db, dead_letter=False):
    row = locked_upload(db, message)
    if not current_job(row, message):
        if not dead_letter and row and row.synced_at and row.sync_token == message['sync_token']:
            access = db.get(PublicMoveAccess, message['access_id'])
            if access:
                from routes.liveswitch import start_ready_report
                start_ready_report(access.lead_id, db)
        return
    if dead_letter:
        row.sync_status = 'failed'
        row.sync_error = 'The background worker could not finish this file. Please retry.'
        db.commit()
        return
    access = db.get(PublicMoveAccess, message['access_id'])
    if not access:
        return
    row.sync_status = 'syncing'
    db.commit()
    try:
        conversation = db.get(LeadLiveSwitch, access.lead_id)
        if message.get('conversation_id'):
            details = {'id': message['conversation_id']}
        elif conversation:
            details = json.loads(conversation.details)
        else:
            # The requesting staff user is rechecked by the existing conversation flow.
            actor = db.get(User, message.get('actor_id')) if message.get('actor_id') else None
            if not actor:
                raise ValueError('Start a LiveSwitch conversation before syncing these files.')
            from routes.liveswitch import ensure_conversation
            details = ensure_conversation(access.lead_id, actor, db)
        row = locked_upload(db, message)
        if not current_job(row, message):
            return
        attachment = db.get(LeadAttachment, row.attachment_id)
        if not attachment or attachment.lead_id != access.lead_id:
            raise ValueError('The customer file is no longer available on this job.')
        if not row.sync_upload_url:
            from routes.liveswitch import _api_post
            kind = 'images' if attachment.content_type.startswith('image/') else 'videos' if attachment.content_type.startswith('video/') else 'documents'
            name = f'{attachment.id}-{attachment.file_name}'
            result = _api_post(f'conversations/{details["id"]}/upload-urls/{kind}', [
                {'fileName': name, 'contentType': attachment.content_type},
            ])
            target = next((item for item in result.get('results', []) if item.get('fileName') == name), {})
            url = target.get('presignedUrl') or ''
            parsed = urlparse(url)
            if target.get('errorMessage') or parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.amazonaws.com'):
                raise ValueError(target.get('errorMessage') or 'LiveSwitch did not return a valid upload URL.')
            row.sync_upload_url = url
            # Keep the SAME S3 destination on retry if a PUT succeeds just before
            # a crash. Do not create a second LiveSwitch media entry in that case.
            db.commit()
            row = locked_upload(db, message)
            if not current_job(row, message):
                return
        stored = urlparse(attachment.external_url or '')
        if stored.scheme == 's3':
            obj = boto3.client('s3').get_object(Bucket=stored.netloc, Key=stored.path.lstrip('/'))
            stream = obj['Body']
            try:
                response = httpx.put(row.sync_upload_url, content=stream.iter_chunks(chunk_size=1024*1024),
                    headers={'Content-Type': attachment.content_type, 'Content-Length': str(obj['ContentLength'])}, timeout=60)
            finally:
                stream.close()
        else:
            from routes.leads import _stored_attachment_bytes
            content = _stored_attachment_bytes(attachment)
            if not content:
                raise ValueError('The saved customer file could not be read.')
            response = httpx.put(row.sync_upload_url, content=content,
                                 headers={'Content-Type': attachment.content_type}, timeout=60)
        response.raise_for_status()
        row.synced_at = datetime.utcnow()
        row.sync_status = 'synced'
        row.sync_error = None
        row.sync_upload_url = None
        db.commit()  # Persist this file now, never at the end of an entire move.
        from routes.liveswitch import start_ready_report
        start_ready_report(access.lead_id, db)
    except Exception as exc:
        db.rollback()
        row = locked_upload(db, message)
        if row and row.synced_at and row.sync_token == message['sync_token']:
            # Retry scheduling without re-uploading a file that already succeeded.
            raise
        if current_job(row, message):
            row.sync_status = 'failed'
            # Never expose presigned URL credentials through httpx exception text.
            if isinstance(exc, httpx.HTTPStatusError):
                row.sync_error = (
                    'LiveSwitch rejected the saved upload destination (HTTP 403). '
                    'It may have expired. Check the file in LiveSwitch before resetting its upload destination.'
                    if exc.response.status_code == 403 else
                    f'LiveSwitch upload failed (HTTP {exc.response.status_code}). Please retry.'
                )
            elif isinstance(exc, httpx.RequestError):
                row.sync_error = 'LiveSwitch upload timed out or was interrupted. Please retry.'
            elif isinstance(exc, HTTPException):
                row.sync_error = str(exc.detail)
            elif isinstance(exc, ValueError):
                row.sync_error = str(exc)
            else:
                row.sync_error = 'Customer file sync failed. Please retry.'
            db.commit()
        logger.warning('Customer file sync failed for %s (%s)', message['attachment_id'], type(exc).__name__)


def dispatch_files(message, db, dead_letter=False):
    jobs = []
    for attachment_id in message['attachment_ids']:
        job = {key: value for key, value in message.items() if key != 'attachment_ids'}
        job['attachment_id'] = attachment_id
        if dead_letter:
            process_file(job, db, dead_letter=True)
        else:
            row = locked_upload(db, job)
            if current_job(row, job):
                jobs.append(job)
            db.commit()
    if not jobs:
        return
    sqs = boto3.client('sqs', config=Config(connect_timeout=2, read_timeout=3, retries={'total_max_attempts': 1}))
    for offset in range(0, len(jobs), 10):
        batch = jobs[offset:offset + 10]
        result = sqs.send_message_batch(QueueUrl=os.environ['PUBLIC_MOVE_SYNC_QUEUE_URL'], Entries=[
            {'Id': str(i), 'MessageBody': json.dumps(job)} for i, job in enumerate(batch)
        ])
        if len(result.get('Successful', [])) != len(batch):
            raise RuntimeError('Some file jobs could not be queued')


def handler(event, context):
    failures = []
    for record in event.get('Records', []):
        try:
            message = json.loads(record['body'])
            dead_letter = bool(os.getenv('PUBLIC_MOVE_SYNC_DLQ_ARN')) and record.get('eventSourceARN') == os.getenv('PUBLIC_MOVE_SYNC_DLQ_ARN')
            with SessionLocal() as db:
                if 'import_recordings' in message:
                    from liveswitch_recording_import import import_recordings
                    import_recordings(message, db, dead_letter)
                elif 'check_media' in message:
                    from media_readiness_check import check_media
                    check_media(message, db, dead_letter)
                elif 'check_report' in message:
                    from customer_report_updates import check_report
                    check_report(message, db, dead_letter)
                elif 'start_report' in message:
                    saved = db.get(LeadLiveSwitch, message['lead_id'])
                    details = json.loads(saved.details or '{}') if saved else {}
                    if not dead_letter and details.get('last_spark_id') == message['start_report']:
                        from routes.liveswitch import start_ready_report
                        start_ready_report(message['lead_id'], db)
                elif 'attachment_ids' in message:
                    dispatch_files(message, db, dead_letter)
                else:
                    process_file(message, db, dead_letter)
        except Exception:
            logger.exception('Customer file sync message failed')
            failures.append({'itemIdentifier': record['messageId']})
    return {'batchItemFailures': failures}
