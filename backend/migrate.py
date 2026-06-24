"""Create all CRM tables in PostgreSQL.

Usage:
    python migrate.py          # create tables
    python migrate.py --drop   # drop + recreate (DEV ONLY)
"""

import sys
import logging

from sqlalchemy import text

from company_colors import resolve_company_color
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

    # Keep only essential fast, idempotent maintenance.
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS color VARCHAR(7)"))
        companies_missing_colors = conn.execute(text("""
            SELECT id, name, color
            FROM companies
            WHERE color IS NULL OR BTRIM(color) = ''
        """)).fetchall()
        for company_id, company_name, company_color in companies_missing_colors:
            conn.execute(
                text("UPDATE companies SET color = :color WHERE id = :company_id"),
                {"company_id": company_id, "color": resolve_company_color(company_name, company_color)},
            )

        # Normalize blank SmartMoving IDs to NULL and enforce uniqueness.
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
        conn.commit()

    logger.info("Done — tables: %s", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    drop = "--drop" in sys.argv
    migrate(drop_first=drop)
