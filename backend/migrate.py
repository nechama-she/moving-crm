"""Create all CRM tables in PostgreSQL.

Usage:
    python migrate.py          # create tables
    python migrate.py --drop   # drop + recreate (DEV ONLY)
"""

import sys
import logging

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
    logger.info("Done — tables: %s", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    drop = "--drop" in sys.argv
    migrate(drop_first=drop)
