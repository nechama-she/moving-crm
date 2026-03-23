"""Import leads from DynamoDB into the CRM PostgreSQL database.

Creates a Lead for each lead that doesn't already exist (by leadgen_id).
Auto-creates "Gorilla Haulers" company and an admin user on first run.

Usage:
    python import_leads.py              # dry-run (preview)
    python import_leads.py --commit     # actually write to DB
    python import_leads.py --commit --limit 20   # import only the 20 most recent
"""

import sys
import logging

from database import SessionLocal
from models import Lead, Company, User, UserCompany
from auth import hash_password
from db import get_all_leads

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("import-leads")


MOVE_TYPE_MAP = {
    "out of state": "out_of_state",
    "within the state": "in_state",
    "out_of_state": "out_of_state",
    "in_state": "in_state",
}


def ensure_seed_data(session) -> str:
    """Create Gorilla Haulers company and admin user if they don't exist. Returns company_id."""
    company = session.query(Company).filter(Company.name == "Gorilla Haulers").first()
    if not company:
        company = Company(name="Gorilla Haulers")
        session.add(company)
        session.flush()
        logger.info("Created company: Gorilla Haulers")

    admin = session.query(User).filter(User.email == "admin@gorillamove.com").first()
    if not admin:
        admin = User(
            email="admin@gorillamove.com",
            name="Admin",
            password_hash=hash_password("admin123"),
            role="admin",
        )
        session.add(admin)
        session.flush()

        # Assign admin to the company
        session.add(UserCompany(user_id=admin.id, company_id=company.id))
        session.flush()
        logger.info("Created admin user: admin@gorillamove.com / admin123")

    return company.id


def import_leads(commit: bool = False, limit: int = 0):
    leads = get_all_leads()  # sorted by created_time desc (newest first)
    logger.info("Found %d leads in DynamoDB", len(leads))

    if limit:
        leads = leads[:limit]
        logger.info("Limiting to %d most recent leads", limit)

    session = SessionLocal()
    created = 0
    skipped = 0
    errors = 0

    try:
        company_id = ensure_seed_data(session)

        existing_ids = {
            row[0]
            for row in session.query(Lead.leadgen_id).filter(
                Lead.leadgen_id.isnot(None)
            ).all()
        }

        for lead in leads:
            leadgen_id = lead.get("leadgen_id", "")
            if not leadgen_id or leadgen_id in existing_ids:
                skipped += 1
                continue

            raw_move_type = lead.get(
                "are_you_moving_within_the_state_or_out_of_state?", ""
            ).lower().strip()

            try:
                new_lead = Lead(
                    company_id=company_id,
                    full_name=lead.get("full_name", "Unknown"),
                    email=lead.get("email", ""),
                    phone=lead.get("phone_number", ""),
                    source="facebook",
                    facebook_user_id=lead.get("user_id", ""),
                    leadgen_id=leadgen_id,
                    inbox_url=lead.get("inbox_url", ""),
                    pickup_zip=lead.get("pickup_zip", ""),
                    delivery_zip=lead.get("delivery_zip", ""),
                    move_size=lead.get("move_size", ""),
                    move_date=lead.get("when_is_the_move?", ""),
                    move_type=MOVE_TYPE_MAP.get(raw_move_type, raw_move_type),
                    created_time=lead.get("created_time", ""),
                    status="new",
                )
                session.add(new_lead)
                created += 1
                existing_ids.add(leadgen_id)
            except Exception as e:
                errors += 1
                logger.warning("Skipping lead %s: %s", leadgen_id, e)

        if commit:
            session.commit()
            logger.info("Committed %d new leads (%d skipped, %d errors)", created, skipped, errors)
        else:
            session.rollback()
            logger.info(
                "DRY RUN — would create %d leads (%d skipped, %d errors). Run with --commit to save.",
                created, skipped, errors,
            )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    do_commit = "--commit" in sys.argv
    do_limit = 0
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        do_limit = int(sys.argv[idx + 1])
    import_leads(commit=do_commit, limit=do_limit)
