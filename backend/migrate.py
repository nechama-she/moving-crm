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


def migrate() -> None:
    # SmartMoving's prices deleted from every job already signed on the customer page. Remove after a deploy ran it.
    from smartmoving_prices import drop_signed_smartmoving_prices
    with engine.begin() as connection:
        logger.info('Signed jobs without SmartMoving prices: %s', drop_signed_smartmoving_prices(connection))
    # Leads already signed on the customer page detached from SmartMoving (their ids kept aside). Remove after a deploy ran it.
    from smartmoving_prices import detach_signed_leads
    with engine.begin() as connection:
        logger.info('Signed leads detached from SmartMoving: %s', detach_signed_leads(connection))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
