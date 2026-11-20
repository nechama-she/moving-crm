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
    # Rep discounts on fee tabs (a new, empty table). Remove after a deploy ran it.
    from sqlalchemy import inspect
    from models import JobSectionDiscount
    with engine.begin() as connection:
        if not inspect(connection).has_table(JobSectionDiscount.__tablename__):
            JobSectionDiscount.__table__.create(connection)
            logger.info('Created table %s', JobSectionDiscount.__tablename__)
    # The archive of signed PDFs (a new, empty table). Remove after a deploy ran it.
    from models import SignedPdfArchive
    with engine.begin() as connection:
        if not inspect(connection).has_table(SignedPdfArchive.__tablename__):
            SignedPdfArchive.__table__.create(connection)
            logger.info('Created table %s', SignedPdfArchive.__tablename__)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
