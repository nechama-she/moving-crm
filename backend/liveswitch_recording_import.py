"""Copy completed LiveSwitch recordings into CRM storage in the file worker."""
import json
import logging
import os
import time
from uuid import NAMESPACE_URL, uuid4, uuid5
from urllib.parse import urlparse

import boto3
import httpx
from boto3.s3.transfer import TransferConfig
from fastapi import HTTPException

from models import LeadAttachment, LeadLiveSwitch


def queue_import(lead_id, db):
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=lead_id).with_for_update().one()
    details = json.loads(saved.details or '{}')
    state = details.get('recording_import', {})
    if state.get('status') in ('queued', 'running') and time.time() - state.get('started_at', 0) < 1200:
        return state
    queue = os.getenv('PUBLIC_MOVE_SYNC_QUEUE_URL', '').strip()
    if not queue or not os.getenv('ATTACHMENTS_BUCKET', '').strip():
        raise HTTPException(503, 'Video import storage or background worker is not configured.')
    state = {'token': str(uuid4()), 'status': 'queued', 'started_at': time.time(), 'imported': 0}
    boto3.client('sqs').send_message(QueueUrl=queue, MessageBody=json.dumps({
        'import_recordings': details['id'], 'lead_id': lead_id, 'token': state['token']}))
    details['recording_import'] = state
    saved.details = json.dumps(details)
    db.commit()
    return state


def update_state(message, db, **updates):
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=message['lead_id']).populate_existing().with_for_update().first()
    details = json.loads(saved.details or '{}') if saved else {}
    state = details.get('recording_import', {})
    if state.get('token') != message['token']:
        db.commit()
        return False
    state.update(updates)
    details['recording_import'] = state
    saved.details = json.dumps(details)
    db.commit()
    return True


def validate_media_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or not any(
        host == domain or host.endswith('.' + domain)
        for domain in ('liveswitch.com', 'amazonaws.com', 'cloudfront.net')
    ):
        raise ValueError('Unsupported recording download host.')


class MediaStream:
    """Bounded-memory reader for S3 multipart uploads, without a disk-sized buffer."""
    def __init__(self, response):
        self.chunks = response.iter_bytes(1024 * 1024)
        self.buffer = bytearray()
        self.size = 0

    def read(self, size=-1):
        if size < 0:
            raise ValueError('Unbounded recording reads are not supported.')
        while len(self.buffer) < size:
            chunk = next(self.chunks, b'')
            if not chunk:
                break
            self.size += len(chunk)
            if self.size > 5 * 1024**3:
                raise ValueError('Recording exceeds the 5 GB import limit.')
            self.buffer.extend(chunk)
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result


def copy_recording(recording, lead_id, conversation_id, db):
    recording_id = str(recording['id'])
    attachment_id = str(uuid5(NAMESPACE_URL, f'liveswitch:{lead_id}:{recording_id}'))
    # Include soft-deleted attachments: reopening the panel must not restore them.
    if db.get(LeadAttachment, attachment_id):
        return False
    if recording.get('conversationId') != conversation_id:
        raise ValueError('Recording does not belong to the requested conversation.')
    url = recording.get('publicUrl') or ''
    bucket = os.environ['ATTACHMENTS_BUCKET']
    key = f'leads/{lead_id}/jobs/lead/liveswitch/{attachment_id}/recording'
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        for _ in range(6):
            validate_media_url(url)
            with client.stream('GET', url) as response:
                if response.is_redirect:
                    from urllib.parse import urljoin
                    url = urljoin(url, response.headers['location'])
                    continue
                response.raise_for_status()
                content_type = response.headers.get('content-type', '').split(';')[0].lower()
                extension = {'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov'}.get(content_type)
                if not extension:
                    raise ValueError('LiveSwitch did not return a downloadable video.')
                stream = MediaStream(response)
                boto3.client('s3').upload_fileobj(stream, bucket, key,
                    ExtraArgs={'ContentType': content_type, 'ServerSideEncryption': 'AES256'},
                    Config=TransferConfig(multipart_threshold=8*1024**2, multipart_chunksize=8*1024**2, use_threads=False))
                if not stream.size:
                    raise ValueError('LiveSwitch returned an empty video.')
                expected = response.headers.get('content-length')
                if expected and not response.headers.get('content-encoding') and int(expected) != stream.size:
                    raise ValueError('Recording download was incomplete.')
                db.add(LeadAttachment(id=attachment_id, lead_id=lead_id,
                    file_name=f'LiveSwitch-{recording_id}{extension}', content_type=content_type,
                    file_size=stream.size, file_blob=b'', external_url=f's3://{bucket}/{key}',
                    is_external_link=True, external_source='liveswitch_s3',
                    source_external_id=f'{conversation_id}:{recording_id}'))
                db.commit()
                return True
    raise ValueError('Too many recording download redirects.')


def import_recordings(message, db, dead_letter=False):
    if not update_state(message, db, status='failed' if dead_letter else 'running',
                        error='Video import could not finish. Reopen LiveSwitch to retry.' if dead_letter else ''):
        return
    if dead_letter:
        return
    from routes.liveswitch import _access_token, AUDIENCE
    try:
        response = httpx.get(AUDIENCE + 'v1/recordings/conversation/' + message['import_recordings'],
            headers={'Authorization': 'Bearer ' + _access_token()}, timeout=45)
        if response.status_code in (401, 403):
            update_state(message, db, status='failed', error='LiveSwitch denied video access. Reconnect LiveSwitch with recordings permission.')
            return
        response.raise_for_status()
        recordings = response.json()
        if not isinstance(recordings, list):
            raise ValueError('Unexpected LiveSwitch recordings response.')
        imported = pending = failed = 0
        for recording in recordings:
            if recording.get('recordingType') == 'Uploads':
                continue
            if recording.get('recordingStatus') != 'Completed':
                pending += 1
                continue
            try:
                imported += int(copy_recording(recording, message['lead_id'], message['import_recordings'], db))
            except Exception:
                db.rollback()
                logging.getLogger(__name__).warning('Recording import failed for lead %s, recording %s',
                    message['lead_id'], recording.get('id'))
                failed += 1
            update_state(message, db, imported=imported)
        update_state(message, db, status='failed' if failed else 'complete', imported=imported, pending=pending,
            error=f'{failed} videos could not be downloaded. Reopen LiveSwitch to retry.' if failed else '')
        from realtime import publish_customer_update
        publish_customer_update(message['lead_id'])
    except Exception:
        db.rollback()
        update_state(message, db, status='failed', error='Could not check LiveSwitch videos. Reopen LiveSwitch to retry.')
        raise
