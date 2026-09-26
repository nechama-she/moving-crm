"""Read-only discovery for the optional staff-initiated media importer."""
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import HTTPException

from models import LeadAttachment


def missing_recordings(lead_id, conversation_id, db):
    from routes.liveswitch import AUDIENCE, _access_token
    try:
        response = httpx.get(f'{AUDIENCE}v1/recordings/conversation/{conversation_id}',
            headers={'Authorization': 'Bearer ' + _access_token(), 'Accept': 'application/json'}, timeout=20)
    except httpx.RequestError as exc:
        raise HTTPException(502, f'LiveSwitch request failed: {exc}') from exc
    if not response.is_success:
        # Preserve the provider's actual error, but do not expose request credentials.
        raise HTTPException(502, {'provider': 'LiveSwitch', 'status': response.status_code, 'body': response.text})
    try:
        recordings = response.json()
        if not isinstance(recordings, list):
            raise ValueError('Expected a list')
    except ValueError as exc:
        raise HTTPException(502, {'provider': 'LiveSwitch', 'status': response.status_code, 'body': response.text}) from exc
    existing = db.query(LeadAttachment).filter_by(lead_id=lead_id).all()
    ids = {row.id for row in existing}
    source_ids = {row.source_external_id for row in existing if row.source_external_id}
    result = []
    for recording in recordings:
        recording_id = str(recording.get('id') or '')
        if not recording_id or recording.get('conversationId') != conversation_id:
            continue
        attachment_id = str(uuid5(NAMESPACE_URL, f'liveswitch:{lead_id}:{recording_id}'))
        if attachment_id in ids or f'{conversation_id}:{recording_id}' in source_ids:
            continue
        ids.add(attachment_id)
        result.append({'id': recording_id, 'request_id': attachment_id,
            'name': f'LiveSwitch-{recording_id}.mp4', 'url': recording.get('publicUrl') or '',
            'status': recording.get('recordingStatus') or 'Unknown'})
    return {'files': result}
