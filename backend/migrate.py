"""Pending schema changes for the existing production database.

Every deploy runs this. Each change here runs once: after a deploy has applied it, it is removed, so with nothing
pending a deploy does not touch the database.
"""
import logging

from sqlalchemy import text

from database import engine

logger = logging.getLogger("migrate")


def add_column(connection, table, column, kind):
    """Adds the column only when it is missing: the ALTER locks the whole table even when the column exists,
    which on a live database waits on (or deadlocks with) the requests using it."""
    if not connection.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
                              {'table': table, 'column': column}).first():
        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {kind}'))


def create_master_book(connection):
    """The master pricing book (pricing_books), a copy of Gorilla Haulers East: no company and inactive, so it prices
    no job. Remove this step once a deploy has run it."""
    from uuid import uuid4
    from pricing_books import MASTER_KEY, copy_book, master_id
    if master_id(connection):
        return
    east = connection.execute(text("SELECT id FROM pricing_plans WHERE company_name = 'Gorilla Haulers' AND name = 'East'")).scalars().all()
    if len(east) != 1:
        logger.warning("Master pricing book not created: found %s Gorilla Haulers East books", len(east))
        return
    master = str(uuid4())
    connection.execute(text("""INSERT INTO pricing_plans (id, company_id, company_name, name, source_key, source_file, source_sheet,
                                   price_valid_days, active, sort_order)
                               VALUES (:id, NULL, 'Master', 'Default', :key, '', '', 7, FALSE, 0)"""), {'id': master, 'key': MASTER_KEY})
    copy_book(connection, east[0], master, keep=())
    logger.info("Created the master pricing book from Gorilla Haulers East")


def migrate() -> None:
    with engine.begin() as connection:
        create_master_book(connection)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
