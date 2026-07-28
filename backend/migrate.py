import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")


def migrate() -> None:
    """Ensure the database schema exists.

    ``create_all`` is idempotent — it only creates missing tables — so this is a
    no-op where the schema already exists (e.g. dev) and builds the full schema on a
    fresh database (e.g. a brand-new prod RDS). Importing ``models`` registers every
    ORM table on ``Base.metadata``.
    """
    import models  # noqa: F401 - registers all ORM tables on Base.metadata
    from models import Base
    from database import engine
    from sqlalchemy import text

    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE lead_update_logs ADD COLUMN IF NOT EXISTS sql_statements TEXT")
        )
    from database import SessionLocal
    from pricing_seed import seed_pricing

    db = SessionLocal()
    try:
        seeded = seed_pricing(db)
    finally:
        db.close()
    logger.info("Schema ensured via create_all; seeded %s pricing plans.", seeded)


if __name__ == "__main__":
    migrate()
