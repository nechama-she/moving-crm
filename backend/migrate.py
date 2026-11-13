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
    # Payments' confirmation numbers: new CRM payments get one; existing payments keep none. Remove after a deploy ran it.
    with engine.begin() as connection:
        add_column(connection, 'lead_payments', 'confirmation_number', 'VARCHAR(12) UNIQUE')
    # When the customer link was emailed, and to which (masked) address. Remove after a deploy ran it.
    with engine.begin() as connection:
        add_column(connection, 'public_move_access', 'link_email_sent_at', 'TIMESTAMP')
        add_column(connection, 'public_move_access', 'link_email_hint', 'VARCHAR(255)')
    # The inventory tables become the inventory: each row records the units item answers took off, the report's own
    # name for it, and its question key. Then every move's saved inventory moves into the tables (approved estimates
    # untouched), and the report items table, which only mirrored it, goes. Remove after a deploy ran it.
    with engine.begin() as connection:
        add_column(connection, 'inventory_edit_items', 'excluded_quantity', 'INTEGER NOT NULL DEFAULT 0')
        add_column(connection, 'inventory_edit_items', 'reference_name', 'VARCHAR(200)')
        add_column(connection, 'inventory_edit_items', 'question_key', 'VARCHAR(200)')
    from database import SessionLocal
    from inventory_migration import migrate_inventories
    logger.info('Moved %s inventories into the inventory tables', migrate_inventories(SessionLocal))
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE IF EXISTS lead_spark_inventory_items'))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
