"""Pending schema changes for the existing production database.

Install first-contact tracking and clear the old backfill once.
"""
import logging

from sqlalchemy import text

from database import engine

logger = logging.getLogger("migrate")


def migrate() -> None:
    with engine.begin() as connection:
        from first_contact_state import install as install_first_contact
        install_first_contact(connection)
        # Clear the incorrectly backfilled queue once. The marker and delete
        # share this transaction, so a failed deployment transaction can retry.
        clear_first_contact = connection.execute(text("""
            INSERT INTO app_settings(key, value)
            VALUES ('cleanup:first-contact-backfill-v1', 'cleared')
            ON CONFLICT (key) DO NOTHING RETURNING key
        """)).scalar()
        if clear_first_contact:
            cleared = connection.execute(text("DELETE FROM first_contact_states")).rowcount
            logger.info("Cleared %s first-contact state rows", cleared)
    logger.info("First-contact state setup complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
