"""Pending schema changes for the existing production database.

Remove retired queue triggers and apply message-state changes.
"""
import logging

from sqlalchemy import text

from database import engine

logger = logging.getLogger("migrate")


def migrate() -> None:
    with engine.begin() as connection:
        from first_contact_state import install as install_first_contact
        install_first_contact(connection)
        # Stop invalidations from the retired projection worker. Keep existing
        # projection tables untouched; no message or lead data is removed here.
        for table_name, trigger_name in (
            ("leads", "work_queue_lead_changed"),
            ("companies", "work_queue_directory_changed"),
            ("users", "work_queue_directory_changed"),
            ("work_queue_dirty", "work_queue_notify"),
            ("work_queue_activity", "work_queue_notify"),
            ("work_queue_checkpoints", "work_queue_recovered"),
        ):
            if connection.execute(text("SELECT to_regclass(:table_name)"), {"table_name": table_name}).scalar():
                connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}"))
        connection.execute(text("ALTER TABLE message_states ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ"))
        from ended_chat_retention import clear_existing_ended_states
        removed = clear_existing_ended_states(connection)
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_states_status_ended ON message_states (conversation_ended, ended_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_states_status_order ON message_states (conversation_ended, occurred_at DESC, channel ASC, message_id ASC)"))
        connection.execute(text("DROP TRIGGER IF EXISTS work_queue_ended_changed ON message_states"))
    logger.info("Message-state expiration column and indexes are ready; removed %s existing ended entries", removed)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
