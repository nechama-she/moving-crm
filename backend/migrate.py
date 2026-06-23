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
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS booked_move_date DATE"))
        # Normalize blank SmartMoving IDs to NULL, dedupe legacy rows,
        # then enforce uniqueness at the DB level.
        conn.execute(text("UPDATE leads SET smartmoving_id = NULL WHERE smartmoving_id IS NOT NULL AND BTRIM(smartmoving_id) = ''"))
        duplicate_groups = conn.execute(text("""
            SELECT COUNT(*)
            FROM (
                SELECT smartmoving_id
                FROM leads
                WHERE smartmoving_id IS NOT NULL
                GROUP BY smartmoving_id
                HAVING COUNT(*) > 1
            ) d
        """)).scalar() or 0
        if duplicate_groups:
            logger.warning("Found %s duplicate smartmoving_id group(s); keeping newest row per ID and nulling older duplicates", duplicate_groups)
            conn.execute(text("""
                WITH ranked AS (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY smartmoving_id
                            ORDER BY created_at DESC NULLS LAST, id DESC
                        ) AS rn
                    FROM leads
                    WHERE smartmoving_id IS NOT NULL
                )
                UPDATE leads l
                SET smartmoving_id = NULL
                FROM ranked r
                WHERE l.id = r.id
                  AND r.rn > 1
            """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_smartmoving_id
            ON leads (smartmoving_id)
            WHERE smartmoving_id IS NOT NULL
        """))
        conn.execute(text("""
            UPDATE leads
            SET booked_move_date = CASE
                WHEN move_date ~ '^\\d{4}-\\d{2}-\\d{2}$' THEN move_date::date
                WHEN move_date ~ '^\\d{1,2}/\\d{1,2}/\\d{4}$' THEN
                    CASE
                        -- If first token cannot be month, treat as DD/MM/YYYY.
                        WHEN split_part(move_date, '/', 1)::int > 12
                             AND split_part(move_date, '/', 2)::int BETWEEN 1 AND 12
                        THEN to_date(move_date, 'DD/MM/YYYY')
                        -- If second token cannot be day in MM/DD/YYYY month position,
                        -- treat as MM/DD/YYYY.
                        WHEN split_part(move_date, '/', 2)::int > 12
                             AND split_part(move_date, '/', 1)::int BETWEEN 1 AND 12
                        THEN to_date(move_date, 'MM/DD/YYYY')
                        -- Ambiguous values (both <= 12): keep existing behavior.
                        WHEN split_part(move_date, '/', 1)::int BETWEEN 1 AND 12
                             AND split_part(move_date, '/', 2)::int BETWEEN 1 AND 12
                        THEN to_date(move_date, 'MM/DD/YYYY')
                        ELSE NULL
                    END
                ELSE NULL
            END
            WHERE booked_move_date IS NULL
              AND COALESCE(TRIM(move_date), '') <> ''
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_company_id_booked_move_date ON leads (company_id, booked_move_date)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lead_attachments (
                id VARCHAR(36) PRIMARY KEY,
                lead_id VARCHAR(36) NOT NULL REFERENCES leads(id),
                file_name VARCHAR(255) NOT NULL,
                content_type VARCHAR(120) NOT NULL DEFAULT 'application/octet-stream',
                file_size INTEGER NOT NULL DEFAULT 0,
                file_blob BYTEA NOT NULL,
                uploaded_by VARCHAR(36) NOT NULL REFERENCES users(id),
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_attachments_lead_id ON lead_attachments (lead_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_attachments_created_at ON lead_attachments (created_at)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lead_jobs (
                id VARCHAR(36) PRIMARY KEY,
                lead_id VARCHAR(36) NOT NULL REFERENCES leads(id),
                company_id VARCHAR(36) NOT NULL REFERENCES companies(id),
                job_order INTEGER NOT NULL DEFAULT 1,
                pickup_zip TEXT,
                delivery_zip TEXT,
                move_date TEXT,
                booked_move_date DATE,
                price NUMERIC(12,2),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_lead_jobs_lead_order UNIQUE (lead_id, job_order)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_jobs_lead_id ON lead_jobs (lead_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_jobs_company_id ON lead_jobs (company_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_jobs_booked_move_date ON lead_jobs (booked_move_date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_jobs_created_at ON lead_jobs (created_at)"))
        conn.execute(text("""
            INSERT INTO lead_jobs (
                id, lead_id, company_id, job_order, pickup_zip, delivery_zip,
                move_date, booked_move_date, created_at, updated_at
            )
            SELECT
                md5(random()::text || clock_timestamp()::text || l.id),
                l.id,
                l.company_id,
                1,
                l.pickup_zip,
                l.delivery_zip,
                l.move_date,
                l.booked_move_date,
                NOW(),
                NOW()
            FROM leads l
            WHERE NOT EXISTS (
                SELECT 1 FROM lead_jobs lj WHERE lj.lead_id = l.id
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dispatch_calendar_days (
                id VARCHAR(36) PRIMARY KEY,
                company_id VARCHAR(36) NOT NULL REFERENCES companies(id),
                day_date DATE NOT NULL,
                is_full BOOLEAN NOT NULL DEFAULT FALSE,
                note TEXT,
                updated_by VARCHAR(36) NOT NULL REFERENCES users(id),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_dispatch_calendar_days_company_day ON dispatch_calendar_days (company_id, day_date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_dispatch_calendar_days_company_id ON dispatch_calendar_days (company_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_dispatch_calendar_days_day_date ON dispatch_calendar_days (day_date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_dispatch_calendar_days_updated_at ON dispatch_calendar_days (updated_at)"))
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
