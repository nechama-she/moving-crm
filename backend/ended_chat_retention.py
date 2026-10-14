"""SQL visibility window for ended queue entries; no background work."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, text

from models import MessageState


def clear_existing_ended_states(connection):
    """Clear existing ended queue history once, in the caller's transaction."""
    claimed = connection.execute(text("""
        INSERT INTO app_settings (key, value, updated_at)
        VALUES ('migration:clear-ended-message-states-20261014', 'complete', CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO NOTHING RETURNING key
    """)).scalar()
    if claimed is None:
        return 0
    return connection.execute(
        MessageState.__table__.delete().where(MessageState.conversation_ended.is_(True))
    ).rowcount


def visible_message_states(now=None):
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=24)
    return or_(
        MessageState.conversation_ended.is_(False),
        and_(MessageState.conversation_ended.is_(True), MessageState.ended_at > cutoff),
    )
