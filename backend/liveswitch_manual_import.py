"""Read-only discovery for the optional staff-initiated media importer."""
from uuid import NAMESPACE_URL, uuid5
import base64
import hashlib
import json
import sys

import httpx
from fastapi import HTTPException

from models import LeadAttachment


def token_diagnostics(token):
    api = sys.modules.get('routes.liveswitch')
    cache = getattr(api, '_token_cache', {})
    result = {'diagnostic_version': 1,
        'credential_source': 'OAuth' if cache.get('value') == token else 'configured bearer or unknown',
        'token_fingerprint': hashlib.sha256(token.encode()).hexdigest()[:16],
        'requested_scopes': getattr(api, 'SCOPES', '').split(),
        'token_scopes': None, 'has_recordings': None}
    try:
        payload = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        scopes = claims.get('scope')
        if isinstance(scopes, str):
            result.update(token_scopes=scopes.split(), has_recordings='recordings' in scopes.split())
        result.update(issued_at=claims.get('iat'), expires_at=claims.get('exp'))
    except (ValueError, IndexError, TypeError):
        pass
    # Decoded claims are diagnostics only, never used to grant authorization.
    return result


def missing_recordings(lead_id, conversation_id, db, fresh_token=None, trace=None):
    from routes.liveswitch import AUDIENCE, _access_token
    token = fresh_token if fresh_token is not None else _access_token()
    try:
        response = httpx.get(f'{AUDIENCE}v1/recordings/conversation/{conversation_id}',
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}, timeout=20)
    except httpx.RequestError as exc:
        raise HTTPException(502, f'LiveSwitch request failed: {exc}') from exc
    if trace is not None:
        from liveswitch_import_login import redact
        trace.append({'stage':'recordings', 'request':{'method':'GET',
            'url':f'{AUDIENCE}v1/recordings/conversation/{conversation_id}',
            'headers':{'Authorization':'Bearer [REDACTED]','Accept':'application/json'}},
            'response':{'status':response.status_code,'body':redact(response.text, [token])}})
    if not response.is_success:
        # Preserve the provider's actual error, but do not expose request credentials.
        raise HTTPException(502, {'provider': 'LiveSwitch', 'status': response.status_code, 'body': response.text,
                                 'diagnostics': token_diagnostics(token)})
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
