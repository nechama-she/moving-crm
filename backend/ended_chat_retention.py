"""SQL visibility window for ended queue entries; no background work."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_

from models import MessageState


def visible_message_states(now=None):
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=24)
    return or_(
        MessageState.conversation_ended.is_(False),
        and_(MessageState.conversation_ended.is_(True), MessageState.ended_at > cutoff),
    )
