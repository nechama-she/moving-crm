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
        connection.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_default_company BOOLEAN NOT NULL DEFAULT FALSE"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_default ON companies(is_default_company) WHERE is_default_company = TRUE"))
        connection.execute(text("ALTER TABLE leads ALTER COLUMN company_id DROP NOT NULL"))
        connection.execute(text("ALTER TABLE lead_jobs ALTER COLUMN company_id DROP NOT NULL"))
        connection.execute(text("ALTER TABLE lead_attachments ALTER COLUMN uploaded_by DROP NOT NULL"))
        connection.execute(text("ALTER TABLE lead_jobs ADD COLUMN IF NOT EXISTS stop_types TEXT"))
        from models import PublicMoveAccess, PublicMoveSession, WalkthroughRequest, PublicMoveUpload, PublicMoveRate, PublicMovePendingUpload
        for model in (PublicMoveAccess, PublicMoveSession, WalkthroughRequest, PublicMoveUpload, PublicMoveRate, PublicMovePendingUpload):
            model.__table__.create(connection, checkfirst=True)
        connection.execute(text("ALTER TABLE lead_attachments ALTER COLUMN file_size TYPE BIGINT"))
        connection.execute(text("ALTER TABLE public_move_pending_uploads ALTER COLUMN file_size TYPE BIGINT"))
        connection.execute(text("ALTER TABLE public_move_uploads ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) NOT NULL DEFAULT 'pending'"))
        connection.execute(text("ALTER TABLE public_move_uploads ADD COLUMN IF NOT EXISTS sync_token VARCHAR(36)"))
        connection.execute(text("ALTER TABLE public_move_uploads ADD COLUMN IF NOT EXISTS sync_error TEXT"))
        connection.execute(text("ALTER TABLE public_move_uploads ADD COLUMN IF NOT EXISTS sync_upload_url TEXT"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_walkthrough_active_job ON walkthrough_requests(job_id) WHERE status IN ('requested', 'scheduled')"))
        connection.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS quote_number VARCHAR(100)"))
        connection.execute(text("""CREATE TABLE IF NOT EXISTS lead_liveswitch (
            lead_id VARCHAR(36) PRIMARY KEY REFERENCES leads(id) ON DELETE CASCADE,
            details TEXT NOT NULL
        )"""))
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
