"""Temporary, one-shot LiveSwitch recordings diagnostic after report uploads."""
import json
from datetime import datetime

import httpx

from models import LeadLiveSwitch


def safe_response(value):
    # Media URLs may grant access without authentication; never publish them.
    if isinstance(value, dict):
        return {key: ('[redacted]' if any(part in key.lower() for part in
                ('url', 'token', 'secret', 'authorization')) else safe_response(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [safe_response(item) for item in value]
    if isinstance(value, str) and ('https://' in value or 'http://' in value):
        return '[URL-containing text redacted]'
    return value


def check_media(message, db, dead_letter=False):
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=message['lead_id']).populate_existing().with_for_update().first()
    state = json.loads(saved.details or '{}') if saved else {}
    check = state.get('media_readiness_check', {})
    if state.get('id') != message['check_media'] or check.get('status') != 'scheduled':
        return
    # Claim before making the request: duplicate SQS deliveries never repeat it.
    check.update(status='unavailable' if dead_letter else 'checking', checked_at=datetime.utcnow().isoformat() + 'Z')
    state['media_readiness_check'] = check
    saved.details = json.dumps(state)
    db.commit()
    if not dead_letter:
        from routes.liveswitch import _access_token, AUDIENCE
        try:
            response = httpx.get(AUDIENCE + 'v1/recordings/conversation/' + message['check_media'],
                headers={'Authorization': 'Bearer ' + _access_token(), 'Accept': 'application/json'}, timeout=45)
            check.update(status='complete', http_status=response.status_code)
            try:
                check['response'] = safe_response(response.json())
            except ValueError:
                check['response'] = 'LiveSwitch returned a non-JSON response.'
        except Exception as exc:
            check.update(status='unavailable', error='Could not retrieve recordings (' + type(exc).__name__ + '). No automatic retry.')
    db.refresh(saved, with_for_update=True)
    state = json.loads(saved.details or '{}')
    if state.get('id') != message['check_media']:
        return
    state['media_readiness_check'] = check
    saved.details = json.dumps(state)
    db.commit()
    from realtime import publish_customer_update
    publish_customer_update(message['lead_id'])
