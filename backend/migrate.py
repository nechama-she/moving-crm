"""Pending schema changes for the existing production database.

The production baseline is already installed. Completed migrations are retained
in Git history rather than replayed on each deployment.
"""
import logging

from sqlalchemy import text

from database import engine

logger = logging.getLogger("migrate")


def migrate() -> None:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE message_states ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ"))
        connection.execute(text("UPDATE message_states SET ended_at = CURRENT_TIMESTAMP WHERE conversation_ended IS TRUE AND ended_at IS NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_states_status_ended ON message_states (conversation_ended, ended_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_states_status_order ON message_states (conversation_ended, occurred_at DESC, channel ASC, message_id ASC)"))
        connection.execute(text("DROP TRIGGER IF EXISTS work_queue_ended_changed ON message_states"))
    logger.info("Message-state expiration column and indexes are ready")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
