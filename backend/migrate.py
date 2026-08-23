"""Database migration entry point."""

import logging

from database import engine
from models import LeadCommunicationState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")


def migrate() -> None:
    """Create the communication-state table when it is missing.

    The DynamoDB message-index migration has already completed and is
    intentionally not repeated here.
    """
    LeadCommunicationState.__table__.create(bind=engine, checkfirst=True)
    logger.info("lead_communication_states is ready")


if __name__ == "__main__":
    migrate()
