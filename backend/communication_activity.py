"""Persist lead communication activity and notify connected admin browsers."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import Lead, LeadCommunicationState
from realtime import publish_realtime_event


def record_outbound_message(db: Session, lead_id: str, channel: str) -> None:
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if lead is None:
        raise ValueError("Lead not found")

    occurred_at = datetime.now(timezone.utc)
    state = db.query(LeadCommunicationState).filter(LeadCommunicationState.lead_id == lead_id).first()
    if state is None:
        state = LeadCommunicationState(lead_id=lead_id)
        db.add(state)
    state.latest_outbound_message_at = occurred_at
    state.latest_message_channel = channel
    db.commit()

    publish_realtime_event({
        "type": "communication_updated",
        "lead_id": lead_id,
        "channel": channel,
        "direction": "outbound",
        "occurred_at": occurred_at.isoformat(),
    })
