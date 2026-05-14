"""Create all CRM tables in PostgreSQL.

Usage:
    python migrate.py          # create tables
    python migrate.py --drop   # drop + recreate (DEV ONLY)
"""

import sys
import logging

from sqlalchemy import text

from database import engine
from models import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")


def migrate(drop_first: bool = False):
    if drop_first:
        logger.warning("Dropping all tables...")
        Base.metadata.drop_all(engine)

    logger.info("Creating tables...")
    Base.metadata.create_all(engine)

    # Keep existing databases in sync for new columns not handled by create_all.
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS facebook_page_id VARCHAR(100)"))
        conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS samrtmoving_branch_id VARCHAR(100)"))
        conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS granot_api_id VARCHAR(100)"))
        conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS granot_mover_ref VARCHAR(100)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_companies_facebook_page_id ON companies (facebook_page_id)"))
        conn.execute(text("ALTER TABLE sent_messages ALTER COLUMN message_type TYPE VARCHAR(100)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_outreach_events_created_at ON outreach_events (created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_outreach_events_outreach_type ON outreach_events (outreach_type)"))
        conn.execute(text("ALTER TABLE outreach_events ALTER COLUMN created_at SET DEFAULT NOW()"))
        conn.execute(text("UPDATE outreach_events SET created_at = NOW() WHERE created_at IS NULL"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_unavailability (
                id VARCHAR(36) PRIMARY KEY,
                admin_user_id VARCHAR(36) NOT NULL REFERENCES users(id),
                start_at TIMESTAMPTZ NOT NULL,
                end_at TIMESTAMPTZ NOT NULL,
                reason TEXT,
                created_by VARCHAR(36) NOT NULL REFERENCES users(id),
                created_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_admin_unavailability_admin_user_id ON admin_unavailability (admin_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_admin_unavailability_start_at ON admin_unavailability (start_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_admin_unavailability_end_at ON admin_unavailability (end_at)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_unavailability_reps (
                id VARCHAR(36) PRIMARY KEY,
                window_id VARCHAR(36) NOT NULL REFERENCES admin_unavailability(id),
                rep_user_id VARCHAR(36) NOT NULL REFERENCES users(id),
                created_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_admin_unavailability_reps_window_id ON admin_unavailability_reps (window_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_admin_unavailability_reps_rep_user_id ON admin_unavailability_reps (rep_user_id)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rep_availability_windows (
                id VARCHAR(36) PRIMARY KEY,
                rep_user_id VARCHAR(36) NOT NULL REFERENCES users(id),
                start_at TIMESTAMPTZ NOT NULL,
                end_at TIMESTAMPTZ NOT NULL,
                reason TEXT,
                created_by VARCHAR(36) NOT NULL REFERENCES users(id),
                created_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rep_availability_windows_rep_user_id ON rep_availability_windows (rep_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rep_availability_windows_start_at ON rep_availability_windows (start_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rep_availability_windows_end_at ON rep_availability_windows (end_at)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auto_assign_events (
                id SERIAL PRIMARY KEY,
                lead_id VARCHAR(36),
                company_id VARCHAR(36),
                assigned_to VARCHAR(36),
                assignment_mode VARCHAR(30) NOT NULL,
                assignment_reason VARCHAR(120) NOT NULL DEFAULT '',
                note TEXT,
                created_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_auto_assign_events_lead_id ON auto_assign_events (lead_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_auto_assign_events_company_id ON auto_assign_events (company_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_auto_assign_events_assigned_to ON auto_assign_events (assigned_to)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_auto_assign_events_assignment_mode ON auto_assign_events (assignment_mode)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_auto_assign_events_assignment_reason ON auto_assign_events (assignment_reason)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_auto_assign_events_created_at ON auto_assign_events (created_at)"))
        conn.execute(text("ALTER TABLE auto_assign_events ALTER COLUMN created_at SET DEFAULT NOW()"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key VARCHAR(120) PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30) NOT NULL DEFAULT ''"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS smartmoving_rep_id VARCHAR(100)"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS aircall_number_id VARCHAR(50)"))
        conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'sales_reps'
                ) THEN
                    UPDATE users u
                    SET aircall_number_id = sr.aircall_number_id
                    FROM sales_reps sr
                    WHERE u.aircall_number_id IS NULL
                      AND sr.aircall_number_id IS NOT NULL
                      AND LOWER(TRIM(u.name)) = LOWER(TRIM(sr.name));
                END IF;
            END
            $$;
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_smartmoving_rep_id ON users (smartmoving_rep_id)"))
        conn.commit()

    logger.info("Done — tables: %s", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    drop = "--drop" in sys.argv
    migrate(drop_first=drop)
