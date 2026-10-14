"""Reuse a conversation until it has been used for a report."""
import json

from models import Lead, LeadLiveSwitch, PublicMoveUpload


def conversation_has_report(state):
    conversation_id = state.get('id')
    reports = [state, *state.get('spark_history', [])]
    return bool(conversation_id and any(
        report.get('last_spark_id') and
        (report.get('report_conversation') or {}).get('id', conversation_id) == conversation_id
        for report in reports
    ))


def prepare_upload_conversation(access, db):
    from routes.liveswitch import ensure_lead_conversation
    lead = db.query(Lead).filter_by(id=access.lead_id).with_for_update().one()
    saved = db.get(LeadLiveSwitch, lead.id)
    state = json.loads(saved.details or '{}') if saved else {}
    # An in-progress run already owns its conversation and upload queue.
    if state.get('pending_spark_payload'):
        return {key: state.get(key, '') for key in
                ('id', 'name', 'hostJoinUrl', 'participantJoinUrl', 'conversationUrl', 'embeddedConversationUrl')}
    fresh = conversation_has_report(state)
    conversation = ensure_lead_conversation(lead, db, fresh=fresh)
    if fresh:
        state.update(conversation)
        saved.details = json.dumps(state)
        for row in db.query(PublicMoveUpload).filter_by(access_id=access.id).all():
            row.synced_at = None
            row.sync_status = 'pending'
            row.sync_token = row.sync_upload_url = row.sync_error = None
        db.commit()
    return conversation
