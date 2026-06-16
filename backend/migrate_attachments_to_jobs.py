"""
One-time migration: add job_id column to lead_attachments and backfill
all existing attachments to their lead's Job 1 (lowest job_order row).

Run once on the target database:
    python migrate_attachments_to_jobs.py
"""

import os
import sys

# Allow running from the backend directory directly.
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
from models import LeadAttachment, LeadJob
from sqlalchemy import text


def run():
    db = SessionLocal()
    try:
        # 1. Add column if it does not already exist (idempotent).
        try:
            db.execute(text(
                "ALTER TABLE lead_attachments ADD COLUMN job_id VARCHAR(36) REFERENCES lead_jobs(id)"
            ))
            db.commit()
            print("Added job_id column to lead_attachments.")
        except Exception as exc:
            db.rollback()
            if "already exists" in str(exc).lower() or "duplicate column" in str(exc).lower():
                print("job_id column already exists, skipping ALTER.")
            else:
                raise

        # 2. Add index if not present (ignore error if already exists).
        try:
            db.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_lead_attachments_job_id ON lead_attachments (job_id)"
            ))
            db.commit()
        except Exception:
            db.rollback()

        # 3. Backfill: assign unlinked attachments to the Job 1 of their lead.
        attachments = (
            db.query(LeadAttachment)
            .filter(LeadAttachment.job_id.is_(None))
            .all()
        )

        if not attachments:
            print("No attachments to backfill.")
            return

        # Build a cache of lead_id -> primary job id (job_order == 1).
        lead_ids = list({a.lead_id for a in attachments})
        primary_jobs = (
            db.query(LeadJob)
            .filter(LeadJob.lead_id.in_(lead_ids), LeadJob.job_order == 1)
            .all()
        )
        primary_job_map = {j.lead_id: j.id for j in primary_jobs}

        updated = 0
        skipped = 0
        for attachment in attachments:
            job_id = primary_job_map.get(attachment.lead_id)
            if job_id:
                attachment.job_id = job_id
                updated += 1
            else:
                skipped += 1

        db.commit()
        print(f"Backfilled {updated} attachments to Job 1. Skipped {skipped} (no primary job found).")

    finally:
        db.close()


if __name__ == "__main__":
    run()
