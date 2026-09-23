"""Bounded, delayed server-side report checks; browsers never poll LiveSwitch."""
import json
import os
import time

import boto3

from models import LeadLiveSwitch
from realtime import publish_customer_update, publish_report_update


def report_check_failed(lead_id, saved, state, db):
    state['notification_error'] = 'Automatic report updates could not finish. Use Refresh move details or contact your moving team.'
    state['notification_until'] = 0
    saved.details = json.dumps(state)
    db.commit()
    publish_customer_update(lead_id)


def queue_report_check(lead_id, db):
    queue = os.getenv('PUBLIC_MOVE_SYNC_QUEUE_URL')
    if not queue:
        return
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=lead_id).populate_existing().with_for_update().first()
    state = json.loads(saved.details or '{}') if saved else {}
    report_id = state.get('last_spark_id')
    if (not report_id or state.get('report_source') == 'manual' or state.get('pending_spark_payload')
            or state.get('last_spark_status') in ('failed', 'cancelled')
            or state.get('spark_extracted_id') == report_id
            or (state.get('notification_report_id') == report_id and state.get('notification_until', 0) > time.time())):
        return
    boto3.client('sqs').send_message(QueueUrl=queue, DelaySeconds=60,
        MessageBody=json.dumps({'check_report': report_id, 'lead_id': lead_id, 'attempt': 0}))
    state.update(notification_report_id=report_id, notification_until=int(time.time()) + 7200)
    state.pop('notification_error', None)
    saved.details = json.dumps(state)
    db.commit()
    publish_report_update(lead_id)


def check_report(message, db, dead_letter=False):
    from routes.liveswitch import _api_get, apply_spark_results_to_lead
    lead_id, report_id = message['lead_id'], message['check_report']
    saved = db.get(LeadLiveSwitch, lead_id)
    state = json.loads(saved.details or '{}') if saved else {}
    if state.get('last_spark_id') != report_id or state.get('spark_extracted_id') == report_id:
        return
    if dead_letter:
        report_check_failed(lead_id, saved, state, db)
        return
    remote = _api_get(f'sparks/{report_id}')
    db.refresh(saved, with_for_update=True)
    state = json.loads(saved.details or '{}')
    if state.get('last_spark_id') != report_id:
        return
    old_status = state.get('last_spark_status')
    state['last_spark_status'] = remote.get('status', old_status)
    if remote.get('shareUrl'):
        state['last_spark_share_url'] = remote['shareUrl']
    saved.details = json.dumps(state)
    db.commit()
    if state['last_spark_status'] == 'completed' and state.get('last_spark_share_url'):
        result = apply_spark_results_to_lead(lead_id, state['last_spark_share_url'], db, expected_report_id=report_id)
        if result.get('ok'):
            return  # Applying the report publishes after commit.
    elif state['last_spark_status'] in ('failed', 'cancelled'):
        publish_customer_update(lead_id)
        return
    if old_status != state['last_spark_status']:
        publish_customer_update(lead_id)
    attempt = int(message.get('attempt', 0)) + 1
    if attempt < 120:
        boto3.client('sqs').send_message(QueueUrl=os.environ['PUBLIC_MOVE_SYNC_QUEUE_URL'], DelaySeconds=60,
            MessageBody=json.dumps({**message, 'attempt': attempt}))
    else:
        db.refresh(saved)
        state = json.loads(saved.details or '{}')
        if state.get('last_spark_id') == report_id:
            report_check_failed(lead_id, saved, state, db)
