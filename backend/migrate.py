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
    # The work queue's Customer page and Customer chat cards (a new, empty table). Remove after a deploy ran it.
    with engine.begin() as connection:
        from models import CustomerPageState
        CustomerPageState.__table__.create(connection, checkfirst=True)
        # Where the table was made before it had the code stage.
        add_column(connection, 'customer_page_states', 'code_channel', 'VARCHAR(10)')
    # Each user's order of the work queue cards (a new, empty table). Remove after a deploy ran it.
    with engine.begin() as connection:
        from models import WorkQueueCardOrder
        WorkQueueCardOrder.__table__.create(connection, checkfirst=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
