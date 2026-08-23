"""Database migration entry point."""

import logging

from sqlalchemy import text

from database import engine
from models import LeadCommunicationState, MessageState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")


def migrate() -> None:
    """Create the communication-state table when it is missing.

    The DynamoDB message-index migration has already completed and is
    intentionally not repeated here.
    """
    LeadCommunicationState.__table__.create(bind=engine, checkfirst=True)
    logger.info("lead_communication_states is ready")
    MessageState.__table__.create(bind=engine, checkfirst=True)
    # Safe for environments where the new table was created by an earlier deploy.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE message_states ADD COLUMN IF NOT EXISTS client_identifier VARCHAR(255)"))
        connection.execute(text("ALTER TABLE message_states ADD COLUMN IF NOT EXISTS company_identifier VARCHAR(255)"))
        connection.execute(text("DELETE FROM message_states WHERE client_identifier IS NULL OR company_identifier IS NULL"))
        connection.execute(text("ALTER TABLE message_states ALTER COLUMN client_identifier SET NOT NULL"))
        connection.execute(text("ALTER TABLE message_states ALTER COLUMN company_identifier SET NOT NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_states_client_identifier ON message_states (client_identifier)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_states_company_identifier ON message_states (company_identifier)"))
    logger.info("message_states is ready")


if __name__ == "__main__":
    migrate()
