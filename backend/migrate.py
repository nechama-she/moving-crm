"""Database migration entry point."""

import logging

from sqlalchemy import text

from database import SessionLocal, engine
from models import Company, LeadDuplicationRule, MessageState, MissedCallState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")


def migrate() -> None:
    """Create the communication-state table when it is missing.

    The DynamoDB message-index migration has already completed and is
    intentionally not repeated here.
    """
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS lead_communication_states"))
    logger.info("obsolete lead_communication_states table removed")
    MessageState.__table__.create(bind=engine, checkfirst=True)
    MissedCallState.__table__.create(bind=engine, checkfirst=True)
    logger.info("missed_call_states is ready")
    LeadDuplicationRule.__table__.create(bind=engine, checkfirst=True)
    logger.info("lead_duplication_rules is ready")
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

    # One-time data migration from the former code-based duplication routes.
    # Runtime duplication reads only the database and has no fallback values.
    initial_rules = (
        ("Gorilla Haulers", "Facebook-Gorilla-HHG-Nationwide", "Top Tier Van Lines", "Facebook-TTVL-HHG-Nationwide", 480),
        ("Gorilla Haulers", "Facebook-Gorilla-HHG-FL-GA-NC", "Top Tier Van Lines", "Facebook-TTVL-HHG-FL-GA-NC", 120),
        ("Gorilla Haulers", "Facebook-Gorilla-HHG-Local", "Movers 95", "Facebook-Movers95-HHG-Local", 480),
        ("Wilson Bros Van Lines", "Facebook-WilsonBros-HHG-FL-GA-NC", "Top Tier Van Lines", "Facebook-TTVL-HHG-FL-GA-NC", 120),
    )
    session = SessionLocal()
    try:
        companies = {company.name: company for company in session.query(Company).all()}
        inserted = 0
        for source_name, source_campaign, target_name, target_campaign, delay_minutes in initial_rules:
            source = companies.get(source_name)
            target = companies.get(target_name)
            if source is None or target is None:
                logger.warning(
                    "Could not migrate duplication rule %s -> %s because a company is missing",
                    source_name,
                    target_name,
                )
                continue
            exists = session.query(LeadDuplicationRule.id).filter(
                LeadDuplicationRule.source_company_id == source.id,
                LeadDuplicationRule.source_referral_source == source_campaign,
                LeadDuplicationRule.target_company_id == target.id,
                LeadDuplicationRule.target_referral_source == target_campaign,
            ).first()
            if exists:
                continue
            session.add(LeadDuplicationRule(
                source_company_id=source.id,
                source_referral_source=source_campaign,
                target_company_id=target.id,
                target_referral_source=target_campaign,
                delay_minutes=delay_minutes,
                active=True,
            ))
            inserted += 1
        session.commit()
        logger.info("Migrated %s initial lead duplication rules", inserted)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    migrate()
