"""Idempotent database migrations run by the deployment pipeline."""

import logging

from sqlalchemy import text

from database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")


def migrate() -> None:
    statement = """
    CREATE TABLE IF NOT EXISTS communication_associations (
        channel VARCHAR(20) NOT NULL,
        client_identifier VARCHAR(255) NOT NULL,
        company_identifier VARCHAR(255) NOT NULL,
        lead_id VARCHAR(36) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        company_id VARCHAR(36) NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        created_by VARCHAR(36) NOT NULL REFERENCES users(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (channel, client_identifier, company_identifier)
    )
    """
    with engine.begin() as connection:
        connection.execute(text(statement))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_communication_associations_lead_id ON communication_associations (lead_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_communication_associations_company_id ON communication_associations (company_id)"))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS smartmoving_referral_sources (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                normalized_name VARCHAR(255) NOT NULL UNIQUE,
                is_lead_provider BOOLEAN NOT NULL DEFAULT FALSE,
                is_public BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_smartmoving_referral_sources_normalized_name ON smartmoving_referral_sources (normalized_name)"))
    logger.info("communication_associations is ready")
    logger.info("smartmoving_referral_sources is ready")


if __name__ == "__main__":
    migrate()
