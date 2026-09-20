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
        connection.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS office_address TEXT NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_default_company BOOLEAN NOT NULL DEFAULT FALSE"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_default ON companies(is_default_company) WHERE is_default_company = TRUE"))
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
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS access_audit_logs (
                id VARCHAR(36) PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                user_name VARCHAR(255) NOT NULL DEFAULT 'Anonymous',
                user_email VARCHAR(255),
                user_role VARCHAR(50) NOT NULL DEFAULT 'anonymous',
                ip_address VARCHAR(100) NOT NULL,
                method VARCHAR(10) NOT NULL,
                path VARCHAR(1000) NOT NULL,
                query_params TEXT,
                status_code INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                user_agent TEXT,
                referer TEXT
            )
        """))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_access_audit_logs_created_at ON access_audit_logs (created_at DESC)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_access_audit_logs_user_id ON access_audit_logs (user_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_access_audit_logs_ip_address ON access_audit_logs (ip_address)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_access_audit_logs_path ON access_audit_logs (path)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_access_audit_logs_status_code ON access_audit_logs (status_code)"))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS local_pricing_routes (
                id VARCHAR(36) PRIMARY KEY,
                company_id VARCHAR(36) NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                pickup VARCHAR(64) NOT NULL,
                delivery VARCHAR(64) NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_local_pricing_routes_company_pair UNIQUE (company_id, pickup, delivery)
            )
        """))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_local_pricing_routes_company_id ON local_pricing_routes (company_id)"))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS lead_spark_inventory_items (
                id VARCHAR(36) PRIMARY KEY,
                job_id VARCHAR(36) NOT NULL REFERENCES lead_jobs(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                cuft NUMERIC(12, 2),
                amount NUMERIC(12, 2),
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_spark_inventory_items_job_id ON lead_spark_inventory_items (job_id)"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS system_permissions TEXT"))
    logger.info("communication_associations is ready")
    logger.info("smartmoving_referral_sources is ready")
    logger.info("access_audit_logs is ready")
    logger.info("local_pricing_routes is ready")
    logger.info("lead_spark_inventory_items is ready")
    logger.info("users.system_permissions is ready")


if __name__ == "__main__":
    migrate()
