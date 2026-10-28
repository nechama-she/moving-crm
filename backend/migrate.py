"""Pending schema changes for the existing production database.

Install timed follow-up tasks and first-contact tracking.
"""
import logging

from sqlalchemy import text

from database import engine

logger = logging.getLogger("migrate")


def migrate() -> None:
    with engine.begin() as connection:
        from models import InventoryCatalogSet, EstimateSignature, CompanyDocument
        CompanyDocument.__table__.create(connection, checkfirst=True)
        from company_documents import seed_documents
        seed_documents(connection)
        EstimateSignature.__table__.create(connection, checkfirst=True)
        connection.execute(text('ALTER TABLE estimate_signatures ADD COLUMN IF NOT EXISTS report_id TEXT'))
        InventoryCatalogSet.__table__.create(connection, checkfirst=True)
        connection.execute(text('ALTER TABLE inventory_edit_items ADD COLUMN IF NOT EXISTS set_id VARCHAR(36)'))
        connection.execute(text('ALTER TABLE inventory_edit_items ADD COLUMN IF NOT EXISTS set_name VARCHAR(200)'))
        from followup_tasks import install as install_followup_tasks
        install_followup_tasks(connection)
        from smartmoving_task_migration import install as install_smartmoving_tasks
        install_smartmoving_tasks(connection)
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
    logger.info("Follow-up task and first-contact state setup complete")
    # A failed import must not block the deployment; it resumes on the next deploy.
    try:
        from sm_followups_due import run as import_open_followups
        import_open_followups(engine)
    except Exception:
        logger.exception("SmartMoving open follow-up import failed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
